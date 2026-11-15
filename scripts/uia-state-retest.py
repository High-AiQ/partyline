#!/usr/bin/env python3
"""One manual-change retest through the real stdio MCP tool, without elapsed-time waits."""
import argparse
import json
import os
import re
import subprocess
import sys


def rpc(process, ident, method, params):
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": ident,
                                    "method": method, "params": params}) + "\n")
    process.stdin.flush()
    for line in process.stdout:
        response = json.loads(line)
        if response.get("id") == ident:
            if "error" in response:
                raise RuntimeError(response["error"])
            result = response["result"]
            if result.get("isError"):
                raise RuntimeError(result)
            return result
    raise RuntimeError("MCP server closed before replying")


def call(process, ident, arguments):
    result = rpc(process, ident, "tools/call", {"name": "screen_elements", "arguments": arguments})
    return json.loads(result["content"][0]["text"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", help="existing attached process's connection JSON")
    parser.add_argument("--window", help="grant id or title, if several are shared")
    parser.add_argument("--query", default="=Manage listing content", help="exact link name or query")
    args = parser.parse_args()
    env = os.environ.copy()
    if args.connection:
        env["PARTYLINE_MCP_CONNECTION"] = args.connection
    if not env.get("PARTYLINE_MCP_CONNECTION"):
        parser.error("provide --connection or PARTYLINE_MCP_CONNECTION")
    process = subprocess.Popen([sys.executable, "-m", "partyline.mcp"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, env=env)
    try:
        rpc(process, 1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                      "clientInfo": {"name": "uia-state-retest", "version": "1"}})
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        options = {"query": args.query, "control_type": "Hyperlink", "refresh": True}
        if args.window:
            options["window"] = args.window
        before = call(process, 2, options)
        print(json.dumps({"before": before}, ensure_ascii=False))
        matches = re.findall(r"^\s*(\S+) Hyperlink ", before.get("lines", ""), re.MULTILINE)
        if len(matches) != 1:
            raise RuntimeError("expected exactly one link; narrow --query/--window")
        input("Choose the marketplace/trigger the lab card BY HAND; then press Enter here: ")
        # Deliberately preserve the before snapshot: a refresh would erase the evidence of staleness.
        inspected = call(process, 3, {"window": before["window"], "inspect": matches[0]})
        print(json.dumps({"inspect": inspected}, ensure_ascii=False))
        if "live" not in inspected:
            raise RuntimeError("inspect unavailable: deploy the state-truth server and helper first")
        print(inspected["verdict"])
    finally:
        process.stdin.close()
        process.terminate()
        process.wait()
        process.stdout.close()


if __name__ == "__main__":
    main()
