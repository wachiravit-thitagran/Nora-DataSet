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
import fnmatch
import hashlib
import json
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


@dataclass
class PlannedFile:
    source: Path
    arcname: str


@dataclass
class BundlePlan:
    bundle_id: str
    filename: str
    files: list[PlannedFile] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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

    def add(source: Path, arcname: str) -> None:
        if arcname in seen:
            plan.skipped.append(f"duplicate arcname skipped: {arcname}")
            return
        seen.add(arcname)
        plan.files.append(PlannedFile(source=source, arcname=arcname))

    for item in bundle.get("items", []):
        src = (source_root / item["src"]).resolve()
        dest = item["dest"].strip("/")

        if not src.exists():
            plan.skipped.append(f"missing source: {item['src']}")
            continue

        if src.is_file():
            add(src, dest)
            continue

        include = item.get("include", [])
        exclude = item.get("exclude", [])
        recursive = item.get("recursive", True)
        found = 0
        for path in iter_directory(src, include, exclude, global_exclude, recursive):
            relative = path.relative_to(src).as_posix()
            add(path, f"{dest}/{relative}" if dest else relative)
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
        "## Licence / สัญญาอนุญาต",
        "",
        f"{licence.get('name', {}).get('th', 'TBD')} / {licence.get('name', {}).get('en', 'TBD')}",
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
