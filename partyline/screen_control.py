"""Server half of agent control: grants, limits, helper actions and batched audit notes."""

import asyncio
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from .contracts import MessageEvent, MessageResponse
from .screen_audit import publish, record
from .screen_connections import notice
from .screen_control_actions import ControlAction, command, describe

CONTROL_VERSION = 1
CONTROL_MESSAGES = ("control_granted", "control_revoked", "action_result")
TOO_OLD = "helper too old for control: update partyline-helper on that computer and restart it"
ACTION_TIMEOUT = 5
FRAME_TIMEOUT = 3
AUDIT_DELAY = 60
AUDIT_BATCH = 100


def plain_move(entry: str) -> bool:
    return entry.startswith("move (") and entry.endswith(")") and entry.count("(") == 1


@dataclass(frozen=True)
class ControlLimits:
    per_second: int = 10
    max_text: int = 500
    per_session: int = 300

    @classmethod
    def from_env(cls, env=os.environ) -> "ControlLimits":
        def read(name: str, default: int) -> int:
            raw = env.get(name, "").strip()
            if not raw:
                return default
            if not raw.isdigit() or int(raw) < 1:
                raise ValueError(f"{name} must be a positive integer, not {raw!r}")
            return int(raw)

        return cls(read("PARTYLINE_CONTROL_RATE", cls.per_second),
                   read("PARTYLINE_CONTROL_MAX_TEXT", cls.max_text),
                   read("PARTYLINE_CONTROL_SESSION_ACTIONS", cls.per_session))


@dataclass
class Grant:
    share_id: str
    requested_by: str
    holder: str | None  # the agent the person granted; None when granted with the share itself
    status: str = "pending"  # pending -> active -> revoked
    reason: str = ""
    times: deque = field(default_factory=deque)
    count: int = 0
    audit: list = field(default_factory=list)
    audit_count: int = 0
    flusher: asyncio.Task | None = None
    last_actor: str | None = None


