"""Nora dataset distribution service.

Serves a bilingual catalogue page and gates bundle downloads behind a short
access form. The application never streams bundle bytes in production: it
validates the token and hands nginx an ``X-Accel-Redirect``, so a 500 MB
download costs one Python request and zero worker time.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

from . import db
from .auth import TokenError, issue_token, verify_token
from .config import settings

logger = logging.getLogger("nora.dataset")

# A bundle id is an internal slug; anything outside this alphabet cannot name
# a real bundle and is rejected before it reaches the filesystem.
BUNDLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

PURPOSES = {
    "research",
    "education",
    "cultural_preservation",
    "journalism",
    "personal",
    "commercial",
    "other",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    purged = db.purge_expired_requests()
    if purged:
        logger.info("retention sweep removed %d expired access requests", purged)
    yield


app = FastAPI(
    title="Nora Dataset",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    root_path=settings.root_path,
    lifespan=lifespan,
)


# --------------------------------------------------------------------------
# Catalogue loading
# --------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_manifest() -> dict[str, Any]:
    return _read_json(settings.manifest_path)


def load_poses() -> dict[str, Any]:
    return _read_json(settings.poses_path)


def bundle_path(manifest: dict[str, Any], bundle: dict[str, Any]) -> Path | None:
    """Absolute on-disk path of a bundle, or None if it is not published yet."""
    filename = bundle.get("filename")
    if not filename:
        return None
    # Reject anything that could escape the version directory. Bundle
    # filenames come from a file we control, but this is the last line of
    # defence before a path reaches the filesystem.
    if "/" in filename or "\\" in filename or filename.startswith("."):
        logger.error("refusing suspicious bundle filename: %r", filename)
        return None
    version = manifest.get("dataset", {}).get("version", "")
    return (settings.data_dir / version / filename).resolve()


def _client_ip(request: Request) -> str:
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the original client; the rest are proxies.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------


class AccessRequestIn(BaseModel):
    email: EmailStr
    purpose: Literal[
        "research",
        "education",
        "cultural_preservation",
        "journalism",
        "personal",
        "commercial",
        "other",
    ]
    purpose_detail: str | None = Field(default=None, max_length=1000)
    organization: str | None = Field(default=None, max_length=200)
    consent: bool
    consent_text: str = Field(min_length=1, max_length=4000)
    lang: Literal["th", "en"] = "th"

    @field_validator("consent")
    @classmethod
    def consent_must_be_given(cls, value: bool) -> bool:
        if not value:
            raise ValueError("consent is required")
        return value

    @field_validator("purpose_detail", "organization")
    @classmethod
    def strip_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AccessRequestOut(BaseModel):
    token: str
    expires_at: int


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/catalog")
def catalog() -> JSONResponse:
    """Everything the page needs to render, in one round-trip."""
    manifest = load_manifest()
    poses = load_poses()

    # Report availability from disk rather than trusting the manifest flag,
    # so a bundle that failed to upload shows as unavailable instead of
    # handing the visitor a download link that 404s.
    for bundle in manifest.get("bundles", []):
        path = bundle_path(manifest, bundle)
        bundle["available"] = bool(path and path.is_file())

    return JSONResponse({"manifest": manifest, "poses": poses})


@app.post("/api/access", response_model=AccessRequestOut)
def request_access(payload: AccessRequestIn, request: Request) -> AccessRequestOut:
    ip = _client_ip(request)

    recent = db.count_recent_requests_from_ip(ip)
    if recent >= settings.rate_limit_per_hour:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_requests",
        )

    if payload.purpose == "other" and not payload.purpose_detail:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="purpose_detail_required",
        )

    request_id = db.insert_access_request(
        email=str(payload.email).lower(),
        organization=payload.organization,
        purpose=payload.purpose,
        purpose_detail=payload.purpose_detail,
        # Store the exact wording the visitor agreed to. If the notice is
        # later reworded, the record still shows what was actually consented to.
        consent_text=payload.consent_text,
        ip=ip,
        user_agent=request.headers.get("user-agent", "")[:500] or None,
        lang=payload.lang,
    )

    token, expires_at = issue_token(request_id)
    return AccessRequestOut(token=token, expires_at=expires_at)


@app.get("/api/download/{bundle_id}")
def download(bundle_id: str, t: str = "") -> Response:
    if not BUNDLE_ID_RE.match(bundle_id):
        raise HTTPException(status_code=400, detail="invalid_bundle_id")

    try:
        claims = verify_token(t)
    except TokenError as exc:
        # 403 rather than 401: there is no login to retry, the visitor needs
        # to submit the form again.
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    manifest = load_manifest()
    bundle = next(
        (b for b in manifest.get("bundles", []) if b.get("id") == bundle_id), None
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="unknown_bundle")

    path = bundle_path(manifest, bundle)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="bundle_not_available")

    # Defence in depth: confirm the resolved path really is inside DATA_DIR.
    try:
        path.relative_to(settings.data_dir)
    except ValueError:
        logger.error("bundle path escaped DATA_DIR: %s", path)
        raise HTTPException(status_code=500, detail="misconfigured") from None

    version = manifest.get("dataset", {}).get("version", "")
    db.record_download(claims.get("rid"), bundle_id, version)

    filename = bundle["filename"]
    disposition = f'attachment; filename="{filename}"'

    if not settings.use_xaccel:
        # Local development path only: FastAPI streams the file itself.
        return FileResponse(
            path, filename=filename, media_type="application/octet-stream"
        )

    # Production path: nginx serves the bytes from the internal location.
    # The URL is percent-encoded because bundle names may contain non-ASCII.
    internal_url = f"{settings.xaccel_prefix}/{quote(version)}/{quote(filename)}"
    return Response(
        status_code=200,
        headers={
            "X-Accel-Redirect": internal_url,
            "Content-Disposition": disposition,
            "Content-Type": "application/octet-stream",
        },
    )


# --------------------------------------------------------------------------
# Static frontend — mounted last so it does not shadow the API routes.
# --------------------------------------------------------------------------

app.mount(
    "/",
    StaticFiles(directory=str(Path(__file__).parent / "static"), html=True),
    name="static",
)
