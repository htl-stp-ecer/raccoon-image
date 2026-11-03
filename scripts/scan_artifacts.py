#!/usr/bin/env python3
"""Read the transport contract marker out of built release artifacts.

Every artifact that contains the compiled transport carries the string
``RACCOON_CONTRACT_V1=<16 hex>`` (see raccoon-transport, scripts/contract.py).
This scans wheels, .deb packages and tarballs without running anything and
compares what it finds with the hash the bundle expects.

    scan_artifacts.py <inputs dir> <expected hash>
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import BinaryIO, Iterator

PREFIX = b"RACCOON_CONTRACT_V1="
MARKER = re.compile(re.escape(PREFIX) + rb"([0-9a-f]{16})")
CHUNK = 4 * 1024 * 1024

# (component directory below the inputs, file pattern). These contain compiled
# transport code, so each must carry exactly the expected marker. A missing
# marker fails the scan: a component type that cannot be checked must be fixed,
# never skipped.
REQUIRED = [
    ("raccoon-lib", "raccoon_sim-*aarch64*.whl"),
    ("botui", "botui_*_arm64.deb"),
    ("stm32-data-reader", "stm32_data_reader-*.tar.gz"),
]
# Pure Python or without transport code: any marker found must still match.
OPTIONAL = [
    ("raccoon-lib", "raccoon_library-*.whl"),
    ("raccoon-cli", "raccoon_cli-*.whl"),
]


def markers_in_stream(stream: BinaryIO) -> set[str]:
    found: set[str] = set()
    tail = b""
    while True:
        block = stream.read(CHUNK)
        if not block:
            return found
        data = tail + block
        found.update(m.decode() for m in MARKER.findall(data))
        tail = data[-(len(PREFIX) + 16):]


def _tar_markers(tar: tarfile.TarFile) -> set[str]:
    found: set[str] = set()
    for member in tar:
        if member.isfile():
            handle = tar.extractfile(member)
            if handle is not None:
                found |= markers_in_stream(handle)
    return found


def markers_in_file(path: Path) -> set[str]:
    name = path.name
    if name.endswith(".whl") or name.endswith(".zip"):
        found: set[str] = set()
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if not info.is_dir():
                    with archive.open(info) as handle:
                        found |= markers_in_stream(handle)
        return found
    if name.endswith(".deb"):
        process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(path)], stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as tar:
                found = _tar_markers(tar)
        finally:
            process.stdout.close()
            if process.wait() != 0:
                raise ValueError(f"dpkg-deb could not read {path.name}")
        return found
    if name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar")):
        with tarfile.open(path, mode="r:*") as tar:
            return _tar_markers(tar)
    with path.open("rb") as handle:
        return markers_in_stream(handle)


def _select(inputs: Path, directory: str, pattern: str) -> list[Path]:
    base = inputs / directory
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if fnmatch.fnmatchcase(p.name, pattern))


def scan_inputs(inputs: Path, expected: str) -> list[tuple[str, str, str]]:
    """Return rows (artifact, found hashes, verdict). Raises ValueError with a table on any failure."""
    rows: list[tuple[str, str, str]] = []
    failed = False
    for required, entries in ((True, REQUIRED), (False, OPTIONAL)):
        for directory, pattern in entries:
            files = _select(inputs, directory, pattern)
            if required and not files:
                rows.append((f"{directory}/{pattern}", "-", "MISSING ARTIFACT"))
                failed = True
            for path in files:
                found = markers_in_file(path)
                label = f"{directory}/{path.name}"
                if not found:
                    verdict = "NO MARKER" if required else "no marker (not required)"
                    failed = failed or required
                    rows.append((label, "-", verdict))
                elif found != {expected}:
                    rows.append((label, ", ".join(sorted(found)), f"MISMATCH (expected {expected})"))
                    failed = True
                else:
                    rows.append((label, expected, "ok"))
    if failed:
        raise ValueError("Transport contract gate failed:\n" + format_table(rows) +
                         "\nA component built against another transport than the bundle's must be "
                         "rebuilt (bump its transport submodule and release it) before this bundle can be made.")
    return rows


def format_table(rows: list[tuple[str, str, str]]) -> str:
    header = ("artifact", "found", "result")
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(3)]
    lines = ["  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) for row in [header, *rows]]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        rows = scan_inputs(Path(argv[1]), argv[2])
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(format_table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
