#!/bin/sh
# Prepare the database once, then hand over to the real command.
#
# uvicorn runs several workers, and every one of them opens the database and
# creates the schema at startup. On a fresh volume they do that simultaneously,
# which is how the first deploy died: switching a database into WAL takes an
# exclusive lock, so all but one worker got "database is locked" and the
# container flapped.
#
# db.py now tolerates that race on its own, but doing the work here — in one
# process, before any worker exists — means the race never happens and startup
# is deterministic. `exec` keeps the server as PID 1 so signals still reach it.

set -e

python3 - <<'PY'
from app import db
from app.config import settings

db.init_db()
print("database ready at", settings.db_path, flush=True)
PY

exec "$@"
