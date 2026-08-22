#!/usr/bin/env python3
"""Validate the catalogue files before they ship.

Runs in CI. A broken manifest does not crash the service — it renders an empty
or half-translated page, which is worse because nobody notices. These checks
turn that into a build failure.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATIC_DIR = PROJECT_ROOT / "app" / "static"

LANGS = ("th", "en")
BUNDLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

errors: list[str] = []
warnings: list[str] = []


def error(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def load(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        error(f"missing file: {path.relative_to(PROJECT_ROOT)}")
    except json.JSONDecodeError as exc:
        error(f"invalid JSON in {path.relative_to(PROJECT_ROOT)}: {exc}")
    return {}


def check_bilingual(value: object, label: str) -> None:
    if not isinstance(value, dict):
        error(f"{label}: expected an object with 'th' and 'en' keys")
        return
    for lang in LANGS:
        text = value.get(lang)
        if not isinstance(text, str) or not text.strip():
            error(f"{label}: missing or empty '{lang}' text")


def check_manifest(manifest: dict) -> None:
    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict):
        error("manifest.dataset is missing")
        return

    for key in ("title", "summary", "description", "disclaimer"):
        check_bilingual(dataset.get(key), f"manifest.dataset.{key}")

    if not dataset.get("version"):
        error("manifest.dataset.version is empty")

    licence = dataset.get("license", {})
    check_bilingual(licence.get("name"), "manifest.dataset.license.name")
    if licence.get("status") == "pending":
        warn(
            "licence is still 'pending' — the site must not be opened to the "
            "public until this is resolved"
        )

    seen_ids: set[str] = set()
    bundles = manifest.get("bundles", [])
    if not bundles:
        error("manifest has no bundles")

    for index, bundle in enumerate(bundles):
        label = f"manifest.bundles[{index}]"
        bundle_id = bundle.get("id", "")
        if not BUNDLE_ID_RE.match(bundle_id):
            error(f"{label}.id is missing or not a valid slug: {bundle_id!r}")
        if bundle_id in seen_ids:
            error(f"{label}.id is duplicated: {bundle_id}")
        seen_ids.add(bundle_id)

        check_bilingual(bundle.get("title"), f"{label}.title")
        check_bilingual(bundle.get("description"), f"{label}.description")

        filename = bundle.get("filename")
        if filename:
            if "/" in filename or "\\" in filename or filename.startswith("."):
                error(f"{label}.filename is unsafe: {filename!r}")
            checksum = bundle.get("sha256")
            if not checksum or not SHA256_RE.match(str(checksum)):
                error(f"{label} has a filename but no valid sha256")
            if not isinstance(bundle.get("bytes"), int):
                error(f"{label} has a filename but no byte count")
        else:
            warn(f"{label} ({bundle_id}) has not been packaged yet")


def check_poses(poses: dict) -> None:
    entries = poses.get("poses", [])
    if not entries:
        error("poses.json contains no poses")
        return

    seen: set[str] = set()
    valid_match = {"verified", "mismatch", "partial", "not_applicable"}

    for index, pose in enumerate(entries):
        label = f"poses[{index}]"
        pose_id = pose.get("id", "")
        if not pose_id:
            error(f"{label}.id is missing")
        if pose_id in seen:
            error(f"{label}.id is duplicated: {pose_id}")
        seen.add(pose_id)

        for key in ("name_th", "name_en", "description_th", "description_en"):
            if not str(pose.get(key, "")).strip():
                error(f"{label} ({pose_id}): {key} is empty")

        match = pose.get("identity_match")
        if match not in valid_match:
            error(f"{label} ({pose_id}): identity_match {match!r} is not recognised")

    unresolved = poses.get("unmapped", [])
    if unresolved:
        warn(
            f"{len(unresolved)} pose pair(s) still unmapped — these are excluded "
            "from published bundles until reviewed"
        )


def check_i18n() -> None:
    strings = load(STATIC_DIR / "i18n.json")
    if not strings:
        return

    keys = {lang: set(strings.get(lang, {})) for lang in LANGS}
    missing_en = keys["th"] - keys["en"]
    missing_th = keys["en"] - keys["th"]
    for key in sorted(missing_en):
        error(f"i18n: key '{key}' exists in th but not en")
    for key in sorted(missing_th):
        error(f"i18n: key '{key}' exists in en but not th")

    # Every data-i18n attribute in the page must resolve, or the visitor sees
    # a raw key where a sentence should be.
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n="([^"]+)"', html))
    for key in sorted(used - keys["th"]):
        error(f"i18n: index.html uses '{key}' but it is not defined")


def check_stylesheet() -> None:
    """The stylesheet is compiled from app/styles/app.css and committed.

    Nothing at runtime rebuilds it, so an edit to the source that is not
    followed by `npm run css` ships the previous design silently. Comparing
    mtimes catches that in CI, where both files come out of the same checkout.
    """
    source = PROJECT_ROOT / "app" / "styles" / "app.css"
    built = PROJECT_ROOT / "app" / "static" / "style.css"
    if not source.exists() or not built.exists():
        return
    if source.stat().st_mtime > built.stat().st_mtime:
        warn(
            "app/styles/app.css is newer than app/static/style.css — "
            "run `npm run css` and commit the result"
        )


def main() -> int:
    manifest = load(DATA_DIR / "manifest.json")
    poses = load(DATA_DIR / "poses.json")

    if manifest:
        check_manifest(manifest)
    if poses:
        check_poses(poses)
    check_i18n()
    check_stylesheet()

    for message in warnings:
        print(f"warning: {message}")
    for message in errors:
        print(f"error: {message}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)", file=sys.stderr)
        return 1

    print(f"\ncatalogue OK ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
