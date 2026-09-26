"""Approve one restart request using trusted local database write access."""

import argparse
import json
import sqlite3
import urllib.request

from partyline.operator_restart import issue


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OSError("refusing to redirect a local operator approval")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="existing service database")
    parser.add_argument("--port", type=int, default=8643)
    parser.add_argument("--request", required=True, help="exact pending restart request id")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        token = issue(args.database, args.request)
        body = json.dumps({"request_id": args.request, "token": token}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.port}/api/restart-request/operator-approve",
            data=body, headers={"Content-Type": "application/json"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=30) as response:
            json.load(response)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"restart approval failed: {exc}\n")
    print(f"Approved restart {args.request}; verify the new version and attachment recovery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
