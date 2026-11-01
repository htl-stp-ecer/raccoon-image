#!/usr/bin/env python3
"""Resolve released components once, verify their digests, and record provenance."""
import fnmatch
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = "htl-stp-ecer/raccoon-image"
BASE_TAG = "base-2026-11-01"
BASE_CHECKSUM_FILE = Path(__file__).parents[1] / "debian-trixie/base-image/raccoon-os-base.img.xz.sha256"
# (name in the manifest, repository, asset pattern, directory below the inputs).
# Two entries may share a directory; they must then come from the same release.
COMPONENTS = [
    ("raccoon-lib", "raccoon-lib", "raccoon_library-*.whl", "raccoon-lib"),
    ("raccoon-sim", "raccoon-lib", "raccoon_sim-*aarch64*.whl", "raccoon-lib"),
    ("raccoon-cli", "raccoon-cli", "raccoon-server-*.tar.gz", "raccoon-cli"),
    ("stm32-data-reader", "stm32-data-reader", "stm32_data_reader-*.tar.gz", "stm32-data-reader"),
    ("botui", "botui", "stp-velox_*_arm64.deb", "botui"),
]


def read_base_checksum(path=BASE_CHECKSUM_FILE):
    """Return (sha256, asset name) from a `sha256sum` style file."""
    parts = path.read_text().split()
    if len(parts) != 2 or len(parts[0]) != 64:
        raise ValueError(f"Invalid checksum file: {path}")
    return parts[0], parts[1].lstrip("*")


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
    base_sha256, base_asset = read_base_checksum()
    manifest = {"base": download(REPO, BASE_TAG, base_asset, dest / "base", base_sha256),
                "components": {}}
    tags = {}
    for name, repo, pattern, directory in COMPONENTS:
        entry = download(f"htl-stp-ecer/{repo}", None, pattern, dest / directory)
        if tags.setdefault(repo, entry["tag"]) != entry["tag"]:
            raise ValueError(f"{repo} published a new release during the download; run again")
        manifest["components"][name] = entry
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
