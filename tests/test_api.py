"""Tests for the access gate.

The point of these is narrow and important: prove that a bundle cannot be
downloaded without a valid, unexpired, correctly-signed token, and that the
production path hands the file to nginx instead of streaming it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "x" * 48)


@pytest.fixture()
def client(request, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A fresh app instance with its own data dir and database per test."""
    data_dir = tmp_path / "data"
    catalog_dir = tmp_path / "catalog"
    (data_dir / "1.0.0").mkdir(parents=True)
    catalog_dir.mkdir()

    bundle_file = data_dir / "1.0.0" / "test-bundle.zip"
    bundle_file.write_bytes(b"PK\x03\x04 pretend archive")

    manifest = {
        "schema_version": "1.0",
        "dataset": {
            "id": "test",
            "version": "1.0.0",
            "title": {"th": "ทดสอบ", "en": "Test"},
            "summary": {"th": "ก", "en": "a"},
            "description": {"th": "ข", "en": "b"},
            "disclaimer": {"th": "ค", "en": "c"},
            "license": {"id": "TBD", "name": {"th": "รอ", "en": "TBD"}},
            "citation": {"text": "TBD"},
            "contact": {},
            "credits": [],
        },
        "bundles": [
            {
                "id": "keypoints",
                "title": {"th": "จุด", "en": "Keypoints"},
                "description": {"th": "ง", "en": "d"},
                "filename": "test-bundle.zip",
                "bytes": bundle_file.stat().st_size,
                "sha256": "0" * 64,
                "file_count": 1,
                "available": True,
            },
            {
                "id": "not-built",
                "title": {"th": "ยัง", "en": "Pending"},
                "description": {"th": "จ", "en": "e"},
                "filename": None,
                "available": False,
            },
        ],
        "poses_file": "poses.json",
    }
    (catalog_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (catalog_dir / "poses.json").write_text(
        json.dumps({"poses": [], "unmapped": []}), encoding="utf-8"
    )

    monkeypatch.setenv("SECRET_KEY", "k" * 48)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("CATALOG_DIR", str(catalog_dir))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db" / "access.sqlite3"))
    # Default deployment: nginx reserves only /dataset/ and proxies everything
    # to this process, which serves the bundle bytes itself. Tests that need
    # the opt-in X-Accel-Redirect mode parametrize this fixture with "true".
    monkeypatch.setenv("USE_XACCEL", getattr(request, "param", "false"))
    monkeypatch.setenv("XACCEL_PREFIX", "/dataset/_dl")
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "5")

    # Force a genuine re-execution of the package so module-level Settings
    # picks up the patched environment. Popping only the submodules is not
    # enough: `from . import db` would still resolve through the surviving
    # attribute on the parent package and hand back the previous test's
    # module, complete with its database connection.
    import sys

    for name in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        sys.modules.pop(name, None)

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as test_client:
        yield test_client


VALID_FORM = {
    "email": "someone@example.org",
    "purpose": "research",
    "purpose_detail": "Studying pose transitions.",
    "organization": "Example University",
    "consent": True,
    "consent_text": "I consent to the privacy notice dated 2026-01-01.",
    "lang": "en",
}


def grant(client) -> str:
    response = client.post("/api/access", json=VALID_FORM)
    assert response.status_code == 200, response.text
    return response.json()["token"]


# --------------------------------------------------------------------- catalog


def test_catalog_reports_disk_truth(client):
    body = client.get("/api/catalog").json()
    bundles = {b["id"]: b for b in body["manifest"]["bundles"]}
    assert bundles["keypoints"]["available"] is True
    assert bundles["not-built"]["available"] is False


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


# ---------------------------------------------------------------------- access


def test_access_requires_consent(client):
    payload = dict(VALID_FORM, consent=False)
    assert client.post("/api/access", json=payload).status_code == 422


def test_access_rejects_bad_email(client):
    payload = dict(VALID_FORM, email="not-an-email")
    assert client.post("/api/access", json=payload).status_code == 422


def test_access_requires_detail_when_purpose_is_other(client):
    payload = dict(VALID_FORM, purpose="other", purpose_detail=None)
    response = client.post("/api/access", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "purpose_detail_required"


def test_access_rate_limited(client):
    for _ in range(5):
        assert client.post("/api/access", json=VALID_FORM).status_code == 200
    assert client.post("/api/access", json=VALID_FORM).status_code == 429


def test_consent_wording_is_stored(client, tmp_path):
    grant(client)
    import sqlite3

    from app.config import settings

    conn = sqlite3.connect(settings.db_path)
    stored = conn.execute("SELECT consent_text, email FROM access_request").fetchone()
    assert stored[0] == VALID_FORM["consent_text"]
    assert stored[1] == "someone@example.org"


# -------------------------------------------------------------------- download


def test_download_without_token_is_refused(client):
    assert client.get("/api/download/keypoints").status_code == 403


def test_download_with_forged_token_is_refused(client):
    assert client.get("/api/download/keypoints?t=abc.def").status_code == 403


def test_download_with_tampered_payload_is_refused(client):
    token = grant(client)
    payload, signature = token.split(".")
    # Flip a character in the payload; the signature no longer matches.
    tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    assert (
        client.get(f"/api/download/keypoints?t={tampered}.{signature}").status_code
        == 403
    )


def test_download_with_expired_token_is_refused(client):
    from app import auth

    # A negative TTL produces a correctly-signed token that is already stale,
    # which is exactly the case the expiry check must catch.
    token, expires_at = auth.issue_token(1, ttl_seconds=-60)
    assert expires_at < time.time()
    assert client.get(f"/api/download/keypoints?t={token}").status_code == 403


def test_download_streams_the_file(client):
    """Default mode: nginx proxies /dataset/ and this process sends the bytes."""
    token = grant(client)
    response = client.get(f"/api/download/keypoints?t={token}", follow_redirects=False)
    assert response.status_code == 200
    assert response.content == b"PK\x03\x04 pretend archive"
    assert "x-accel-redirect" not in response.headers
    assert "test-bundle.zip" in response.headers["content-disposition"]


@pytest.mark.parametrize("client", ["true"], indirect=True)
def test_download_returns_xaccel_redirect_when_enabled(client):
    """Opt-in mode, for deployments that add a second internal nginx location."""
    token = grant(client)
    response = client.get(f"/api/download/keypoints?t={token}", follow_redirects=False)
    assert response.status_code == 200
    # Absolute URI in nginx's address space, so it carries the /dataset prefix
    # even though the app itself is mounted at /.
    assert response.headers["x-accel-redirect"] == "/dataset/_dl/1.0.0/test-bundle.zip"
    assert response.content == b""


def test_download_of_unbuilt_bundle_is_404(client):
    token = grant(client)
    assert client.get(f"/api/download/not-built?t={token}").status_code == 404


def test_download_of_unknown_bundle_is_404(client):
    token = grant(client)
    assert client.get(f"/api/download/nonexistent?t={token}").status_code == 404


def test_path_traversal_bundle_id_is_rejected(client):
    token = grant(client)
    response = client.get(f"/api/download/..%2F..%2Fetc%2Fpasswd?t={token}")
    assert response.status_code in (400, 404)


def test_download_is_recorded(client):
    token = grant(client)
    client.get(f"/api/download/keypoints?t={token}")

    import sqlite3

    from app.config import settings

    conn = sqlite3.connect(settings.db_path)
    rows = conn.execute("SELECT bundle_id, version FROM download_event").fetchall()
    assert rows == [("keypoints", "1.0.0")]
