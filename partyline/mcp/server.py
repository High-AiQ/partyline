"""Minimal newline-delimited JSON-RPC MCP server over stdio."""

from __future__ import annotations

import json
import logging
import sys
import threading

from .. import __version__
from .client import ApiError, PartylineClient
from .render import render
from . import tools_captain, tools_core
from .validation import validate_arguments

logger = logging.getLogger(__name__)
MAX_LINE = 1_000_000


class MCPServer:
    def __init__(self, client: PartylineClient, output=None):
        self.client = client
        self.output = output or sys.stdout
        self._write_lock = threading.Lock()
        self._state_signature = None
        self._revoked = False

    def send(self, message: dict):
        raw = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            self.output.write(raw + "\n")
            self.output.flush()

    def response(self, ident, result=None, error=None):
        message = {"jsonrpc": "2.0", "id": ident}
        if error:
            message["error"] = error
        else:
            message["result"] = result or {}
        self.send(message)

    def _state(self):
        if self._revoked:
            raise ApiError("attachment credential is no longer valid")
        return self.client.capabilities()

    @staticmethod
    def _signature(state):
        return (state.get("kind"), state.get("role"), state.get("conv_id"),
                state.get("attachment_id"), bool(state.get("is_lead")),
                tuple(sorted(state.get("actions", []))))

    def handle(self, message: dict):
        if not isinstance(message, dict):
            return self.response(None, error={"code": -32600, "message": "invalid request"})
        ident = message.get("id")
        if message.get("jsonrpc") != "2.0":
            return self.response(ident, error={"code": -32600, "message": "invalid request"})
        method = message.get("method")
        if not isinstance(method, str):
            return self.response(ident, error={"code": -32600, "message": "invalid request"})
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self.response(ident, error={"code": -32602, "message": "invalid params"})
        if method == "initialize":
            return self.response(ident, {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "partyline", "version": __version__},
            })
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self.response(ident, {})
        if method == "tools/list":
            try:
                state = self._state()
                self._state_signature = self._signature(state)
                tools = tools_core.tool_list(state) + tools_captain.tool_list(state)
                return self.response(ident, {"tools": tools})
            except ApiError as exc:
                self._revoked = self._revoked or "HTTP 401" in str(exc)
                return self.response(ident, error={"code": -32001, "message": str(exc)})
        if method == "tools/call":
            return self._call(ident, params)
        if method.startswith("notifications/"):
            return None
        if ident is None:
            return None
        return self.response(ident, error={"code": -32601, "message": "method not found"})

    def _call(self, ident, params):
        name, args = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(args, dict):
            return self.response(ident, error={"code": -32602, "message": "invalid tool arguments"})
        try:
            state = self._state()  # Each call checks the live attachment capability.
            signature = self._signature(state)
            if signature != self._state_signature:
                changed = self._state_signature is not None
                self._state_signature = signature
                if changed:
                    self.send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
            core_names = {tool["name"] for tool in tools_core.tool_list(state)}
            captain_names = {tool["name"] for tool in tools_captain.tool_list(state)}
            if name in core_names:
                schema = next(tool["inputSchema"] for tool in tools_core.tool_list(state)
                              if tool["name"] == name)
                validate_arguments(schema, args)
                value = tools_core.call(self.client, name, args, state)
            elif name in captain_names:
                value = tools_captain.call(self.client, name, args, state)
            else:
                raise ValueError("tool is not currently available to this attachment")
            text = render(value, self.client.connection["api"].rstrip("/"))
            return self.response(ident, {"content": [{"type": "text", "text": text}]})
        except (ApiError, ValueError, KeyError, TypeError, OSError) as exc:
            self._revoked = self._revoked or (
                isinstance(exc, ApiError) and "HTTP 401" in str(exc))
            message = (str(exc) if isinstance(exc, (ApiError, ValueError))
                       else "invalid tool arguments or local file")
            return self.response(ident, {
                "content": [{"type": "text", "text": message}], "isError": True})
        except Exception:
            logger.exception("MCP tool call failed")
            return self.response(ident, {
                "content": [{"type": "text", "text": "Partyline MCP operation failed"}],
                "isError": True})

    def run(self, input_stream=None):
        stream = input_stream or sys.stdin
        while True:
            line = stream.readline(MAX_LINE + 1)
            if not line:
                break
            if len(line) > MAX_LINE:
                self.response(None, error={"code": -32700, "message": "request exceeds MCP input limit"})
                break
            try:
                message = json.loads(line)
            except RecursionError:
                self.response(None, error={
                    "code": -32700, "message": "request nesting exceeds parser limit"})
                continue
            except ValueError:
                self.response(None, error={"code": -32700, "message": "parse error"})
                continue
            self.handle(message)


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        client = PartylineClient()
    except (OSError, ValueError) as exc:
        print(f"Partyline MCP startup failed: {exc}", file=sys.stderr)
        return 2
    MCPServer(client).run()
    return 0
