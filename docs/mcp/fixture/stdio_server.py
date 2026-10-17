#!/usr/bin/env python3
"""Minimal MCP stdio server for client compatibility checks.

Set MCP_FIXTURE_LOG to a path to record sanitized JSON-RPC method names.
After the first tools/list response, this server emits list_changed once; a
subsequent tools/list response includes the second fixture tool.
"""

import json
import os
import sys
import threading
import time


_write_lock = threading.Lock()
_log_path = os.environ.get("MCP_FIXTURE_LOG")


def _send(message: dict) -> None:
    with _write_lock:
        sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def _log(method: str) -> None:
    if _log_path:
        with open(_log_path, "a", encoding="utf-8") as stream:
            stream.write(f"{time.monotonic():.3f} {method}\n")


def _log_call(params: dict) -> None:
    """Record sanitized tool names and arguments without credentials."""
    if _log_path:
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        with open(_log_path, "a", encoding="utf-8") as stream:
            stream.write(f"{time.monotonic():.3f} call {name} {json.dumps(arguments)}\n")


def _notify_changed() -> None:
    time.sleep(2)
    _send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})


for line in sys.stdin:
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        continue
    if not isinstance(request, dict):
        continue
    method = request.get("method")
    _log(str(method))
    request_id = request.get("id")
    if method == "initialize" and request_id is not None:
        _send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "partyline-compat-fixture", "version": "1"},
            },
        })
    elif method == "tools/list" and request_id is not None:
        tools = [{"name": "tool_a", "description": "Initial fixture tool", "inputSchema": {
            "type": "object", "properties": {},
        }}, {"name": "dispatch", "description": (
            "Call a named fixture tool, including tools added after connection startup. "
            "Use name=tool_b to reach the dynamically added tool."
        ), "inputSchema": {
            "type": "object", "properties": {
                "name": {"type": "string"}, "arguments": {"type": "object"},
            }, "required": ["name"],
        }}]
        if getattr(_notify_changed, "sent", False):
            tools.append({"name": "tool_b", "description": "Dynamically added fixture tool",
                          "inputSchema": {"type": "object", "properties": {}}})
        _send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}})
        if not getattr(_notify_changed, "sent", False):
            _notify_changed.sent = True
            threading.Thread(target=_notify_changed, daemon=True).start()
    elif method == "tools/call" and request_id is not None:
        params = request.get("params") or {}
        _log_call(params)
        name = params.get("name")
        result = "tool B result" if name == "tool_b" or (
            name == "dispatch" and (params.get("arguments") or {}).get("name") == "tool_b"
        ) else f"{name} result"
        _send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [
            {"type": "text", "text": result},
        ]}})
    elif request_id is not None:
        _send({"jsonrpc": "2.0", "id": request_id,
               "error": {"code": -32601, "message": "Method not found"}})
