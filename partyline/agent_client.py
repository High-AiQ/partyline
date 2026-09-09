"""Standalone authenticated API helper; credentials never enter shell arguments."""

import argparse
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
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("unsafe connection file")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("connection file must have mode 0600")
        data = json.load(stream)
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
            body = json.dumps(json.loads(raw)).encode()
        output = api_request(connection, args.method, args.path, body)
        if args.output:
            Path(args.output).write_bytes(output)
        else:
            sys.stdout.write(output.decode() + "\n")
        return 0
    except HTTPError as exc:
        print(f"Partyline request failed: HTTP {exc.code}", file=sys.stderr)
    except (OSError, ValueError, URLError):
        # Exception text may contain credentials or caller-supplied JSON.
        print("Partyline connection/request failed; check the connection file and API availability",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
