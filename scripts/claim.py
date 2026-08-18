"""Claim, list, and release path-glob write locks on a line.

    uv run python -m scripts.claim take CONV --owner grok partyline/claims.py
    uv run python -m scripts.claim list CONV
    uv run python -m scripts.claim release CLAIM_ID --owner grok
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
DEFAULT_URL = f"http://127.0.0.1:{os.environ.get('PARTYLINE_PORT', '8642')}"


def request(method: str, path: str, payload: dict | None = None, base: str = DEFAULT_URL):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body}
        return exc.code, parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("PARTYLINE_API", DEFAULT_URL))
    sub = parser.add_subparsers(dest="cmd", required=True)

    take = sub.add_parser("take", help="claim one or more path globs")
    take.add_argument("conv")
    take.add_argument("--owner", required=True)
    take.add_argument("paths", nargs="+")

    listed = sub.add_parser("list", help="list live claims on a line")
    listed.add_argument("conv")

    release = sub.add_parser("release", help="drop a claim by id")
    release.add_argument("claim_id")
    release.add_argument("--owner")

    args = parser.parse_args(argv)
    if args.cmd == "take":
        code, body = request(
            "POST",
            f"/api/conversations/{args.conv}/claims",
            {"owner": args.owner, "paths": args.paths},
            args.url,
        )
        print(json.dumps(body, indent=2))
        return 0 if code == 200 else 1
    if args.cmd == "list":
        code, body = request("GET", f"/api/conversations/{args.conv}/claims", base=args.url)
        print(json.dumps(body, indent=2))
        return 0 if code == 200 else 1
    code, body = request(
        "DELETE",
        f"/api/claims/{args.claim_id}" + (f"?owner={args.owner}" if args.owner else ""),
        base=args.url,
    )
    print(json.dumps(body, indent=2))
    return 0 if code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
