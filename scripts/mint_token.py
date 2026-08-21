#!/usr/bin/env python3
"""Mint a download token directly from SECRET_KEY, without the access form.

For operators and post-deploy checks. Submitting the real form to test a
deployment would write a fake personal-data record every time — records that
then sit in the PDPA-governed table pretending to be people. This mints an
equivalent token and writes nothing.

It grants no privilege that SECRET_KEY does not already confer: anyone able to
read the key can already sign tokens. Keep the key in a credential store.

    SECRET_KEY=... python3 scripts/mint_token.py
    SECRET_KEY=... python3 scripts/mint_token.py --ttl 300
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import sys
import time
from hashlib import sha256


def mint(secret: str, ttl: int, request_id: int | None) -> tuple[str, int]:
    expires_at = int(time.time()) + ttl
    payload = json.dumps(
        {"rid": request_id, "exp": expires_at},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, sha256).digest()
    encode = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")  # noqa: E731
    return f"{encode(payload)}.{encode(signature)}", expires_at


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ttl", type=int, default=300, help="lifetime in seconds (default 300)"
    )
    parser.add_argument(
        "--rid",
        type=int,
        default=None,
        help="access-request id to attribute downloads to; omitted by default "
        "so the download event is recorded without a data subject",
    )
    args = parser.parse_args()

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        print("error: SECRET_KEY is not set", file=sys.stderr)
        return 2
    if len(secret) < 32:
        print("error: SECRET_KEY must be at least 32 characters", file=sys.stderr)
        return 2

    token, _ = mint(secret, args.ttl, args.rid)
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
