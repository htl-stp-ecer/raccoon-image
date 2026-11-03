#!/usr/bin/env python3
"""Resolve released components once, verify their digests, and record provenance."""
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent))
from scan_artifacts import format_table, scan_inputs  # noqa: E402

REPO = "htl-stp-ecer/raccoon-image"
TRANSPORT = "raccoon-transport"
HASH_PATTERN = re.compile(r"[0-9a-f]{16}")
BASE_TAG = "base-2026-11-01"
BUNDLES_DIR = Path(__file__).parents[1] / "bundles"
BASE_CHECKSUM_FILE = Path(__file__).parents[1] / "debian-trixie/base-image/raccoon-os-base.img.xz.sha256"
# (name in the manifest, repository, asset pattern, directory below the inputs).
# Two entries may share a directory; they must then come from the same release.
COMPONENTS = [
    ("raccoon-lib", "raccoon-lib", "raccoon_library-*.whl", "raccoon-lib"),
    ("raccoon-sim", "raccoon-lib", "raccoon_sim-*aarch64*.whl", "raccoon-lib"),
    ("raccoon-cli", "raccoon-cli", "raccoon-server-*.tar.gz", "raccoon-cli"),
    ("stm32-data-reader", "stm32-data-reader", "stm32_data_reader-*.tar.gz", "stm32-data-reader"),
    ("botui", "botui", "botui_*_arm64.deb", "botui"),
]


def read_base_checksum(path=BASE_CHECKSUM_FILE):
    """Return (sha256, asset name) from a `sha256sum` style file."""
    parts = path.read_text().split()
    if len(parts) != 2 or len(parts[0]) != 64:
        raise ValueError(f"Invalid checksum file: {path}")
    return parts[0], parts[1].lstrip("*")


def read_bundle(bundle=None, bundles_dir=None):
    """Return (bundle name, {repository: release tag}) of a bundle manifest.

    Without a name, bundles/latest.json points at the bundle to use.
    """
    bundles_dir = bundles_dir or BUNDLES_DIR
    if bundle is None:
        bundle = json.loads((bundles_dir / "latest.json").read_text())["ref"]
    if Path(bundle).name != bundle:
        raise ValueError(f"Invalid bundle name: {bundle}")
    if bundle == "dev":
        raise ValueError("The dev bundle is never built into an image")
    components = json.loads((bundles_dir / f"{bundle}.json").read_text())["components"]
    missing = sorted({repo for _, repo, _, _ in COMPONENTS} - {r for r, t in components.items() if t})
    if missing:
        raise ValueError(f"Bundle {bundle} has no release for: {', '.join(missing)}")
    return bundle, components


def normalize_tag(tag):
    """Release tags of the transport are v<number>; bundles may write the bare number."""
    tag = tag.strip()
    return tag if tag.startswith("v") else f"v{tag}"


def read_contract(bundle, bundles_dir=None):
    """Return {"tag", "hash"} of the transport contract in a bundle, or None for older bundles.

    Bundles made before the contract check have neither a transport tag nor a hash
    and stay buildable. Once either is present, both must be valid, and `dev` is
    never accepted for an image.
    """
    document = json.loads(((bundles_dir or BUNDLES_DIR) / f"{bundle}.json").read_text())
    if document.get("bundle") == "dev":
        raise ValueError("The dev bundle is never built into an image")
    tag = (document.get("components") or {}).get(TRANSPORT)
    has_hash = "contract_hash" in document
    if not tag and not has_hash:
        return None
    value = document.get("contract_hash")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Bundle {bundle} has an empty contract_hash")
    value = value.strip()
    if value == "dev":
        raise ValueError(f"Bundle {bundle} has contract_hash 'dev'; images are never built from it")
    if not HASH_PATTERN.fullmatch(value):
        raise ValueError(f"Bundle {bundle} has an invalid contract_hash: {value!r}")
    if not tag:
        raise ValueError(f"Bundle {bundle} has a contract_hash but no {TRANSPORT} tag")
    if not re.fullmatch(r"v?\d+", tag):
        raise ValueError(f"Bundle {bundle} has an invalid {TRANSPORT} tag: {tag!r}")
    return {"tag": normalize_tag(tag), "hash": value}


def verify_transport_release(contract, dest):
    """Download the transport release's contract-hash.txt and require it to equal the bundle's hash."""
    entry = download(f"htl-stp-ecer/{TRANSPORT}", contract["tag"], "contract-hash.txt", dest)
    published = (dest / "contract-hash.txt").read_text().strip()
    if published != contract["hash"]:
        raise ValueError(
            f"Bundle claims contract hash {contract['hash']} for {TRANSPORT} {contract['tag']}, "
            f"but that release published {published}")
    return {**entry, "contract_hash": published}


def select_asset(release, pattern):
    assets = [a for a in release["assets"] if fnmatch.fnmatchcase(a["name"], pattern)]
    if len(assets) != 1:
        raise ValueError(f"Expected one {pattern} asset, found {len(assets)}")
    asset = assets[0]
    if Path(asset["name"]).name != asset["name"]:
        raise ValueError("Invalid asset filename")
    digest = asset.get("digest") or ""
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError(f"Missing SHA-256 digest for {asset['name']}")
    return asset


def download(repo, tag, pattern, dest, expected=None):
    endpoint = f"repos/{repo}/releases/" + (f"tags/{tag}" if tag else "latest")
    release = json.loads(subprocess.check_output(["gh", "api", endpoint]))
    asset = select_asset(release, pattern)
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gh", "release", "download", release["tag_name"], "--repo", repo,
                    "--pattern", asset["name"], "--dir", str(dest)], check=True)
    path = dest / asset["name"]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != asset["digest"].removeprefix("sha256:") or (expected and actual != expected):
        raise ValueError(f"Checksum mismatch: {path}")
    return {"repository": repo, "tag": release["tag_name"], "asset": asset["name"],
            "sha256": actual, "url": asset["browser_download_url"]}


def main():
    dest = Path(sys.argv[1])
    bundle, tags = read_bundle(sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None)
    base_sha256, base_asset = read_base_checksum()
    contract = read_contract(bundle)
    manifest = {"bundle": bundle,
                "base": download(REPO, BASE_TAG, base_asset, dest / "base", base_sha256),
                "components": {}}
    for name, repo, pattern, directory in COMPONENTS:
        manifest["components"][name] = download(
            f"htl-stp-ecer/{repo}", tags[repo], pattern, dest / directory)
    if contract:
        manifest["components"][TRANSPORT] = verify_transport_release(contract, dest / TRANSPORT)
        # Blocking gate: every artifact with compiled transport code must carry the bundle's hash.
        print(format_table(scan_inputs(dest, contract["hash"])))
        # The device gets the bundle manifest itself (see raccoon-transport contract/CHECK_SPEC.md).
        (dest / "raccoon-bundle.json").write_text(
            (BUNDLES_DIR / f"{bundle}.json").read_text())
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
