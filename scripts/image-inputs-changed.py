#!/usr/bin/env python3
"""Tell whether a new image is due: compare the inputs a build would use with those of the last published image."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = "htl-stp-ecer/raccoon-image"

spec = importlib.util.spec_from_file_location(
    "inputs", Path(__file__).parent / "download-image-inputs.py")
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def current_tags():
    """Release tag of every input a build would download now."""
    tags = {"base": inputs.BASE_TAG}
    latest = {}
    for name, repo, _pattern, _directory in inputs.COMPONENTS:
        if repo not in latest:
            latest[repo] = json.loads(gh(
                "release", "view", "--repo", f"htl-stp-ecer/{repo}", "--json", "tagName"))["tagName"]
        tags[name] = latest[repo]
    return tags


def last_image_manifest():
    """manifest.json of the newest published (non-draft) image release, or None."""
    releases = json.loads(gh("release", "list", "--repo", REPO, "--limit", "100",
                             "--json", "tagName,isDraft,publishedAt"))
    images = [r for r in releases if r["tagName"].startswith("image-") and not r["isDraft"]]
    if not images:
        return None
    newest = max(images, key=lambda r: r["publishedAt"])
    with tempfile.TemporaryDirectory() as directory:
        gh("release", "download", newest["tagName"], "--repo", REPO,
           "--pattern", "manifest.json", "--dir", directory)
        return json.loads((Path(directory) / "manifest.json").read_text())


def differences(previous, current):
    """Names of the inputs whose tag differs from the last image (all of them if there is none)."""
    if previous is None:
        return sorted(current)
    used = {"base": previous.get("base", {}).get("tag")}
    for name, entry in previous.get("components", {}).items():
        used[name] = entry.get("tag")
    return sorted(name for name, tag in current.items() if used.get(name) != tag)


def main():
    current = current_tags()
    try:
        previous = last_image_manifest()
    except (subprocess.CalledProcessError, ValueError, OSError) as error:
        print(f"Could not read the last image's manifest ({error}); building.")
        previous = None
    changed = differences(previous, current)
    for name in changed:
        print(f"changed: {name} -> {current[name]}")
    if not changed:
        print("No input changed since the last image; nothing to build.")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as output:
        output.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    sys.exit(main())
