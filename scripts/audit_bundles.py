#!/usr/bin/env python3
"""Audit built bundles for files that must never be published.

`build_bundles.py` uses a whitelist, so in principle nothing unwanted can get
in. This script assumes that principle will eventually be violated — by a
config edit, a renamed folder, a well-meant "just add this one directory" —
and checks the finished archives independently.

Run it before every release, and in CI on any commit that touches
`bundles.config.json`.

    python3 scripts/audit_bundles.py dist/0.1.0-draft
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
    (r"id_rsa", "private key"),
    (r"\.pem$", "private key or certificate"),
]

COMPILED = [(re.compile(pattern), reason) for pattern, reason in FORBIDDEN]


def audit(directory: Path) -> int:
    archives = sorted(directory.glob("*.zip"))
    if not archives:
        print(f"error: no .zip files found in {directory}", file=sys.stderr)
        return 2

    leaks: list[tuple[str, str, str]] = []
    checked = 0

    for archive_path in archives:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
        checked += len(names)
        print(f"{archive_path.name}: {len(names)} entries")

        for name in names:
            basename = name.rsplit("/", 1)[-1]
            for pattern, reason in COMPILED:
                if pattern.search(basename) or pattern.search(name):
                    leaks.append((archive_path.name, name, reason))
                    break

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