class ControlHub:
    def __init__(self, hub, limits=None, clock=time.monotonic, sleep=asyncio.sleep):
        self.hub = hub
        self.limits = limits or ControlLimits.from_env()
        self.clock, self.sleep = clock, sleep
        self.grants: dict[str, Grant] = {}
        self.waiters: dict[str, tuple[str, str, asyncio.Future]] = {}

    def view(self, share) -> dict | None:
        grant = self.grants.get(share.share_id)
        if not grant:
            return None
        return {"status": grant.status, "holder": grant.holder, "requested_by": grant.requested_by,
                "reason": grant.reason, "actions": grant.count}

    def target(self, conv_id: str):
        share = self.hub.shares.get(conv_id)
        if not share or share.status != "active":
            raise ValueError("nobody is sharing a screen on this line")
        if share.share_id in self.hub.walkthroughs.items:
            raise ValueError("agent control is unavailable during a Show me recording")
        device = self.hub.devices.get(share.device_id)
        if not device:
            raise ValueError("the sharing computer is offline")
        if device.get("control", 0) < CONTROL_VERSION:
            raise ValueError(TOO_OLD)
        return share, device

    def expect(self, share, person: str) -> None:
        """The person asked for control with the share; the helper prompts after share consent."""
        self.grants[share.share_id] = Grant(share.share_id, person, None)

    async def request(self, conv_id: str, agent: str, line_name: str) -> dict:
        share, device = self.target(conv_id)
        grant = self.grants.get(share.share_id)
        if grant and grant.status == "revoked":
            raise ValueError(f"agent control was revoked for this share ({grant.reason}); "
                             "the person must start a new share before control can be asked again")
        if grant and grant.status == "active":
            if grant.holder not in (None, agent):
                raise ValueError(f"agent control is held by {grant.holder}")
            return {"status": "granted", "message": "Agent control is active; use screen_click etc."}
        if grant:
            raise ValueError("a control request is already waiting for the person's answer")
        self.grants[share.share_id] = grant = Grant(share.share_id, agent, agent)
        try:
            await device["socket"].send_json({"type": "control_request", "share_id": share.share_id,
                                               "requested_by": agent, "line_name": line_name})
        except Exception as exc:
            self.grants.pop(share.share_id, None)
            raise ValueError("the sharing computer could not be reached") from exc
        await self._changed(share)
        return {"status": "pending", "message": (
            "The person is being asked on their computer (60 s). You will be @mentioned with the answer; "
            "do not call screen actions until then.")}

    async def from_helper(self, device: dict, message: dict) -> None:
        kind = message.get("type")
        if kind == "action_result":
            entry = self.waiters.get(message.get("request_id"))
            if entry and entry[0] == device["id"] and not entry[2].done():
                entry[2].set_result(message)
            return
        share = self.hub._share(message.get("share_id"), device["id"])
        grant = self.grants.get(share.share_id) if share else None
        if not grant:
            return
        reason = str(message.get("reason") or "revoked on the computer")[:200]
        mention = f"@{grant.holder} " if grant.holder else ""
        if kind == "control_granted" and grant.status == "pending":
            grant.status = "active"
            from .capability_versions import bump_runtime
            bump_runtime(self.hub.runtime)
            await self._changed(share)
            who = f"to {grant.holder}" if grant.holder else "to agents on this line"
            await notice(self.hub, share.conv_id,
                         f"{mention}Agent control of {device['name']} granted {who}. Actions use frame "
                         "pixels of the latest screen_frame; moving the mouse or pressing a key there "
                         "takes control back.")
        elif kind == "control_revoked" and grant.status == "pending":
            self.grants.pop(share.share_id, None)
            await self._changed(share)
            await notice(self.hub, share.conv_id, f"{mention}Agent control was not granted ({reason}).")
        elif kind == "control_revoked" and grant.status == "active":
            await self.revoke(share, reason, tell_helper=False)

    async def revoke(self, share, reason: str, tell_helper: bool = True) -> bool:
        grant = self.grants.get(share.share_id)
        if not grant or grant.status == "revoked":
            return False
        status, grant.status, grant.reason = grant.status, "revoked", reason
        if status == "active":
            from .capability_versions import bump_runtime
            bump_runtime(self.hub.runtime)
        await self.flush(grant, share.conv_id)
        device = self.hub.devices.get(share.device_id)
        if tell_helper and device:
            try:
                await device["socket"].send_json({"type": "control_revoked", "share_id": share.share_id,
                                                   "reason": reason})
            except Exception:
                pass
        await self._changed(share)
        who = grant.last_actor or grant.holder
        if status == "active" or who:
            await notice(self.hub, share.conv_id,
                         f"{'@' + who + ' ' if who else ''}Agent control "
                         f"{'revoked' if status == 'active' else 'request withdrawn'} ({reason}); screen "
                         "actions are refused for the rest of this share.")
        return True

    async def end(self, share, reason: str) -> None:
        """The share ended or the computer disconnected; control ends with it."""
        for _, share_id, future in list(self.waiters.values()):
            if share_id == share.share_id:
                future.cancel()
        grant = self.grants.pop(share.share_id, None)
        if grant and grant.status == "active":
            await self.flush(grant, share.conv_id)
            await self._note(share.conv_id, f"Agent control ended with the share ({reason}).")
        elif grant and grant.flusher:
            grant.flusher.cancel()

    def _spend(self, grant: Grant) -> None:
        now, limits = self.clock(), self.limits
        while grant.times and now - grant.times[0] >= 1:
            grant.times.popleft()
        if len(grant.times) >= limits.per_second:
            raise ValueError(f"rate limit: at most {limits.per_second} actions per second")
        if grant.count >= limits.per_session:
            raise ValueError(f"session cap: at most {limits.per_session} actions per share; "
                             "ask the person to share again")
        grant.times.append(now)
        grant.count += 1

    async def action(self, conv_id: str, agent: str, action: ControlAction):
        share, device = self.target(conv_id)
        grant = self.grants.get(share.share_id)
        if not grant or grant.status != "active":
            raise ValueError(f"agent control was revoked ({grant.reason})" if grant and grant.reason
                             else "agent control is not granted; call screen_control_request first")
        if grant.holder not in (None, agent):
            raise ValueError(f"agent control was granted to {grant.holder}")
        if not share.frames:
            raise ValueError("no frame yet; call screen_frame first")
        cmd = command(action, share.frames[-1], self.limits.max_text, device.get("os", ""))
        self._spend(grant)
        await self._changed(share)  # viewers' badges show the live action count
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        result, settled = loop.create_future(), loop.create_future()
        self.waiters[request_id] = (device["id"], share.share_id, result)
        self.hub.snap_waiters[request_id] = (share, settled)
        try:
            try:
                async with asyncio.timeout(ACTION_TIMEOUT):
                    await device["socket"].send_json({"type": "action", "share_id": share.share_id,
                                                       "request_id": request_id, "action": cmd})
                    answer = await result
            except (TimeoutError, asyncio.CancelledError):
                if asyncio.current_task().cancelling():
                    raise
                await self._audit(grant, share.conv_id, agent, f"{describe(cmd)} (unconfirmed)")
                if share.status != "active":
                    raise ValueError("screen sharing has stopped") from None
                raise ValueError("the sharing computer did not answer the action") from None
            if not answer.get("ok"):
                error = str(answer.get("error"))[:200]
                if answer.get("started"):  # partly injected before it stopped: still audited
                    entry = f"{describe(cmd)} (interrupted: {error[:80]})"
                    await self._audit(grant, share.conv_id, agent, entry)
                    raise ValueError(f"the action was interrupted: {error}")
                raise ValueError(f"the computer refused the action: {error}")
            await self._audit(grant, share.conv_id, agent, describe(cmd))
            try:
                async with asyncio.timeout(FRAME_TIMEOUT):
                    return share, await settled, cmd, False
            except (TimeoutError, asyncio.CancelledError, ValueError):  # ValueError: capture failed
                if asyncio.current_task().cancelling() or not share.frames:
                    raise ValueError("the action ran but no frame followed; call screen_frame") from None
                return share, share.frames[-1], cmd, True
        finally:
            self.waiters.pop(request_id, None)
            self.hub.snap_waiters.pop(request_id, None)
            for future in (result, settled):
                if not future.done():
                    future.cancel()

    async def _audit(self, grant: Grant, conv_id: str, agent: str, entry: str) -> None:
        record(self.hub.runtime.db, grant.share_id, conv_id, agent, entry)
        grant.last_actor = agent
        grant.audit_count += 1
        last = grant.audit[-1] if grant.audit else None
        if last and last[0] == agent and plain_move(last[1]) and plain_move(entry):
            last[1], last[2] = entry, last[2] + 1  # coalesce pointer moves
        else:
            grant.audit.append([agent, entry, 1])
        # Late entries (after a revoke or the share's end) post at once rather than by timer.
        if grant.audit_count >= AUDIT_BATCH or self.grants.get(grant.share_id) is not grant \
                or grant.status == "revoked":
            await self.flush(grant, conv_id)
        elif grant.flusher is None:
            grant.flusher = asyncio.create_task(self._flush_later(grant, conv_id))

    async def _flush_later(self, grant: Grant, conv_id: str) -> None:
        await self.sleep(AUDIT_DELAY)
        grant.flusher = None
        await self.flush(grant, conv_id)

    async def flush(self, grant: Grant, conv_id: str) -> None:
        flusher, grant.flusher = grant.flusher, None
        if flusher and flusher is not asyncio.current_task():
            flusher.cancel()
        try:
            message = publish(self.hub.runtime.db, grant.share_id)
        except Exception:
            if self.grants.get(grant.share_id) is grant and grant.status == "active":
                grant.flusher = asyncio.create_task(self._flush_later(grant, conv_id))
            raise
        if message:
            grant.audit, grant.audit_count = [], 0
            await self.hub.runtime.broadcast(
                conv_id, MessageEvent(message=MessageResponse.model_validate(message)))

    async def _note(self, conv_id: str, text: str) -> None:
        # Audit notes inform people; they deliberately wake no process.
        await self.hub.runtime.post_message(conv_id, "system", "system", text)

    async def _changed(self, share) -> None:
        device = self.hub.devices.get(share.device_id)
        if device and self.hub.shares.get(share.conv_id) is share:
            await self.hub._line_event(share.conv_id, self.hub._share_view(share, device))
