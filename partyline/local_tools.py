"""Server half of local tools: sessions the person granted on their computer, routed calls and audit.

The helper owns consent, the kill switch, expiry and the add-on connection; this side only routes an agent's
calls to it while a session is active, limits them and keeps the audit. Sessions live in memory only.
"""

import asyncio
import re
import time
import uuid

from . import local_tools_audit as audit
from . import local_tools_media as media
from .contracts import MessageEvent, MessageResponse
from .local_tools_state import ToolLimits, ToolSession
from .screen_connections import notice

TOOLS_VERSION = 1
TOOL_MESSAGES = ("tools_granted", "tools_revoked", "tool_result")
TOO_OLD = "helper too old for local tools: update partyline-helper on that computer and restart it"
NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
GRACE = 5            # seconds the server waits beyond a call's own timeout
AUDIT_DELAY = 60
AUDIT_BATCH = 25


class LocalTools:
    def __init__(self, hub, limits=None, clock=time.monotonic, sleep=asyncio.sleep, deadline=asyncio.timeout):
        self.hub = hub
        self.deadline = deadline
        self.limits = limits or ToolLimits.from_env()
        self.clock, self.sleep = clock, sleep
        self.sessions: dict[str, ToolSession] = {}  # by line
        self.waiters: dict[str, tuple[str, str, asyncio.Future]] = {}

    def view(self, conv_id: str) -> dict | None:
        item = self.sessions.get(conv_id)
        if not item:
            return None
        return {"status": item.status, "tool": item.tool, "agent": item.agent, "checker": item.checker,
                "reason": item.reason, "calls": item.count, "info": item.info}

    def device(self, conv_id: str, name: str | None = None) -> dict:
        online = [d for d in self.hub.devices.values()
                  if d["conv_id"] == conv_id and (name is None or d["name"] == name)]
        if not online:
            raise ValueError("no paired computer is online on this line")
        if len(online) > 1:
            names = ", ".join(sorted(d["name"] for d in online))
            raise ValueError(f"several computers are online; pass the computer's name ({names})")
        if online[0].get("tools", 0) < TOOLS_VERSION:
            raise ValueError(TOO_OLD)
        return online[0]

    async def request(self, conv_id: str, agent: str, line_name: str, tool: str, checker: bool = False,
                      device_name: str | None = None) -> dict:
        if not NAME.match(tool):
            raise ValueError("invalid tool name")
        item = self.sessions.get(conv_id)
        scope_only = False
        if item and item.status == "pending" or item and item.scope_pending:
            raise ValueError("a request is already waiting for the person's answer")
        if item and item.status == "active":
            if item.agent != agent or item.tool != tool:
                raise ValueError(f"{item.tool} tools are held by {item.agent}")
            if item.checker or not checker:
                return {"status": "granted", "message": "Local tools are already active."}
            scope_only = True
        device = self.device(conv_id, device_name)
        if not scope_only:
            item = ToolSession(str(uuid.uuid4()), conv_id, device["id"], tool, agent)
        item.scope_pending = scope_only
        message = {"type": "tools_request", "session_id": item.session_id, "tool": tool,
                   "requested_by": agent, "line_name": line_name, "checker": checker,
                   "scope_only": scope_only}
        try:
            await device["socket"].send_json(message)
        except Exception as exc:
            item.scope_pending = False
            raise ValueError("the computer could not be reached") from exc
        self.sessions[conv_id] = item
        return {"status": "pending", "message": (
            "The person is being asked on their computer (60 s). You will be @mentioned with the answer; "
            "do not call tools until then.")}

    async def from_helper(self, device: dict, message: dict) -> None:
        kind = message.get("type")
        if kind == "tool_result":
            data = await media.read(device, message)
            entry = self.waiters.get(message.get("call_id"))
            if entry and entry[0] == device["id"] and not entry[2].done():
                entry[2].set_result(message if data is None else {**message, "data": data})
            return
        item = next((s for s in self.sessions.values() if s.session_id == message.get("session_id")
                     and s.device_id == device["id"]), None)
        if not item:
            return
        reason = str(message.get("reason") or "revoked on the computer")[:200]
        who = f"@{item.agent} "
        if kind == "tools_granted" and (item.status == "pending" or item.scope_pending):
            first = item.status == "pending"
            item.status, item.scope_pending = "active", False
            item.checker = bool(message.get("checker"))
            if isinstance(message.get("info"), dict):
                item.info = {str(k)[:40]: str(v)[:200] for k, v in list(message["info"].items())[:8]}
            await self._event(item, f"granted (render checks: {'yes' if item.checker else 'no'})")
            await notice(self.hub, item.conv_id, f"{who}{item.tool} tools on {device['name']} "
                         f"{'granted' if first else 'now include render checks'} "
                         f"({'render checks allowed' if item.checker else 'no render checks'}).")
        elif kind == "tools_granted" and item.status == "active" and item.checker \
                and not message.get("checker"):
            item.checker = False  # the person withdrew render checks on their computer; only "off" counts
            await self._event(item, "render checks withdrawn on the computer")
            await notice(self.hub, item.conv_id, f"{who}Render checks were switched off on {device['name']}.")
        elif kind == "tools_revoked" and item.status == "pending":
            self.sessions.pop(item.conv_id, None)
            await notice(self.hub, item.conv_id, f"{who}{item.tool} tools were not granted ({reason}).")
        elif kind == "tools_revoked" and item.scope_pending and message.get("scope_only") is True:
            item.scope_pending = False  # only the extra scope was refused; the session lives on
            await notice(self.hub, item.conv_id, f"{who}Render checks were not granted ({reason}).")
        elif kind == "tools_revoked":
            await self.revoke(item, reason, tell_helper=False)

    async def revoke(self, item: ToolSession, reason: str, tell_helper: bool = True) -> bool:
        if item.status == "revoked":
            return False
        was_active = item.status == "active"
        item.status, item.reason, item.scope_pending = "revoked", reason, False
        for _, session_id, future in list(self.waiters.values()):
            if session_id == item.session_id:
                future.cancel()
        await self._event(item, f"revoked ({reason})")
        await self.flush(item)
        device = self.hub.devices.get(item.device_id)
        if tell_helper and device:
            try:
                await device["socket"].send_json({"type": "tools_revoked", "session_id": item.session_id,
                                                  "reason": reason})
            except Exception:
                pass
        if was_active:
            await notice(self.hub, item.conv_id, f"@{item.agent} {item.tool} tools revoked ({reason}); "
                         "tool calls are refused until the person grants a new session.")
        return True

    async def end_device(self, device_id: str, reason: str) -> None:
        for item in list(self.sessions.values()):
            if item.device_id == device_id:
                await self.revoke(item, reason, tell_helper=False)

    async def end(self, conv_id: str, agent: str) -> dict:
        item = self.sessions.get(conv_id)
        if not item or item.status == "revoked":
            raise ValueError("no local tools session is active on this line")
        if item.agent != agent:
            raise ValueError(f"local tools are held by {item.agent}")
        await self.revoke(item, f"ended by {agent}")
        return {"status": "ended"}

    def _spend(self, item: ToolSession) -> None:
        now = self.clock()
        while item.times and now - item.times[0] >= 60:
            item.times.popleft()
        if len(item.times) >= self.limits.per_minute:
            raise ValueError(f"rate limit: at most {self.limits.per_minute} calls per minute")
        if item.count >= self.limits.per_session:
            raise ValueError(f"session cap: at most {self.limits.per_session} calls per session; "
                             "ask the person to grant a new session")
        item.times.append(now)
        item.count += 1

    async def call(self, conv_id: str, agent: str, op: str, args: dict, timeout: float, store=None) -> dict:
        item = self.sessions.get(conv_id)
        if not item or item.status != "active":
            why = f" ({item.reason})" if item and item.reason else ""
            raise ValueError(f"local tools are not granted{why}; ask the person with a request first")
        if item.agent != agent:
            raise ValueError(f"local tools were granted to {item.agent}")
        device = self.hub.devices.get(item.device_id)
        if not device:
            await self.revoke(item, "the computer went offline", tell_helper=False)
            raise ValueError("the computer is offline")
        code = args.get("code") if isinstance(args.get("code"), str) else None
        if code is not None and len(code.encode()) > self.limits.max_code:
            raise ValueError(f"code is larger than {self.limits.max_code} bytes")
        self._spend(item)
        call_id = str(uuid.uuid4())
        await self._record(item, "call", op, audit.entry(op, args, code), code)
        future = asyncio.get_running_loop().create_future()
        self.waiters[call_id] = (device["id"], item.session_id, future)
        try:
            async with self.deadline(timeout + GRACE):
                await device["socket"].send_json({"type": "tool_call", "session_id": item.session_id,
                                                  "call_id": call_id, "op": op, "args": args,
                                                  "timeout": timeout})
                answer = await future
        except (TimeoutError, asyncio.CancelledError):
            if asyncio.current_task().cancelling():
                raise
            try:
                await device["socket"].send_json({"type": "tool_cancel", "session_id": item.session_id,
                                                  "call_id": call_id})
            except Exception:
                pass
            ended = item.status == "revoked"
            await self._record(item, "result", op, "revoked during the call" if ended else "no answer")
            raise ValueError("the session was revoked during the call" if ended else
                             "the computer did not answer in time; cancel requested") from None
        finally:
            self.waiters.pop(call_id, None)
            if not future.done():
                future.cancel()
        result = answer.get("result") if isinstance(answer.get("result"), dict) else {}
        if not answer.get("ok"):
            error = str(answer.get("error") or "refused")[:300]
            await self._record(item, "result", op, f"refused: {error}")
            raise ValueError(f"the computer refused the call: {error}")
        failure = result.get("error")
        outcome = "ok" if result.get("ok", True) else f"script error: {(failure or {}).get('type', '?')}"
        try:
            result = await media.attach(store, item, op, result, answer)
        except ValueError as exc:
            await self._record(item, "result", op, f"refused: {exc}")
            raise
        await self._record(item, "result", op, outcome + media.note(result))
        return result

    async def note(self, item: ToolSession, op: str, text: str) -> None:
        """An audit row for something done with the session besides a call (a render check)."""
        await self._record(item, "check", op, text)

    async def _event(self, item: ToolSession, text: str) -> None:
        await self._record(item, "event", "session", text)

    async def _record(self, item: ToolSession, kind: str, op: str, entry: str, code=None) -> None:
        audit.record(self.hub.runtime.db, item.session_id, item.conv_id, item.agent, kind, op, entry, code)
        item.audit_count += 1
        if item.audit_count >= AUDIT_BATCH or item.status == "revoked":
            await self.flush(item)
        elif item.flusher is None:
            item.flusher = asyncio.create_task(self._flush_later(item))

    async def _flush_later(self, item: ToolSession) -> None:
        await self.sleep(AUDIT_DELAY)
        item.flusher = None
        await self.flush(item)

    async def flush(self, item: ToolSession) -> None:
        flusher, item.flusher = item.flusher, None
        if flusher and flusher is not asyncio.current_task():
            flusher.cancel()
        message = audit.publish(self.hub.runtime.db, item.session_id)
        if message:
            item.audit_count = 0
            await self.hub.runtime.broadcast(
                item.conv_id, MessageEvent(message=MessageResponse.model_validate(message)))
