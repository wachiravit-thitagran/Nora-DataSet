"""Stateless download tokens.

A token is `<payload>.<signature>` where payload is base64url-encoded JSON.
Signing is HMAC-SHA256 with SECRET_KEY, compared in constant time. Tokens are
deliberately stateless: verifying one costs no database round-trip, and
rotating SECRET_KEY revokes every outstanding token at once.
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from hashlib import sha256
from typing import Any

from .config import settings


class TokenError(Exception):
    """Raised when a token is malformed, forged, or expired."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload: bytes) -> str:
    digest = hmac.new(settings.secret_key.encode("utf-8"), payload, sha256).digest()
    return _b64encode(digest)


def issue_token(request_id: int, ttl_seconds: int | None = None) -> tuple[str, int]:
    """Return ``(token, expires_at_epoch)`` for an approved access request."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.token_ttl_seconds
    expires_at = int(time.time()) + ttl
    payload = json.dumps(
        {"rid": request_id, "exp": expires_at},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = _b64encode(payload)
    return f"{encoded}.{_sign(payload)}", expires_at


def verify_token(token: str) -> dict[str, Any]:
    """Return the token payload, or raise :class:`TokenError`."""
    if not token or token.count(".") != 1:
        raise TokenError("malformed")

    encoded, signature = token.split(".", 1)
    try:
        payload = _b64decode(encoded)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise TokenError("malformed") from exc

    # Constant-time comparison: a naive `==` would leak signature bytes
    # through timing and let an attacker forge a token byte by byte.
    if not hmac.compare_digest(_sign(payload), signature):
        raise TokenError("bad_signature")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TokenError("malformed") from exc

    if not isinstance(data, dict) or "exp" not in data or "rid" not in data:
        raise TokenError("malformed")

    if int(data["exp"]) < int(time.time()):
        raise TokenError("expired")

    return data
