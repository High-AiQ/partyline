"""Standalone authenticated API helper; credentials never enter shell arguments.

A binary response (an image from `/api/media/<id>/thumb`, say) is saved to
`media-<id>-<variant>.<ext>` in the current directory and the path is printed;
`--output FILE` chooses the file instead. Redirects are never followed.
"""

import argparse
import errno
import hashlib
import http.client
import json
import mimetypes
import os
import re
from pathlib import Path
import socket
import ssl
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


def api_request(connection: Connection, method: str, path: str,
                body: bytes | None = None) -> tuple[bytes, str]:
    """The response body and its Content-Type (empty when the server sent none)."""
    parsed = urlsplit(path)
    if not path.startswith("/api/") or parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("request path must be a local /api/ path")
    request = Request(connection["api"] + path, data=body, method=method,
                      headers={"Authorization": "Bearer " + connection["token"],
                               "Content-Type": "application/json"})
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        kind = response.headers.get_content_type() if response.headers.get("Content-Type") else ""
        return response.read(), kind


TEXT_TYPES = ("application/json",)

NETWORK_ERRNOS = frozenset(getattr(errno, name) for name in (
    "ETIMEDOUT", "EHOSTUNREACH", "ENETUNREACH", "ENETDOWN", "EHOSTDOWN") if hasattr(errno, name))
LOCAL_FILE_ERRORS = (FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError)
FAILURE_TEXT = {
    "timeout": "timed out waiting for the Partyline server to answer; it may be slow or busy",
    "refused": "the Partyline server refused the connection; it is down or the address is wrong",
    "reset": "the connection to Partyline was reset or closed before a full reply",
    "network": "the network path to Partyline failed",
}


def classify_failure(exc: BaseException) -> str:
    """`timeout`, `refused`, `reset`, `network`, or `local` (bad file, path or input).

    Looks only at the exception's type, never its text: that text can hold a
    credential or the caller's JSON.
    """
    if isinstance(exc, URLError) and not isinstance(exc, HTTPError):
        inner = exc.reason
        if isinstance(inner, BaseException):
            return classify_failure(inner)
        return "timeout" if "timed out" in str(inner) else "network"
    if isinstance(exc, TimeoutError):  # socket.timeout is the same class
        return "timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "refused"
    if isinstance(exc, (ConnectionError, http.client.HTTPException)):
        return "reset"
    if isinstance(exc, (socket.gaierror, socket.herror, ssl.SSLError)):
        return "network"
    if (isinstance(exc, OSError) and not isinstance(exc, LOCAL_FILE_ERRORS)
            and exc.errno in NETWORK_ERRNOS):
        return "network"
    return "local"


def failure_text(kind: str, *, changes_state: bool) -> str:
    """What happened, and whether the server may already have acted on the request."""
    text = FAILURE_TEXT[kind]
    if kind == "refused":
        return text + "; nothing was sent, so retrying is safe once it is reachable"
    if changes_state:
        return (text + ". The action may already have been applied: check current state "
                "(for a decision or grant, read the request or task) before retrying")
    return text + "; this read changed nothing, so retrying is safe"


def is_text(content_type: str, output: bytes) -> bool:
    """JSON and text/* print; anything else, or bytes that are not UTF-8, is binary."""
    if content_type and not (content_type.startswith("text/") or content_type in TEXT_TYPES):
        return False
    try:
        output.decode()
    except UnicodeDecodeError:
        return False
    return True


def default_output_name(path: str, content_type: str) -> Path:
    """`media-<id>-<variant>.<ext>` for a media path, else a name from the path, in the cwd."""
    parts = [part for part in urlsplit(path).path.split("/") if part]
    if parts[:2] == ["api", "media"] and len(parts) >= 3:
        stem = "-".join(["media", *parts[2:4]])
    else:
        stem = "-".join(re.sub(r"[^A-Za-z0-9_.]", "_", part) for part in parts[1:]) or "response"
    ext = mimetypes.guess_extension(content_type) if content_type else None
    return Path(f"{stem}{ext or '.bin'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("context", help="show identity and API origin, never the credential")
    request = commands.add_parser("request", help="call an authorized API route")
    request.add_argument("method", choices=("GET", "POST", "PUT", "PATCH", "DELETE"))
    request.add_argument("path")
    request.add_argument("--json-file", help="JSON body file, or - for stdin")
    request.add_argument("--output", help="write bytes here (binary default: media-<id>-<variant>.<ext>)")
    args = parser.parse_args(argv)
    stage = "connection file"
    try:
        connection = load_connection(args.connection)
        if args.command == "context":
            print(json.dumps({key: value for key, value in connection.items() if key != "token"}))
            return 0
        body = None
        stage = "request input"
        if args.json_file:
            raw = sys.stdin.read() if args.json_file == "-" else Path(args.json_file).read_text()
            body = with_client_key(args.method, args.path, json.dumps(json.loads(raw)).encode())
        stage = "request"
        output, content_type = api_request(connection, args.method, args.path, body)
        stage = "output"
        if args.output:
            Path(args.output).write_bytes(output)
        elif is_text(content_type, output):
            sys.stdout.write(output.decode() + "\n")
        else:
            saved = default_output_name(args.path, content_type)
            saved.write_bytes(output)
            print(saved)
        note_replay(output)
        return 0
    except HTTPError as exc:
        # The server's reason is the one thing a caller can act on: a 409 with
        # no detail sent a captain improvising instead of renaming a handle.
        print(f"Partyline request failed: HTTP {exc.code}: {_detail(exc)}", file=sys.stderr)
    except (OSError, ValueError, URLError, http.client.HTTPException) as exc:
        # Exception text may contain credentials or caller-supplied JSON: say
        # only what kind of failure it was, never its message.
        kind = classify_failure(exc) if stage == "request" else "local"
        if kind == "local":
            print(f"Partyline request not sent or not saved: bad local {stage} "
                  "(check the connection file, --json-file and --output paths)", file=sys.stderr)
        else:
            print("Partyline request failed: "
                  + failure_text(kind, changes_state=args.method != "GET"), file=sys.stderr)
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
