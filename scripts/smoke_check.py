#!/usr/bin/env python3
"""Verify a running instance from the inside.

Run this *in the container*, not on the host:

    docker exec ainora-dataset-web python3 scripts/smoke_check.py

Everything it checks is reached over the container's own loopback, so it works
regardless of how the deploy host publishes the port — a Jenkins agent that
cannot reach the host's 127.0.0.1 (because it is itself a container) can still
run it. SECRET_KEY comes from the container environment, so the download check
uses a real signed token without submitting the access form, which would write
a fake person into the PDPA-governed table on every deploy.

Exit status is 0 only if every check passes.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
TIMEOUT = 10


class CheckFailed(Exception):
    pass


def request(path: str) -> tuple[int, bytes]:
    """Return (status, body). A 4xx/5xx is a result here, not an exception."""
    try:
        with urllib.request.urlopen(BASE + path, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise CheckFailed(f"cannot reach {path}: {exc.reason}") from exc


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
        return
    print(f"  FAIL  {label}{' — ' + detail if detail else ''}")
    raise CheckFailed(label)


def main() -> int:
    print("smoke check (inside the container)")

    status, body = request("/api/health")
    check("health responds 200", status == 200, f"got {status}")
    check('health says "ok"', b'"ok"' in body, body[:120].decode(errors="replace"))

    status, body = request("/api/catalog")
    check("catalogue responds 200", status == 200, f"got {status}")
    manifest = json.loads(body)["manifest"]

    published = [b for b in manifest["bundles"] if b.get("available")]
    print(f"  info  {len(published)} of {len(manifest['bundles'])} bundle(s) available")

    # The gate is the whole point of the service, so it is checked whether or
    # not anything is published: a bundle id that does not exist must still be
    # refused for missing credentials, never answered with a 404 that leaks
    # which ids are real.
    probe = published[0]["id"] if published else "pose-images"

    status, _ = request(f"/api/download/{probe}")
    check("download without a token is refused", status == 403, f"got {status}")

    status, _ = request(f"/api/download/{probe}?t=aaa.bbb")
    check("forged token is refused", status == 403, f"got {status}")

    status, _ = request(f"/api/download/{probe}?t=" + "A" * 200)
    check("garbage token is refused", status == 403, f"got {status}")

    if not published:
        print("  info  nothing published yet, skipping the download check")
        print("PASS")
        return 0

    # A real, correctly signed token, minted from the same secret the service
    # is running with. Inside the container that secret is always present —
    # the service refuses to start without it — but say so plainly rather than
    # ending on a traceback if this is ever run somewhere else.
    sys.path.insert(0, "/srv/app")
    try:
        from app.auth import issue_token
    except RuntimeError as exc:
        raise CheckFailed(f"cannot mint a token: {exc}") from exc

    token, _ = issue_token(request_id=None, ttl_seconds=300)

    bundle = published[0]
    status, payload = request(f"/api/download/{bundle['id']}?t={token}")
    check("a valid token is accepted", status == 200, f"got {status}")
    check(
        "the whole file is served",
        len(payload) == bundle["bytes"],
        f"got {len(payload)} bytes, manifest says {bundle['bytes']}",
    )

    print("PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckFailed as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
