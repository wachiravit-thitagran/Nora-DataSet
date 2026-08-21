#!/usr/bin/env python3
"""Operator tool for PDPA obligations against the access-request database.

Every right the privacy notice promises needs a way to actually exercise it,
otherwise the notice is a claim the system cannot honour. This script provides
those levers from the command line.

    python3 scripts/pdpa_tool.py export  --db /srv/ainora/dataset/db/access.sqlite3 -o report.csv
    python3 scripts/pdpa_tool.py subject --db ... --email someone@example.com
    python3 scripts/pdpa_tool.py erase   --db ... --email someone@example.com
    python3 scripts/pdpa_tool.py purge   --db ... --days 730
    python3 scripts/pdpa_tool.py stats   --db ...
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        raise SystemExit(2)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_export(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    rows = conn.execute(
        "SELECT id, email, organization, purpose, purpose_detail, lang, created_at "
        "FROM access_request ORDER BY created_at DESC"
    ).fetchall()

    out = (
        open(args.output, "w", newline="", encoding="utf-8-sig")
        if args.output
        else sys.stdout
    )
    try:
        writer = csv.writer(out)
        writer.writerow(
            [
                "id",
                "email",
                "organization",
                "purpose",
                "purpose_detail",
                "lang",
                "created_at",
            ]
        )
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])
    finally:
        if args.output:
            out.close()
            print(f"wrote {len(rows)} rows to {args.output}")
    return 0


def cmd_subject(args: argparse.Namespace) -> int:
    """Data subject access request: everything held about one email."""
    conn = connect(args.db)
    email = args.email.strip().lower()
    requests = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM access_request WHERE email = ? ORDER BY created_at", (email,)
        )
    ]
    ids = [r["id"] for r in requests]
    downloads = []
    if ids:
        placeholders = ",".join("?" * len(ids))
        downloads = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM download_event WHERE request_id IN ({placeholders})",
                ids,
            )
        ]

    report = {"email": email, "access_requests": requests, "downloads": downloads}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote subject report to {args.output}")
    else:
        print(text)
    return 0


def cmd_erase(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    email = args.email.strip().lower()
    count = conn.execute(
        "SELECT COUNT(*) FROM access_request WHERE email = ?", (email,)
    ).fetchone()[0]

    if count == 0:
        print(f"no records found for {email}")
        return 0

    if not args.yes:
        answer = input(f"Delete {count} record(s) for {email}? [y/N] ").strip().lower()
        if answer != "y":
            print("aborted")
            return 1

    # Detach download events before deleting, so aggregate statistics survive
    # while the identifying record does not.
    conn.execute(
        "UPDATE download_event SET request_id = NULL WHERE request_id IN "
        "(SELECT id FROM access_request WHERE email = ?)",
        (email,),
    )
    conn.execute("DELETE FROM access_request WHERE email = ?", (email,))
    conn.commit()
    print(f"erased {count} record(s) for {email}")
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat(
        timespec="seconds"
    )
    count = conn.execute(
        "SELECT COUNT(*) FROM access_request WHERE created_at < ?", (cutoff,)
    ).fetchone()[0]
    conn.execute(
        "UPDATE download_event SET request_id = NULL WHERE request_id IN "
        "(SELECT id FROM access_request WHERE created_at < ?)",
        (cutoff,),
    )
    conn.execute("DELETE FROM access_request WHERE created_at < ?", (cutoff,))
    conn.commit()
    print(f"purged {count} record(s) older than {args.days} days (before {cutoff})")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    total = conn.execute("SELECT COUNT(*) FROM access_request").fetchone()[0]
    print(f"access requests: {total}")

    print("\nby purpose:")
    for row in conn.execute(
        "SELECT purpose, COUNT(*) AS n FROM access_request GROUP BY purpose ORDER BY n DESC"
    ):
        print(f"  {row['purpose']:<24} {row['n']}")

    print("\ndownloads by bundle:")
    for row in conn.execute(
        "SELECT bundle_id, COUNT(*) AS n FROM download_event GROUP BY bundle_id ORDER BY n DESC"
    ):
        print(f"  {row['bundle_id']:<24} {row['n']}")

    oldest = conn.execute("SELECT MIN(created_at) FROM access_request").fetchone()[0]
    if oldest:
        print(f"\noldest record: {oldest}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="path to access.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="export all access requests to CSV")
    p_export.add_argument("-o", "--output")
    p_export.set_defaults(func=cmd_export)

    p_subject = sub.add_parser("subject", help="data subject access request")
    p_subject.add_argument("--email", required=True)
    p_subject.add_argument("-o", "--output")
    p_subject.set_defaults(func=cmd_subject)

    p_erase = sub.add_parser("erase", help="erase all records for one email")
    p_erase.add_argument("--email", required=True)
    p_erase.add_argument("--yes", action="store_true", help="skip confirmation")
    p_erase.set_defaults(func=cmd_erase)

    p_purge = sub.add_parser("purge", help="delete records past the retention window")
    p_purge.add_argument("--days", type=int, default=730)
    p_purge.set_defaults(func=cmd_purge)

    p_stats = sub.add_parser("stats", help="summary counts")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
