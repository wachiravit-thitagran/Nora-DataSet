#!/usr/bin/env python3
"""Package the Nora dataset into distributable zip bundles.

Whitelist-driven: a file reaches a bundle only if `bundles.config.json` names
it or names a directory plus an include pattern that matches it. The source
folder also holds procurement documents, invoices, and third-party video, so
an allow-list is the only safe default here.

The script writes each bundle to `output_root/<version>/`, computes a SHA-256
for every one, and updates `data/manifest.json` in place so the website picks
up the new sizes and checksums without any code change.

Usage
-----
    python3 scripts/build_bundles.py                # build everything
    python3 scripts/build_bundles.py --only keypoints
    python3 scripts/build_bundles.py --dry-run      # list what would go in
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
CONFIG_PATH = HERE / "bundles.config.json"
CATALOG_DIR = PROJECT_ROOT / "data"
MANIFEST_PATH = CATALOG_DIR / "manifest.json"

# Facebook CDN filenames look like 153409864_2873380766280908_5518422278461896439_n.
# The pipeline used them as pose_id values, so the identifiers are embedded in
# the metadata files as *content* — dropping the orig_*.json keypoint files was
# never enough on its own.
FACEBOOK_ID_RE = re.compile(r"\d{9,}_\d{9,}")


@dataclass
class PlannedFile:
    source: Path
    arcname: str
    record_filter: str | None = None


@dataclass
class BundlePlan:
    bundle_id: str
    filename: str
    files: list[PlannedFile] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# Fields that say *which image a record is*, as opposed to fields that merely
# mention another record. A Facebook ID in one of these means the record itself
# is that photo; a Facebook ID anywhere else is a cross-reference to a record
# that is being dropped, and only that reference needs to go.
IDENTITY_KEYS = ("pose_id", "file", "source_image", "control_map", "overlay")

# Groups whose source images are listed under `_not_published`: the hand
# gesture photographs (จีบ / วง / ตั้งวง / ล่อแก้ว) and the costume reference
# shots. The images were never in the release; their extracted coordinates
# should not be either.
OUT_OF_SCOPE_GROUPS = ("hand", "costume")


def _is_facebook_record(record) -> bool:
    if not isinstance(record, dict):
        return bool(FACEBOOK_ID_RE.search(str(record)))
    return any(
        isinstance(record.get(key), str) and FACEBOOK_ID_RE.search(record[key])
        for key in IDENTITY_KEYS
    )


def _is_out_of_scope_record(record) -> bool:
    if _is_facebook_record(record):
        return True
    group = record.get("group") if isinstance(record, dict) else None
    return isinstance(group, str) and group.strip().lower() in OUT_OF_SCOPE_GROUPS


def _scrub_references(value, dropped_ids: set[str]):
    """Remove references to dropped records. Returns (value, count).

    `pose_library.json` entries point at their neighbours through fields like
    `transition_to`, so a record that is itself fine can still name one that
    was dropped. Those references are removed rather than taken as grounds to
    drop the record as well.
    """

    def is_dangling(text: str) -> bool:
        return bool(FACEBOOK_ID_RE.search(text)) or text in dropped_ids

    if isinstance(value, str):
        return (None, 1) if is_dangling(value) else (value, 0)

    if isinstance(value, list):
        out, removed = [], 0
        for item in value:
            if isinstance(item, str) and is_dangling(item):
                removed += 1
                continue
            cleaned, n = _scrub_references(item, dropped_ids)
            out.append(cleaned)
            removed += n
        return out, removed

    if isinstance(value, dict):
        out, removed = {}, 0
        for key, item in value.items():
            cleaned, n = _scrub_references(item, dropped_ids)
            out[key] = cleaned
            removed += n
        return out, removed

    return value, 0


def _record_id(record: dict) -> str | None:
    value = record.get("pose_id")
    return value if isinstance(value, str) else None


def filter_records(path: Path, should_drop) -> tuple[bytes, int]:
    """Rewrite *path* without the records *should_drop* selects.

    `pose_library.json`, `manifest.json` and `manifest.csv` hold one record per
    source image. Two things have to come out of them: images sourced from
    Facebook, which carry the photo ID as their identifier, and the hand and
    costume references that `_not_published` keeps out of the release. Removing
    the matching keypoint files does not touch these three, which is why they
    are rewritten here.

    Returns the rewritten bytes and the number of records dropped. References
    to dropped records are scrubbed from the survivors and reported separately,
    since they are edits rather than deletions.
    """
    suffix = path.suffix.lower()

    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(
                f"{path.name}: expected a list of records, got {type(data).__name__}"
            )
        kept, dropped_ids = [], set()
        for record in data:
            if should_drop(record):
                identifier = _record_id(record) if isinstance(record, dict) else None
                if identifier:
                    dropped_ids.add(identifier)
            else:
                kept.append(record)

        scrubbed, references = _scrub_references(kept, dropped_ids)
        if references:
            print(f"    scrubbed {path.name}: {references} dangling reference(s)")
        text = json.dumps(scrubbed, ensure_ascii=False, indent=2) + "\n"
        return text.encode("utf-8"), len(data) - len(kept)

    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        kept = [row for row in rows if not should_drop(row)]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(kept)
        return buffer.getvalue().encode("utf-8"), len(rows) - len(kept)

    raise ValueError(f"{path.name}: no record filter for {suffix or 'this file type'}")


def drop_facebook_ids(path: Path) -> tuple[bytes, int]:
    """Drop only the records identified by a Facebook photo ID."""
    return filter_records(path, _is_facebook_record)


def drop_out_of_scope(path: Path) -> tuple[bytes, int]:
    """Drop Facebook-sourced records and the hand and costume references."""
    return filter_records(path, _is_out_of_scope_record)


RECORD_FILTERS = {
    "drop_facebook_ids": drop_facebook_ids,
    "drop_out_of_scope": drop_out_of_scope,
}


def matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def iter_directory(
    root: Path,
    include: list[str],
    exclude: list[str],
    global_exclude: list[str],
    recursive: bool,
):
    """Yield files under *root* that pass the include/exclude filters."""
    walker = root.rglob("*") if recursive else root.glob("*")
    for path in sorted(walker):
        if not path.is_file():
            continue
        name = path.name
        if matches_any(name, global_exclude):
            continue
        if exclude and matches_any(name, exclude):
            continue
        # An empty include list means "every file that survived the excludes".
        if include and not matches_any(name, include):
            continue
        yield path


def plan_bundle(
    bundle: dict,
    source_root: Path,
    global_exclude: list[str],
    version: str,
) -> BundlePlan:
    plan = BundlePlan(
        bundle_id=bundle["id"],
        filename=bundle["filename"].replace("{version}", version),
    )
    seen: set[str] = set()

    def add(source: Path, arcname: str, record_filter: str | None = None) -> None:
        if arcname in seen:
            plan.skipped.append(f"duplicate arcname skipped: {arcname}")
            return
        seen.add(arcname)
        plan.files.append(
            PlannedFile(source=source, arcname=arcname, record_filter=record_filter)
        )

    for item in bundle.get("items", []):
        src = (source_root / item["src"]).resolve()
        dest = item["dest"].strip("/")
        record_filter = item.get("record_filter")
        if record_filter and record_filter not in RECORD_FILTERS:
            raise SystemExit(f"unknown record_filter: {record_filter}")

        if not src.exists():
            plan.skipped.append(f"missing source: {item['src']}")
            continue

        if src.is_file():
            add(src, dest, record_filter)
            continue

        include = item.get("include", [])
        exclude = item.get("exclude", [])
        recursive = item.get("recursive", True)
        found = 0
        for path in iter_directory(src, include, exclude, global_exclude, recursive):
            relative = path.relative_to(src).as_posix()
            add(path, f"{dest}/{relative}" if dest else relative, record_filter)
            found += 1
        if found == 0:
            plan.skipped.append(f"no files matched in: {item['src']}")

    for item in bundle.get("catalog_files", []):
        src = (CATALOG_DIR / item["src"]).resolve()
        if src.is_file():
            add(src, item["dest"].strip("/"))
        else:
            plan.skipped.append(f"missing catalog file: {item['src']}")

    return plan


def bundle_readme(manifest: dict, bundle_id: str, plan: BundlePlan) -> str:
    dataset = manifest["dataset"]
    bundle = next(b for b in manifest["bundles"] if b["id"] == bundle_id)
    licence = dataset.get("license", {})
    lines = [
        f"# {dataset['title']['th']} — {bundle['title']['th']}",
        f"# {dataset['title']['en']} — {bundle['title']['en']}",
        "",
        f"Version : {dataset.get('version')}",
        f"Bundle  : {bundle_id}",
        f"Files   : {len(plan.files)}",
        f"Built   : {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "## License",
        "",
        licence.get("name", {}).get("en", "TBD"),
        licence.get("url") or "",
        "",
        (licence.get("note") or {}).get("th", ""),
        (licence.get("note") or {}).get("en", ""),
        "",
        "## Important notice / ข้อควรทราบ",
        "",
        (dataset.get("disclaimer") or {}).get("th", ""),
        "",
        (dataset.get("disclaimer") or {}).get("en", ""),
        "",
        "## Citation / การอ้างอิง",
        "",
        (dataset.get("citation") or {}).get("text", "TBD"),
        "",
    ]
    return "\n".join(lines)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bundle(plan: BundlePlan, out_dir: Path, manifest: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / plan.filename
    temporary = target.with_suffix(target.suffix + ".part")

    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        archive.writestr("README.txt", bundle_readme(manifest, plan.bundle_id, plan))
        for entry in plan.files:
            if entry.record_filter:
                payload, dropped = RECORD_FILTERS[entry.record_filter](entry.source)
                archive.writestr(entry.arcname, payload)
                print(f"    filtered {entry.arcname}: {dropped} record(s) dropped")
            else:
                archive.write(entry.source, arcname=entry.arcname)

    # Rename only once the archive is complete, so an interrupted build never
    # leaves a truncated file where nginx would happily serve it.
    temporary.replace(target)
    return target


def update_manifest(manifest: dict, results: dict[str, dict]) -> None:
    for bundle in manifest.get("bundles", []):
        result = results.get(bundle["id"])
        if not result:
            continue
        bundle["filename"] = result["filename"]
        bundle["bytes"] = result["bytes"]
        bundle["sha256"] = result["sha256"]
        bundle["file_count"] = result["file_count"]
        bundle["updated_at"] = result["updated_at"]
        bundle["available"] = True

    with MANIFEST_PATH.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--only", action="append", help="build only these bundle ids")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()

    config = load_json(args.config)
    manifest = load_json(MANIFEST_PATH)

    source_root = (
        args.source_root
        if args.source_root
        else Path(config["source_root"]).expanduser()
    ).resolve()

    if not source_root.is_dir():
        print(f"error: source root not found: {source_root}", file=sys.stderr)
        return 2

    version = manifest["dataset"].get("version") or config["version"]
    output_root = (
        args.output_root if args.output_root else PROJECT_ROOT / config["output_root"]
    ).resolve()
    out_dir = output_root / version

    global_exclude = config.get("global_exclude", [])
    wanted = set(args.only) if args.only else None

    results: dict[str, dict] = {}
    exit_code = 0

    for bundle in config["bundles"]:
        if wanted and bundle["id"] not in wanted:
            continue

        # A bundle held back on purpose stays held back through a plain
        # `build_bundles.py`. Packaging it is what makes it downloadable, so
        # the decision not to publish has to live here rather than in a note
        # someone has to remember. Name it with --only to build it anyway.
        if bundle.get("publish") is False and not wanted:
            print(f"\n=== {bundle['id']} ===")
            print(f"    held back: {bundle.get('hold_reason', 'publish is false')}")
            print("    (build it anyway with --only " + bundle["id"] + ")")
            continue

        plan = plan_bundle(bundle, source_root, global_exclude, version)

        print(f"\n=== {plan.bundle_id} ===")
        print(f"    files   : {len(plan.files)}")
        total = sum(f.source.stat().st_size for f in plan.files)
        print(f"    raw size: {total / 1024 / 1024:.1f} MB")
        for note in plan.skipped:
            print(f"    ! {note}")
            exit_code = max(exit_code, 1)

        if args.dry_run:
            for entry in plan.files[:20]:
                print(f"      {entry.arcname}")
            if len(plan.files) > 20:
                print(f"      … and {len(plan.files) - 20} more")
            continue

        if not plan.files:
            print("    nothing to package, skipping")
            continue

        target = write_bundle(plan, out_dir, manifest)
        size = target.stat().st_size
        checksum = sha256_of(target)
        print(f"    -> {target.name}  {size / 1024 / 1024:.1f} MB")
        print(f"       sha256 {checksum}")

        results[plan.bundle_id] = {
            "filename": target.name,
            "bytes": size,
            "sha256": checksum,
            "file_count": len(plan.files),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    if results and not args.dry_run:
        update_manifest(manifest, results)
        print(f"\nmanifest updated: {MANIFEST_PATH}")
        print(f"bundles written to: {out_dir}")
        print("\nNext: copy this directory to the server's DATA_DIR, e.g.")
        print(
            f"  rsync -av --progress {out_dir}/ ainora-agent:/srv/ainora/dataset/{version}/"
        )

    if args.dry_run:
        print("\n(dry run — nothing written)")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
