#!/usr/bin/env python3
"""Audit built bundles for files that must never be published.

`build_bundles.py` uses a whitelist, so in principle nothing unwanted can get
in. This script assumes that principle will eventually be violated — by a
config edit, a renamed folder, a well-meant "just add this one directory" —
and checks the finished archives independently — both the names of the entries
and, for text formats, what is inside them.

Run it before every release, and in CI on any commit that touches
`bundles.config.json`.

    python3 scripts/audit_bundles.py data/bundles/0.1.0-draft
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

# (pattern, why it must not be published)
FORBIDDEN: list[tuple[str, str]] = [
    (r"TOR", "procurement document"),
    (r"\.bak_", "backup of a procurement document"),
    (r"^~\$", "Office lock file"),
    (r"ราคากลาง", "median-price evidence (procurement)"),
    (r"invoice", "supplier invoice"),
    (r"snaptik", "video downloaded from TikTok — third-party content"),
    (r"roi_wilor_overlay", "derived from the TikTok source video"),
    (r"^orig_\d{9,}", "filename is a Facebook photo ID"),
    (r"^\d{9,}_\d{9,}", "filename is a Facebook photo ID"),
    (r"โนราคล้ายขี้หนอน", "book scan — copyright not yet confirmed"),
    (r"^tha\d+\.jpg$", "costume image — provenance not confirmed"),
    (r"^14184-BIG", "costume image — provenance not confirmed"),
    (r"^9-4\.jpg$", "costume image — provenance not confirmed"),
    (r"^07_", "pose pair 07 is unmapped and pending expert review"),
    (r"\.DS_Store$", "macOS metadata"),
    (r"^\._", "macOS resource fork"),
    (r"\.env$", "environment file"),
    (r"\.env\.", "environment file (.env.production and friends)"),
    (r"id_rsa", "private key"),
    (r"\.pem$", "private key or certificate"),
]

COMPILED = [(re.compile(pattern), reason) for pattern, reason in FORBIDDEN]

# Checking names alone missed a whole class of leak: the pipeline used Facebook
# photo filenames as pose_id values, so the IDs travelled inside
# pose_library.json, manifest.json and manifest.csv while the archive entries
# were innocently named. These patterns are matched against the text of every
# entry small enough to read.
FORBIDDEN_CONTENT: list[tuple[str, str]] = [
    (r"\d{9,}_\d{9,}", "Facebook photo ID inside the file"),
    (r"snaptik", "reference to a TikTok-sourced video"),
]

COMPILED_CONTENT = [(re.compile(p), reason) for p, reason in FORBIDDEN_CONTENT]

# Only text formats are scanned, and only up to this size: the point is to
# catch identifiers in metadata, not to grep through video.
SCANNED_SUFFIXES = {".json", ".csv", ".txt", ".md", ".yml", ".yaml", ".xml", ".srt"}
MAX_SCAN_BYTES = 32 * 1024 * 1024


def scan_entry_content(archive: zipfile.ZipFile, info: zipfile.ZipInfo):
    """Yield (reason, sample) for each forbidden pattern found inside *info*."""
    name = info.filename
    if name.endswith("/"):
        return
    if Path(name).suffix.lower() not in SCANNED_SUFFIXES:
        return
    if info.file_size > MAX_SCAN_BYTES:
        print(f"  ! not scanned, too large: {name} ({info.file_size} bytes)")
        return

    try:
        text = archive.read(name).decode("utf-8", errors="replace")
    except (KeyError, OSError) as exc:  # pragma: no cover - corrupt archive
        print(f"  ! could not read {name}: {exc}", file=sys.stderr)
        return

    for pattern, reason in COMPILED_CONTENT:
        found = pattern.search(text)
        if found:
            yield reason, found.group(0)


def audit(directory: Path) -> int:
    archives = sorted(directory.glob("*.zip"))
    if not archives:
        print(f"error: no .zip files found in {directory}", file=sys.stderr)
        return 2

    leaks: list[tuple[str, str, str]] = []
    checked = 0

    for archive_path in archives:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            checked += len(infos)
            print(f"{archive_path.name}: {len(infos)} entries")

            for info in infos:
                name = info.filename
                basename = name.rsplit("/", 1)[-1]
                for pattern, reason in COMPILED:
                    if pattern.search(basename) or pattern.search(name):
                        leaks.append((archive_path.name, name, reason))
                        break
                else:
                    # Name is clean — now read what is actually in it.
                    for reason, sample in scan_entry_content(archive, info):
                        leaks.append((archive_path.name, name, f"{reason}: {sample!r}"))

    print()
    if leaks:
        print(f"FAIL — {len(leaks)} forbidden entr(ies) found:", file=sys.stderr)
        for archive_name, entry, reason in leaks:
            print(f"  {archive_name}: {entry}\n      reason: {reason}", file=sys.stderr)
        return 1

    print(f"PASS — {checked} entries checked across {len(archives)} bundle(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, help="directory containing the .zip bundles"
    )
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"error: not a directory: {args.directory}", file=sys.stderr)
        return 2
    return audit(args.directory)


if __name__ == "__main__":
    raise SystemExit(main())
