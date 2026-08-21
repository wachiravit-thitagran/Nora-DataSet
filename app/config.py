"""Runtime configuration, read entirely from environment variables.

Nothing here has a secret as its default: SECRET_KEY must be supplied or the
application refuses to start, so a misconfigured deployment fails loudly at
boot instead of silently issuing forgeable download tokens.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "See deploy/docker-compose.yml for the expected configuration."
        )
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc


class Settings:
    def __init__(self) -> None:
        # Secret used to sign download tokens. Rotating it invalidates every
        # outstanding token, which is the intended emergency lever.
        self.secret_key: str = _env("SECRET_KEY")
        if len(self.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 characters long.")

        # Where the packaged bundles live on disk. The application only ever
        # reads metadata here; nginx serves the bytes via X-Accel-Redirect.
        self.data_dir: Path = Path(_env("DATA_DIR", "/data")).resolve()

        # Catalogue files. Kept in the image (version-controlled) rather than
        # on the data volume, so a deploy always ships a consistent catalogue.
        self.catalog_dir: Path = Path(
            os.environ.get("CATALOG_DIR", str(PROJECT_ROOT / "data"))
        ).resolve()

        self.db_path: Path = Path(
            os.environ.get("DB_PATH", str(self.data_dir / "db" / "access.sqlite3"))
        )

        # Mounted under this prefix by the host nginx. FastAPI needs it to
        # build correct URLs; the frontend uses relative paths regardless.
        self.root_path: str = os.environ.get("ROOT_PATH", "").rstrip("/")

        # Off by default: nginx reserves exactly one path, /dataset/, and
        # everything behind it — including serving bundle bytes — is handled
        # here in the application.
        #
        # X-Accel-Redirect is still supported for deployments willing to
        # declare a second, internal nginx location. It is faster for large
        # files but requires nginx to have its own filesystem access to the
        # bundles. Leave it off unless you have set that up.
        self.use_xaccel: bool = _env_bool("USE_XACCEL", False)

        # Only used when use_xaccel is true. Absolute URI in nginx's address
        # space, matching the `internal` location that aliases DATA_DIR.
        self.xaccel_prefix: str = os.environ.get(
            "XACCEL_PREFIX", "/dataset/_dl"
        ).rstrip("/")

        self.token_ttl_seconds: int = _env_int("TOKEN_TTL_SECONDS", 24 * 3600)

        # Retention window for access records, enforced by a startup sweep.
        self.retention_days: int = _env_int("RETENTION_DAYS", 730)

        # Crude abuse brake: max access-request submissions per IP per hour.
        self.rate_limit_per_hour: int = _env_int("RATE_LIMIT_PER_HOUR", 10)

        self.trust_forwarded_for: bool = _env_bool("TRUST_FORWARDED_FOR", True)

    @property
    def manifest_path(self) -> Path:
        return self.catalog_dir / "manifest.json"

    @property
    def poses_path(self) -> Path:
        return self.catalog_dir / "poses.json"


settings = Settings()
