"""Durable update pauses and event-driven release/setting pushes."""
import asyncio
import json
import time

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from partyline_helper import __version__
from partyline_helper.update_timing import SERVER_DEADLINE
from .helper_release import installer_info, parse, update_available
from .screen_audit import record
from .op_timing import pushed
from .screen_connections import notice
from .screen_grants import device_grants

PAUSED = {"status": "paused", "reason": "helper updating",
          "retry_hint": "Wait for window access resumed, then read fresh state before retrying actions."}


class HelperUpdating(Exception):
    def __init__(self, grant=None):
        self.grant = grant or {}


class AutoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class PublishedRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str


class UpdateStarted(BaseModel):
    type: Literal["helper_updating"]
    version: str = Field(max_length=40)


class UpdateRestored(BaseModel):
    type: Literal["helper_update_restored"]
    grants: list[str] = Field(max_length=1000)
    failed: bool = False


class HelperUpdates:
    def __init__(self, hub):
        self.hub, self.timers = hub, {}
        self.db = hub.runtime.db

    def start(self):
        for row in self.db._exec("SELECT device_id,deadline FROM screen_helper_updates").fetchall():
            self.arm(row["device_id"], row["deadline"])

    def close(self):
        for timer in self.timers.values():
            timer.cancel()
        self.timers.clear()

    def paused(self, ident):
        return self.db._exec("SELECT * FROM screen_helper_updates WHERE device_id=?", (ident,)).fetchone()

    def audit(self, ident, actor, detail):
        self.db._exec("INSERT INTO screen_helper_update_audit(device_id,actor,detail,created_at) "
                      "VALUES(?,?,?,?)", (ident, actor, detail, time.time()))

    def arm(self, ident, deadline):
        timer = self.timers.pop(ident, None)
        if timer:
            timer.cancel()
        # no-poll (b): one deadline for this update; failure never schedules a retry.
        self.timers[ident] = asyncio.get_running_loop().call_later(
            max(0, deadline - time.time()),
            lambda: asyncio.create_task(self.finish(ident, failed=True, expired=True)))

    def begin(self, device, version, previous):
        from .hierarchy import descendants
        from .screen_device_access import standing_lines
        lines = set(standing_lines(self.db, device))
        for grant in device_grants(self.db, device["id"]):
            lines.update({grant["conv_id"], *descendants(self.db, grant["conv_id"], include_archived=False)})
        deadline = time.time() + SERVER_DEADLINE
        self.db._exec("INSERT OR REPLACE INTO screen_helper_updates VALUES(?,?,?,?,?)",
                      (device["id"], version, previous, deadline, json.dumps(sorted(lines))))
        self.arm(device["id"], deadline)

    async def connected(self, device, hello):
        ident = device["id"]
        if hello.update_check and not hello.update_recovery:
            await pushed("screen", device["socket"].send_json({"type": "ping", "helper_update": {
                **installer_info(), "available": update_available(hello.helper_version)}}))
        row = self.db._exec("SELECT * FROM screen_helper_preferences WHERE device_id=?", (ident,)).fetchone()
        if row and row["pending"]:
            await pushed("screen",
                device["socket"].send_json({"type": "set_auto_update", "enabled": bool(row["enabled"])}))
        else:
            self.preference(ident, hello.auto_update, "helper connected")
        if self.paused(ident) or hello.update_recovery:
            pause = self.paused(ident)
            if pause:
                self.arm(ident, pause["deadline"])
            from .screen_window_grants import share_targets
            from .screen_device_access import standing_lines
            lines = share_targets(self.db, device["owner_id"], standing_lines=standing_lines(self.db, device))
            allowed = {row["line_id"]: row for row in lines}
            grants = [row for row in device_grants(self.db, ident) if pause and row["conv_id"] in allowed and
                      (not row["standing_access"] or allowed[row["conv_id"]]["standing_access"])]
            await pushed("screen",
                device["socket"].send_json({"type": "helper_update_restore", "grants": grants}))

    def preference(self, ident, enabled, actor):
        old = self.db._exec("SELECT enabled FROM screen_helper_preferences WHERE device_id=?",
                            (ident,)).fetchone()
        self.db._exec("INSERT INTO screen_helper_preferences VALUES(?,?,0) ON CONFLICT(device_id) "
                      "DO UPDATE SET enabled=excluded.enabled,pending=0", (ident, int(enabled)))
        if bool(old and old["enabled"]) != enabled:
            self.audit(ident, actor, f"auto_update={enabled}")

    async def receive(self, device, message):
        ident, kind = device["id"], message["type"]
        if kind == "auto_update_changed":
            body = AutoUpdate.model_validate({"enabled": message.get("enabled")})
            row = self.db._exec("SELECT * FROM screen_helper_preferences WHERE device_id=?",
                                (ident,)).fetchone()
            if row and row["pending"] and bool(row["enabled"]) != body.enabled:
                await pushed("screen",
                    device["socket"].send_json({"type": "set_auto_update", "enabled": bool(row["enabled"])}))
                return
            self.preference(ident, body.enabled, "helper")
        elif kind == "helper_updating":
            version = UpdateStarted.model_validate(message).version
            if version != __version__ or not parse(device["helper_version"]) or (
                    parse(version) <= parse(device["helper_version"])):
                raise ValueError("invalid update version")
            self.begin(device, version, device["helper_version"])
            self.audit(ident, "helper", f"updating to {version}")
            waiting = [*self.hub.elements.waiters.values(), *self.hub.standing_windows.waiters.values()]
            for device_id, future in waiting:
                if device_id == ident and not future.done():
                    future.set_exception(HelperUpdating())
            await pushed("screen", device["socket"].send_json({"type": "helper_update_paused"}))
        elif kind == "helper_update_restored":
            restored = UpdateRestored.model_validate(message)
            kept = restored.grants
            from .screen_window_grants import share_targets
            from .screen_device_access import standing_lines
            allowed = {row["line_id"]: row for row in share_targets(self.db, device["owner_id"],
                        standing_lines=standing_lines(self.db, device))}
            for row in device_grants(self.db, ident):
                if (row["id"] not in kept or row["conv_id"] not in allowed or
                        (row["standing_access"] and not allowed[row["conv_id"]]["standing_access"])):
                    await self.hub.window_grants.revoke(row["id"], reason="window closed")
                else:
                    self.hub.window_grants.known[row["id"]] = row
            pause = self.paused(ident)
            failed = (restored.failed or
                      (pause is not None and device["helper_version"] != pause["version"]))
            await self.finish(ident, failed=failed)
            await pushed("screen", device["socket"].send_json({"type": "helper_update_finished"}))
        elif kind == "helper_update_failed":
            await self.finish(ident, failed=True)
        await self.hub._device_event(device, True)

    async def finish(self, ident, failed=False, expired=False):
        pause = self.paused(ident)
        if not pause:
            return
        ended = expired or ident not in self.hub.devices
        if failed and ended:
            known = {key for key, row in self.hub.window_grants.known.items() if row["device_id"] == ident}
            for key in known | {row["id"] for row in device_grants(self.db, ident)}:
                await self.hub.window_grants.revoke(key, tell_helper=True, reason="helper update failed")
        self.db._exec("DELETE FROM screen_helper_updates WHERE device_id=?", (ident,))
        timer = self.timers.pop(ident, None)
        if timer:
            timer.cancel()
        text = (("helper update failed; window access ended" if ended else
                 "helper update failed; window access resumed where available") if failed else
                f"helper updated to {pause['version']}; window access resumed")
        self.audit(ident, "helper", text)
        for line in json.loads(pause["lines"]):
            record(self.db, "helper-update:" + ident, line, "system", text)
            await notice(self.hub, line, text)
        device = self.hub.devices.get(ident)
        if device:
            await self.hub._device_event(device, True)
        else:
            row = self.db._exec("SELECT id,owner_id FROM screen_devices WHERE id=?", (ident,)).fetchone()
            if row:
                await self.hub._device_event(dict(row), False)

    def standing_pause(self, conv_id):
        from .screen_device_access import standing_lines
        rows = self.db._exec("SELECT d.* FROM screen_devices d JOIN screen_helper_updates u "
                            "ON u.device_id=d.id JOIN screen_device_window_access a ON a.device_id=d.id "
                            "WHERE d.revoked_at IS NULL AND a.enabled=1").fetchall()
        for row in rows:
            if conv_id in standing_lines(self.db, dict(row)):
                raise HelperUpdating({"device_id": row["id"]})

    async def published(self):
        sent = 0
        for device in list(self.hub.devices.values()):
            try:
                await pushed("screen",
                    device["socket"].send_json({"type": "helper_release_published", "helper_update": {
                    **installer_info(), "available": update_available(device["helper_version"])}}))
                sent += 1
            except (OSError, RuntimeError):
                pass
        return sent


def router_for(runtime, hub, app):
    from .screen_helper_update_routes import router_for as build
    return build(runtime, hub, app)


MESSAGES = {"auto_update_changed", "helper_updating", "helper_update_restored", "helper_update_failed"}
