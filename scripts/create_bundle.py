#!/usr/bin/env python3
"""Create a numbered bundle from component releases, behind the transport contract gate.

Run by .github/workflows/create-bundle.yml. Resolves the five versions, downloads
and verifies the release assets (digests, one asset per pattern), checks that
every artifact with compiled transport code carries the contract hash of the
target transport release, picks the next name of the day and writes
bundles/<name>.json and bundles/latest.json. It never commits or pushes; the
workflow does that, and only after this script succeeded.

There is deliberately no option to skip the gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).parent
ROOT = SCRIPTS.parent
BUNDLES_DIR = ROOT / "bundles"
ORG = "htl-stp-ecer"
NAME_PATTERN = re.compile(r"^(\d{4}\.\d{2}\.\d{2})(?:-(\d+))?$")
TAG_PATTERN = re.compile(r"^v?\d+(\.\d+)*$")
TIMEZONE = ZoneInfo("Europe/Vienna")

sys.path.insert(0, str(SCRIPTS))
from scan_artifacts import format_table, scan_inputs  # noqa: E402

_spec = importlib.util.spec_from_file_location("image_inputs", SCRIPTS / "download-image-inputs.py")
image_inputs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(image_inputs)

# manifest key -> repository
INPUT_REPOS = {
    "raccoon-cli": "raccoon-cli",
    "raccoon-lib": "raccoon-lib",
    "raccoon-transport": "raccoon-transport",
    "botui": "botui",
    "stm32-data-reader": "stm32-data-reader",
}


class BundleError(Exception):
    pass


# ── Names ────────────────────────────────────────────────────────────────


def valid_name(name: str) -> bool:
    return bool(NAME_PATTERN.fullmatch(name))


def today_prefix(now: datetime | None = None) -> str:
    now = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE)
    return now.strftime("%Y.%m.%d")


def next_bundle_name(existing: list[str], prefix: str) -> str:
    """First bundle of a day is `YYYY.MM.DD`, then `-2`, `-3` ...

    Only names in the new pattern count; `dev`, `latest` and older formats such
    as `2026.5.25.1` are ignored. A name without suffix counts as 1.
    """
    highest = 0
    for name in existing:
        match = NAME_PATTERN.fullmatch(name)
        if match and match.group(1) == prefix:
            highest = max(highest, int(match.group(2)) if match.group(2) else 1)
    name = prefix if highest == 0 else f"{prefix}-{highest + 1}"
    if not valid_name(name):
        raise BundleError(f"Refusing to use bundle name {name!r}")
    return name


def existing_names(bundles_dir: Path) -> list[str]:
    return [p.stem for p in bundles_dir.glob("*.json")]


# ── Versions ─────────────────────────────────────────────────────────────


def tag_candidates(value: str) -> list[str]:
    """A tag as typed on the release page; a missing leading `v` is tolerated."""
    value = value.strip()
    if not TAG_PATTERN.fullmatch(value):
        raise BundleError(f"{value!r} is not a release tag (expected something like v155)")
    bare = value[1:] if value.startswith("v") else value
    return [f"v{bare}", bare]


def gh_api(endpoint: str) -> dict | None:
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True)
    if result.returncode != 0:
        if "Not Found" in result.stderr or "404" in result.stderr:
            return None
        raise BundleError(f"gh api {endpoint} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def resolve_tag(repo: str, requested: str, api=gh_api) -> str:
    """The release tag to use: the given one (either spelling), or the newest published release."""
    requested = (requested or "").strip()
    if not requested:
        release = api(f"repos/{ORG}/{repo}/releases/latest")  # skips drafts and pre-releases
        if not release:
            raise BundleError(f"{repo} has no published release")
        return release["tag_name"]
    for candidate in tag_candidates(requested):
        release = api(f"repos/{ORG}/{repo}/releases/tags/{candidate}")
        if release and not release.get("draft"):
            return release["tag_name"]
    raise BundleError(f"{repo} has no release {requested!r} (tried {' and '.join(tag_candidates(requested))})")


# ── Bundle ───────────────────────────────────────────────────────────────


def build_manifest(name: str, tags: dict[str, str], contract_hash: str) -> dict:
    return {
        "bundle": name,
        "components": {
            "raccoon-lib": tags["raccoon-lib"],
            "raccoon-cli": tags["raccoon-cli"],
            "stm32-data-reader": tags["stm32-data-reader"],
            "raccoon-cam": "",
            "botui": tags["botui"],
            "raccoon-transport": tags["raccoon-transport"],
        },
        "contract_hash": contract_hash,
    }


def gate(tags: dict[str, str], scratch: Path) -> str:
    """Download and verify everything, return the transport contract hash. Raises BundleError."""
    transport_tag = image_inputs.normalize_tag(tags["raccoon-transport"])
    try:
        entry = image_inputs.download(
            f"{ORG}/raccoon-transport", transport_tag, "contract-hash.txt", scratch / "raccoon-transport")
    except (ValueError, subprocess.CalledProcessError) as error:
        raise BundleError(
            f"raccoon-transport {transport_tag} has no usable contract-hash.txt asset ({error}). "
            "Only transport releases made after the contract hash was introduced can be bundled.") from error
    contract_hash = (scratch / "raccoon-transport" / "contract-hash.txt").read_text().strip()
    if not image_inputs.HASH_PATTERN.fullmatch(contract_hash):
        raise BundleError(f"raccoon-transport {transport_tag} published an invalid contract hash: {contract_hash!r}")
    del entry

    try:
        for _, repo, pattern, directory in image_inputs.COMPONENTS:
            image_inputs.download(f"{ORG}/{repo}", tags[repo], pattern, scratch / directory)
    except (ValueError, subprocess.CalledProcessError) as error:
        raise BundleError(f"Release check failed: {error}") from error

    try:
        scan_inputs(scratch, contract_hash)
    except ValueError as error:
        raise BundleError(
            f"{error}\n\nTransport {transport_tag} (contract {contract_hash}) is the target. "
            "After a transport release the components must first merge their transport bump PR "
            "and be released again; until then a bundle with the newest transport cannot be made.") from error
    return contract_hash


def write_files(bundles_dir: Path, manifest: dict) -> None:
    bundles_dir.mkdir(exist_ok=True)
    name = manifest["bundle"]
    if not valid_name(name):
        raise BundleError(f"Refusing to use bundle name {name!r}")
    (bundles_dir / f"{name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (bundles_dir / "latest.json").write_text(json.dumps({"ref": name}, indent=2) + "\n")


def summary(tags: dict[str, str], requested: dict[str, str], name: str, contract_hash: str) -> str:
    lines = ["| component | requested | resolved |", "| --- | --- | --- |"]
    for key in INPUT_REPOS:
        lines.append(f"| {key} | {requested.get(key) or 'latest'} | {tags[key]} |")
    return f"### Bundle {name}\n\nContract hash `{contract_hash}`\n\n" + "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for key in INPUT_REPOS:
        parser.add_argument(f"--{key}", default="", help="release tag; empty = newest published release")
    args = parser.parse_args(argv)
    requested = {key: getattr(args, key.replace("-", "_")) for key in INPUT_REPOS}

    try:
        tags = {key: resolve_tag(repo, requested[key]) for key, repo in INPUT_REPOS.items()}
        print("Resolved:", json.dumps(tags, indent=2))
        with tempfile.TemporaryDirectory() as scratch:
            contract_hash = gate(tags, Path(scratch))
        name = next_bundle_name(existing_names(BUNDLES_DIR), today_prefix())
        manifest = build_manifest(name, tags, contract_hash)
        write_files(BUNDLES_DIR, manifest)
    except BundleError as error:
        print(f"::error::{str(error).splitlines()[0]}")
        print(error, file=sys.stderr)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as out:
                out.write(f"### Bundle not created\n\n```\n{error}\n```\n")
        return 1

    text = summary(tags, requested, name, contract_hash)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as out:
            out.write(text)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"name={name}\ncontract_hash={contract_hash}\n")
            out.write(f"cli={tags['raccoon-cli']}\nlib={tags['raccoon-lib']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
