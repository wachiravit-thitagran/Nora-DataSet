#!/usr/bin/env bash
# Start the Nora Dataset site locally.
#
#   ./run.sh          serve the real catalogue (bundles show as unavailable
#                     until you have packaged them with build_bundles.py)
#   ./run.sh --demo   serve a copy of the catalogue with placeholder sizes and
#                     checksums, so every card is downloadable and the page can
#                     be shown end to end
#
# Everything it creates lives under .local/ and is git-ignored. Safe to rerun.

set -euo pipefail
cd "$(dirname "$0")"

DEMO=0
PORT=8099
for arg in "$@"; do
  case "$arg" in
    --demo) DEMO=1 ;;
    --port=*) PORT="${arg#*=}" ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

PY=""
for candidate in python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3 not found. On macOS: xcode-select --install, or install from python.org" >&2
  exit 1
fi

VENV=".local/venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "→ creating virtualenv in $VENV"
  "$PY" -m venv "$VENV"
fi
# Quiet unless something is actually missing, so a rerun starts almost instantly.
if ! "$VENV/bin/python" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "→ installing dependencies"
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -r requirements.txt
fi

# The signing key persists across runs so download links stay valid between
# restarts. It is local-only and never committed.
KEY_FILE=".local/secret_key"
if [ ! -f "$KEY_FILE" ]; then
  mkdir -p .local
  "$VENV/bin/python" -c "import secrets; print(secrets.token_hex(32))" > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
fi
export SECRET_KEY="$(cat "$KEY_FILE")"

export DB_PATH=".local/db/access.sqlite3"
export USE_XACCEL=false
export ROOT_PATH=""
mkdir -p .local/db

if [ "$DEMO" -eq 1 ]; then
  export CATALOG_DIR=".local/demo-catalog"
  export DATA_DIR=".local/demo-data"
  "$VENV/bin/python" - <<'PY'
import hashlib, json, os, pathlib, shutil
cat = pathlib.Path(os.environ["CATALOG_DIR"]); data = pathlib.Path(os.environ["DATA_DIR"])
cat.mkdir(parents=True, exist_ok=True)
manifest = json.loads(pathlib.Path("data/manifest.json").read_text(encoding="utf-8"))
shutil.copy("data/poses.json", cat / "poses.json")
version = manifest["dataset"]["version"]
out = data / version
out.mkdir(parents=True, exist_ok=True)
# Plausible stand-in figures, clearly not real: the point is to exercise the
# page, not to publish numbers anyone might quote.
sizes = {"pose-images": (48_234_496, 25),
         "generated-videos": (612_368_384, 19),
         "pose-positions": (4_718_592, 52)}
for bundle in manifest["bundles"]:
    size, count = sizes.get(bundle["id"], (1_048_576, 1))
    name = f"nora-{bundle['id']}-{version}.zip"
    (out / name).write_bytes(b"demo placeholder, not a real bundle\n")
    bundle.update(filename=name, bytes=size, file_count=count,
                  sha256=hashlib.sha256(name.encode()).hexdigest(),
                  available=True)
(cat / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("→ demo catalogue ready (placeholder sizes and checksums)")
PY
else
  # The bundles live in the repo now, so a plain run serves whatever has been
  # packaged and committed.
  export DATA_DIR="data/bundles"
  mkdir -p "data/bundles"
  packaged=$("$VENV/bin/python" -c "
import json
m = json.load(open('data/manifest.json', encoding='utf-8'))
print(sum(1 for b in m['bundles'] if b.get('filename')))")
  if [ "$packaged" = "0" ]; then
    echo "→ no bundles packaged yet, so every card will read 'ยังไม่เปิดให้ดาวน์โหลด'"
    echo "  run ./run.sh --demo to see the page with placeholder data instead"
  fi
fi

echo
echo "  Nora Dataset  →  http://127.0.0.1:${PORT}/"
echo "  stop with Ctrl-C"
echo
exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload
