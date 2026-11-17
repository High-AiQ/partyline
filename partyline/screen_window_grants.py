"""The authenticated helper asks for live owner-visible targets and reports local consent."""
from collections import deque
from types import SimpleNamespace
from typing import Literal

from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .auth_guard import Principal
from .auth_store import user_by_id
from .machine_scope import visible_conversation_ids
from .screen_chrome_approval import ChromeApprovals
from .screen_closed_windows import ClosedWindows
from .screen_window_notices import announce, live_processes
from .preset_traits import match_preset
from .screen_grants import GRANTS
from .screen_grant_store import replace_grant
from .screen_device_access import standing_lines
from .op_timing import pushed

MESSAGES = ("list_share_targets", "window_grant", "window_revoked", "window_changed")


class TargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["list_share_targets"]
    request_id: str = Field(min_length=1, max_length=128)


class WindowRevoked(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["window_revoked"]
    grant_id: str = Field(min_length=1, max_length=128)
    reason: Literal["revoked by the person", "window closed", "replaced by another grant"] = Field(
        default="revoked by the person")


class WindowChanged(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["window_changed"]
    grant_id: str = Field(min_length=1, max_length=128)


class WindowGrantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["window_grant"]
    request_id: str = Field(min_length=1, max_length=128)
    grant_id: str = Field(min_length=1, max_length=128)
    line_id: str | None = Field(default=None, min_length=1, max_length=128)
    attachment_id: str | None = Field(default=None, min_length=1, max_length=128)  # helpers before 1.1.0
    targets_request_id: str = Field(min_length=1, max_length=128)
    hwnd: int = Field(gt=0)
    title: str = Field(max_length=500)
    process: str = Field(max_length=200)
    standing_access: bool = False


def share_targets(db, owner_id, *, offered=None, window_lines=True, standing_lines=()):
    """Every line the computer's owner can see, each with its live processes (maybe none).

    Helpers that predate line grants pick one process, so they are offered only lines that have one.
    """
    user = user_by_id(db, owner_id)
    if user is None:
        return []
    principal = Principal(kind="user", name=user["handle"], user_id=owner_id)
    visible = visible_conversation_ids(db, principal)
    presets = db.list_presets()
    groups = []
    for line in db.list_conversations():
        if visible is not None and line["id"] not in visible:
            continue
        processes = []
        for att in live_processes(db, line["id"]):
            if offered is not None:
                offered[att["id"]] = (line["id"], att["name"])
            preset = match_preset(att, presets)
            processes.append({"attachment_id": att["id"], "name": att["name"],
                              "preset": preset["title"] if preset else att["adapter"]})
        if processes or window_lines:
            groups.append({"line_id": line["id"], "line_name": line["name"],
                           "parent_id": line.get("parent_id"), "processes": processes,
                           "standing_access": line["id"] in standing_lines})
    return groups


class WindowGrants:
    def __init__(self, hub):
        self.hub = hub
        self.actions = {}
        self.offers = {}
        self.known = {}  # helper grants known on this connection, including rows removed by triggers
        self.closed = ClosedWindows()
        self.approvals = ChromeApprovals(hub)  # which of the grants wait on Chrome's Allow prompt

    def spend(self, grant):
        counter = self.actions.setdefault(grant["id"], SimpleNamespace(times=deque(), count=0))
        self.hub.control._spend(counter)

    def connected(self, device):
        current = self.hub.devices.get(device["id"])
        return (current is not None and current["socket"] is device["socket"] and
                getattr(device["socket"], "client_state", None) != WebSocketState.DISCONNECTED and
                getattr(device["socket"], "application_state", None) != WebSocketState.DISCONNECTED)

    async def changed(self, device_id):
        row = self.hub.runtime.db._exec(
            "SELECT owner_id FROM screen_devices WHERE id=?", (device_id,)).fetchone()
        if row is not None:
            await self.hub._device_event({"id": device_id, "owner_id": row["owner_id"]},
                                         device_id in self.hub.devices)

    async def from_helper(self, device, message):
        if not self.connected(device):
            return
        kind, ident = message.get("type"), message.get("request_id")
        if kind == "list_share_targets":
            try:
                TargetRequest.model_validate(message)
            except ValidationError:
                return
            offered = {}  # attachment id -> (line id, name), for helpers that still pick a process
            authorized = standing_lines(self.hub.runtime.db, device)
            lines = share_targets(self.hub.runtime.db, device["owner_id"], offered=offered,
                                  window_lines=bool(device.get("windows")), standing_lines=authorized)
            self.offers[device["id"]] = (device["socket"], ident, offered,
                                          {g["line_id"] for g in lines}, authorized)
            await pushed("screen", device["socket"].send_json(
                {"type": "share_targets", "request_id": ident, "lines": lines}))
            return
        if kind == "window_revoked":
            try:
                revoked = WindowRevoked.model_validate(message)
            except ValidationError:
                return
            entry = self.known.get(revoked.grant_id)
            if entry and entry["device_id"] == device["id"]:
                await self.revoke(revoked.grant_id, tell_helper=False, reason=revoked.reason)
            return
        if kind == "window_changed":
            try:
                event = WindowChanged.model_validate(message)
            except ValidationError:
                return
            entry = self.known.get(event.grant_id)
            if entry and entry["device_id"] == device["id"]:
                self.hub.elements.changed(event.grant_id)
            return
        response = {"type": "window_grant_result", "request_id": ident, "ok": False}
        try:
            body = WindowGrantMessage.model_validate(message)
            if body.standing_access and not device.get("window_access_enabled", False):
                raise ValueError("window access is off on the server")
            offer = self.offers.get(device["id"])
            if not offer or offer[:2] != (device["socket"], body.targets_request_id):
                raise ValueError("choose a line from the current picker")
            line_id, name = self.target_line(device, body, offer)
            line = self.hub.runtime.db.get_conversation(line_id)
            current_standing = standing_lines(self.hub.runtime.db, device)
            if body.standing_access and line_id not in current_standing:
                raise ValueError("the selected line is not owned by the paired person")
            if (line is None or line.get("archived_at") or line_id not in offer[3]
                    or body.grant_id in self.known):
                raise ValueError("the selected line is unavailable")
            old = replace_grant(self.hub.runtime.db, device["id"], line_id, body)
            self.offers.pop(device["id"], None)
            user = user_by_id(self.hub.runtime.db, device["owner_id"])
            entry = {"device_id": device["id"], "device_name": device["name"], "conv_id": line_id,
                     "line_name": line["name"], "title": body.title, "shared_by": user["handle"],
                     "standing_access": body.standing_access}
            self.known[body.grant_id] = entry
            response.update(ok=True, target={"line_id": line_id, "line_name": line["name"],
                                             **({"name": name} if name else {})})
            for grant_id in old:
                await self.revoke(grant_id, reason="replaced by another grant")
            await self.changed(device["id"])
        except (ValidationError, ValueError) as exc:
            response["error"] = (str(exc) if isinstance(exc, ValueError)
                                 else "the selected line is unavailable; choose a line from the picker")
        if self.connected(device):
            await pushed("screen", device["socket"].send_json(response))
            if response["ok"] and self.known.get(body.grant_id) is entry:
                # Let the helper activate its worker before the line's processes can use the grant.
                await announce(self.hub.runtime, entry, body.grant_id)

    def target_line(self, device, body, offer):
        """The line a helper chose: by line, or, for a helper before 1.1.0, by the process it picked."""
        if body.line_id:
            return body.line_id, None
        if body.attachment_id and not device.get("windows") and body.attachment_id in offer[2]:
            return offer[2][body.attachment_id]  # the name offered, even if the process has since gone
        raise ValueError("this helper cannot share a window with a line; update the Partyline helper")

    async def revoke(self, grant_id, tell_helper=True, *, reason="revoked by the person"):
        self.actions.pop(grant_id, None)
        if elements := getattr(self.hub, "elements", None):
            elements.end(grant_id)
        if snapshots := getattr(self.hub, "snapshots", None):
            snapshots.end(grant_id)
        entry = self.known.pop(grant_id, None)
        device_id = entry["device_id"] if entry else None
        if entry:
            self.remember_end(grant_id, entry, reason)
        self.hub.runtime.db._exec("DELETE FROM screen_line_window_grants WHERE id=?", (grant_id,))
        if entry:
            await announce(self.hub.runtime, entry, grant_id, reason)
        device = self.hub.devices.get(device_id)
        if device and tell_helper:
            try:
                await pushed("screen",
                        device["socket"].send_json({"type": "revoke_window", "grant_id": grant_id}))
            except (OSError, RuntimeError, WebSocketDisconnect):
                pass  # Server authorization is already gone, even if the helper disconnected.
        if device_id:
            await self.approvals.sync(device_id)
            await self.changed(device_id)

    def remember_end(self, grant_id, entry, reason):
        """A closed window is remembered so a later read names it; any other ending forgets the line's."""
        row = self.hub.runtime.db._exec(
            "SELECT g.process,d.owner_id FROM screen_line_window_grants g JOIN screen_devices d "
            "ON d.id=g.device_id WHERE g.id=?", (grant_id,)).fetchone()
        if reason == "window closed" and row:
            self.closed.remember(grant_id, entry["conv_id"], row["owner_id"], entry["title"], row["process"])
        else:
            self.closed.forget_line(entry["conv_id"])

    async def revoke_standing(self, device_id, *, tell_helper=False, lines=None):
        rows = self.hub.runtime.db._exec(
            "SELECT id,conv_id FROM screen_line_window_grants WHERE device_id=? AND standing_access=1",
            (device_id,)).fetchall()
        rows = [row for row in rows if lines is None or row["conv_id"] in lines]
        # Delete the complete affected set before any notification can yield.
        for row in rows:
            self.hub.runtime.db._exec("DELETE FROM screen_line_window_grants WHERE id=?", (row["id"],))
        for row in rows:
            await self.revoke(row["id"], tell_helper=tell_helper)

    async def expire(self):
        active = {row["id"] for row in self.hub.runtime.db._exec(GRANTS).fetchall()}
        for grant_id in list(self.known):
            if grant_id not in active:
                await self.revoke(grant_id)

    async def disconnected(self, device_id, *, reason="helper disconnected"):
        self.offers.pop(device_id, None)
        await self.approvals.sync(device_id)
        if reason == "helper disconnected" and self.hub.updates.paused(device_id):
            return
        for grant_id, entry in list(self.known.items()):
            if entry["device_id"] == device_id:
                await self.revoke(grant_id, tell_helper=False, reason=reason)
