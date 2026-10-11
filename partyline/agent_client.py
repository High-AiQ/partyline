"""Standalone authenticated API helper; credentials never enter shell arguments."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class Connection(TypedDict):
    api: str
    token: str
    conversation_id: str
    attachment_id: str
    handle: str


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an attachment credential to a redirect destination.
        return None


def load_connection(path: str) -> Connection:
    if os.name == 'nt':
        from partyline.windows_private import load_connection as load_windows
        return _validate_connection(load_windows(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("unsafe connection file")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("connection file must have mode 0600")
        data = json.load(stream)
    return _validate_connection(data)


def _validate_connection(data) -> Connection:
    if not isinstance(data, dict):
        raise ValueError("invalid connection file")
    for field in ("api", "token", "conversation_id", "attachment_id", "handle"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise ValueError("invalid connection file")
    base = urlsplit(data["api"])
    if base.scheme not in ("http", "https") or not base.hostname or base.username or base.password:
        raise ValueError("invalid API origin")
    if base.path not in ("", "/") or base.query or base.fragment:
        raise ValueError("API must be an origin")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(base.hostname, base.hostname)
    host = f"[{host}]" if ":" in host else host
    data["api"] = urlunsplit((base.scheme, host + (f":{base.port}" if base.port else ""), "", "", ""))
    return data


def derived_client_key(method: str, path: str, body: bytes) -> str:
    """A retry-safe key derived from the request itself.

    The helper does not retry in-process, but the caller does: it re-runs the
    identical command after `connection/request failed`, which may have been
    printed for a POST that actually succeeded (finding 2.7). Deriving the
    key — never invented per run — makes that re-run land as the original
    message. The ``d:`` prefix marks it derived, which the server reads as
    "retry window, not intent" (two minutes, not ten); a deliberate repeat
    needs a caller-made key.
    """
    digest = hashlib.sha256(b"\0".join((method.encode(), path.encode(), body))).hexdigest()
    return "d:" + digest[:62]  # the contract caps client_key at 64 characters


def with_client_key(method: str, path: str, body: bytes | None) -> bytes | None:
    """Stamp a message POST with its derived idempotency key, if unstamped."""
    if body is None or method != "POST" or not urlsplit(path).path.endswith("/messages"):
        return body
    try:
        payload = json.loads(body)
    except ValueError:
        return body
    if not isinstance(payload, dict) or payload.get("client_key"):
        return body
    payload["client_key"] = derived_client_key(method, path, body)
    return json.dumps(payload).encode()


def note_replay(output: bytes) -> None:
    """On a replay, say so: a caller that believes it posted new words is worse
    than the double post the key prevents (finding 2.7's review)."""
    try:
        payload = json.loads(output)
    except ValueError:
        return
    if isinstance(payload, dict) and payload.get("replayed"):
        print(
            f"replayed original message {payload.get('id')}; nothing new was posted — "
            "add a distinct client_key to post the same text again",
            file=sys.stderr,
        )


def api_request(connection: Connection, method: str, path: str, body: bytes | None = None) -> bytes:
    parsed = urlsplit(path)
    if not path.startswith("/api/") or parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("request path must be a local /api/ path")
    request = Request(connection["api"] + path, data=body, method=method,
                      headers={"Authorization": "Bearer " + connection["token"],
                               "Content-Type": "application/json"})
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        return response.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("context", help="show identity and API origin, never the credential")
    request = commands.add_parser("request", help="call an authorized API route")
    request.add_argument("method", choices=("GET", "POST", "PUT", "PATCH", "DELETE"))
    request.add_argument("path")
    request.add_argument("--json-file", help="JSON body file, or - for stdin")
    request.add_argument("--output", help="write response bytes to this file")
    args = parser.parse_args(argv)
    try:
        connection = load_connection(args.connection)
        if args.command == "context":
            print(json.dumps({key: value for key, value in connection.items() if key != "token"}))
            return 0
        body = None
        if args.json_file:
            raw = sys.stdin.read() if args.json_file == "-" else Path(args.json_file).read_text()
            body = with_client_key(args.method, args.path, json.dumps(json.loads(raw)).encode())
        output = api_request(connection, args.method, args.path, body)
        if args.output:
            Path(args.output).write_bytes(output)
        else:
            sys.stdout.write(output.decode() + "\n")
        note_replay(output)
        return 0
    except HTTPError as exc:
        # The server's reason is the one thing a caller can act on: a 409 with
        # no detail sent a captain improvising instead of renaming a handle.
        print(f"Partyline request failed: HTTP {exc.code}: {_detail(exc)}", file=sys.stderr)
    except (OSError, ValueError, URLError):
        # Exception text may contain credentials or caller-supplied JSON.
        print("Partyline connection/request failed; check the connection file and API availability",
              file=sys.stderr)
    return 1


def _detail(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode() or "{}")
    except (OSError, ValueError):
        return exc.reason or ""
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return detail if isinstance(detail, str) else json.dumps(detail or payload)


if __name__ == "__main__":
    raise SystemExit(main())
