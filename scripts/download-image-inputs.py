#!/usr/bin/env python3
"""Resolve released components once, verify their digests, and record provenance."""
import fnmatch
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = "htl-stp-ecer/raccoon-image"
BASE_TAG = "v2.0.0"
BASE_ASSET = "raccoon-os-2026-07-17.img.xz"
BASE_SHA256 = "782a0fcad23a9ac84c9c458ab678a28b5bb53b087248de5183809612ee10a5c2"
COMPONENTS = {
    "raccoon-lib": "raccoon_library-*.whl",
    "raccoon-cli": "raccoon-server-*.tar.gz",
    "stm32-data-reader": "stm32_data_reader-*.tar.gz",
    "botui": "stp-velox_*_arm64.deb",
}


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
    manifest = {"base": download(REPO, BASE_TAG, BASE_ASSET, dest / "base", BASE_SHA256),
                "components": {}}
    for component, pattern in COMPONENTS.items():
        manifest["components"][component] = download(
            f"htl-stp-ecer/{component}", None, pattern, dest / component)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
