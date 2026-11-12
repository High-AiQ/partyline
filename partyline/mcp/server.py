"""Minimal newline-delimited JSON-RPC MCP server over stdio."""

from __future__ import annotations

import json
import logging
import sys
import threading

from .. import __version__
from .client import ApiError, PartylineClient
from .render import render
from . import tools_blender, tools_captain, tools_check, tools_control, tools_core, tools_tasks
from . import tools_resources, tools_handover
from .captain_schemas import ACK_HINT
from .validation import validate_arguments

logger = logging.getLogger(__name__)
MAX_LINE = 1_000_000
# Python 3.14's json parser no longer recurses, so RecursionError stopped
# being the nesting guard; the bound is enforced here, on any interpreter.
MAX_NESTING = 1_000


class MCPServer:
    def __init__(self, client: PartylineClient, output=None):
        self.client = client
        self.output = output or sys.stdout
        self._write_lock = threading.Lock()
        self._state_signature = None
        self._revoked = False
        self._dynamic_screen_tools = None
        self._capability_version = None
        self._watch_ready = threading.Event()
        self._poll_stop = threading.Event()
        self._poll_thread = None

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
        screen_state = ((bool(state.get("screen_read")), bool(state.get("screen_control")),
                         bool(state.get("screen_windows")))
                        if state.get("dynamic_screen_tools") else ())
        return (state.get("kind"), state.get("role"), state.get("conv_id"),
                state.get("attachment_id"), bool(state.get("is_lead")),
                tuple(sorted(state.get("actions", []))), screen_state)

    def _refresh_signature(self):
        """Fetch capabilities after the server reports a version change."""
        try:
            state = self._state()
        except (ApiError, OSError) as exc:
            self._revoked = self._revoked or "HTTP 401" in str(exc)
            return False
        signature = self._signature(state)
        if self._state_signature is not None and signature != self._state_signature:
            self.send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        self._state_signature = signature
        self._capability_version = state.get("capability_version", self._capability_version)
        return True

    def _follow_stream(self):
        """Apply each pushed revision; True once the stream delivered at least one."""
        delivered = False
        try:
            for version in self.client.capability_stream():
                # A refresh records the revision its capabilities were read at.
                if version != self._capability_version and not self._refresh_signature():
                    return False
                delivered = True
        except Exception:
            if not self._poll_stop.is_set():
                logger.warning("MCP capability stream failed; it will reconnect", exc_info=True)
            return False
        return delivered

    def _poll_capabilities(self):
        """Hold one pushed stream open; reconnect only after it breaks."""
        delay = 0.5
        while not self._poll_stop.is_set():
            self._watch_ready.wait()
            if self._poll_stop.is_set() or self._revoked:
                return
            # no-poll (e): bounded reconnect backoff after a broken stream; a served one resets it
            delay = 0.5 if self._follow_stream() else min(delay * 2, 10)
            if self._revoked or self._poll_stop.wait(delay):
                return

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
                self._dynamic_screen_tools = bool(state.get("dynamic_screen_tools"))
                self._state_signature = self._signature(state)
                self._capability_version = state.get("capability_version")
                if self._dynamic_screen_tools:
                    self._watch_ready.set()
                tools = (tools_core.tool_list(state) + tools_captain.tool_list(state)
                         + tools_tasks.tool_list(state) + tools_resources.tool_list(state)
                         + tools_handover.tool_list(state) + tools_control.tool_list(state)
                         + tools_blender.tool_list(state) + tools_check.tool_list(state))
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
            self._dynamic_screen_tools = bool(state.get("dynamic_screen_tools"))
            if self._dynamic_screen_tools:
                self._watch_ready.set()
            if signature != self._state_signature:
                changed = self._state_signature is not None
                self._state_signature = signature
                if changed:
                    self.send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
            core_names = {tool["name"] for tool in tools_core.tool_list(state)}
            captain_names = {tool["name"] for tool in tools_captain.tool_list(state)}
            task_names = {tool["name"] for tool in tools_tasks.tool_list(state)}
            resource_names = {tool['name'] for tool in tools_resources.tool_list(state)}
            handover_names = {tool['name'] for tool in tools_handover.tool_list(state)}
            control_names = {tool['name'] for tool in tools_control.tool_list(state)}
            blender_names = {tool['name'] for tool in tools_blender.tool_list(state)}
            if name in blender_names:
                value = tools_blender.call(self.client, name, args, state)
            elif name in {tool['name'] for tool in tools_check.tool_list(state)}:
                value = tools_check.call(self.client, name, args, state)
            elif name in control_names:
                value = tools_control.call(self.client, name, args, state)
            elif name in handover_names:
                value = tools_handover.call(self.client, name, args, state)
            elif name in resource_names:
                value = tools_resources.call(self.client, name, args, state)
            elif name in task_names:
                value = tools_tasks.call(self.client, name, args, state)
            elif name in core_names:
                schema = next(tool["inputSchema"] for tool in tools_core.tool_list(state)
                              if tool["name"] == name)
                validate_arguments(schema, args, ACK_HINT if name == "reports" else "")
                value = tools_core.call(self.client, name, args, state)
            elif name in captain_names:
                value = tools_captain.call(self.client, name, args, state)
            else:
                if name in {"screen_frame", "screen_elements", "screen_element_action",
                            "screen_control_request", "screen_click", "screen_move",
                            "screen_drag", "screen_scroll", "screen_type", "screen_key"}:
                    raise ApiError("no screen shared with you")
                raise ValueError("tool is not currently available to this attachment")
            text = render(value, self.client.connection["api"].rstrip("/"))
            return self.response(ident, {"content": [{"type": "text", "text": text}]})
        except (ApiError, ValueError, KeyError, TypeError, OSError) as exc:
            self._revoked = self._revoked or (
                isinstance(exc, ApiError) and "HTTP 401" in str(exc))
            creating = name == "create_task" or (name == "captain" and args.get("op") == "create_task")
            if creating and isinstance(exc, OSError):
                message = ("create_task connection failed; the task may already exist. "
                           "Retry create_task with the same name and assignment, or inspect tasks().")
            else:
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
        self._poll_thread = threading.Thread(target=self._poll_capabilities, daemon=True)
        self._poll_thread.start()
        try:
            while True:
                line = stream.readline(MAX_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_LINE:
                    self.response(None, error={"code": -32700, "message": "request exceeds MCP input limit"})
                    break
                if nesting_depth(line) > MAX_NESTING:
                    self.response(None, error={
                        "code": -32700, "message": "request nesting exceeds parser limit"})
                    continue
                try:
                    message = json.loads(line)
                except RecursionError:  # pragma: no cover - older parsers, kept as a backstop
                    self.response(None, error={
                        "code": -32700, "message": "request nesting exceeds parser limit"})
                    continue
                except ValueError:
                    self.response(None, error={"code": -32700, "message": "parse error"})
                    continue
                self.handle(message)
        finally:
            self._poll_stop.set()
            self._watch_ready.set()
            interrupt = getattr(self.client, "interrupt", None)
            if interrupt:
                try:
                    interrupt()
                except OSError:
                    logger.debug("MCP client connection close was already complete", exc_info=True)
            if self._poll_thread:
                self._poll_thread.join(timeout=1)


def nesting_depth(text: str) -> int:
    """Deepest bracket nesting outside string literals; cheap and parser-independent."""
    depth = deepest = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "]}":
            depth -= 1
    return deepest


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        client = PartylineClient()
    except (OSError, ValueError) as exc:
        print(f"Partyline MCP startup failed: {exc}", file=sys.stderr)
        return 2
    MCPServer(client).run()
    return 0
