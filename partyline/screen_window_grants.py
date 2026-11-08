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
from .preset_traits import match_preset
from .screen_grants import GRANTS
from .screen_grant_store import replace_grant

MESSAGES = ("list_share_targets", "window_grant", "window_revoked")


class TargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["list_share_targets"]
    request_id: str = Field(min_length=1, max_length=128)


class WindowRevoked(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["window_revoked"]
    grant_id: str = Field(min_length=1, max_length=128)


class WindowGrantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["window_grant"]
    request_id: str = Field(min_length=1, max_length=128)
    grant_id: str = Field(min_length=1, max_length=128)
    attachment_id: str
    targets_request_id: str = Field(min_length=1, max_length=128)
    hwnd: int = Field(gt=0)
    title: str = Field(max_length=500)
    process: str = Field(max_length=200)


def share_targets(db, owner_id, *, activations=None):
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
        for att in db.list_attachments(line["id"]):
            if att["status"] not in ("starting", "running"):
                continue
            if activations is not None:
                activations[att["id"]] = att["runtime_owner"]
            preset = match_preset(att, presets)
            processes.append({"attachment_id": att["id"], "name": att["name"],
                              "preset": preset["title"] if preset else att["adapter"]})
        if processes:
            groups.append({"line_id": line["id"], "line_name": line["name"], "processes": processes})
    return groups


class WindowGrants:
    def __init__(self, hub):
        self.hub = hub
        self.actions = {}
        self.offers = {}
        self.known = {}  # helper grants known on this connection, including rows removed by triggers

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
            activations = {}
            lines = share_targets(self.hub.runtime.db, device["owner_id"], activations=activations)
            self.offers[device["id"]] = (device["socket"], ident, activations)
            await device["socket"].send_json({"type": "share_targets", "request_id": ident, "lines": lines})
            return
        if kind == "window_revoked":
            try:
                grant_id = WindowRevoked.model_validate(message).grant_id
            except ValidationError:
                return
            if self.known.get(grant_id) == device["id"]:
                await self.revoke(grant_id, tell_helper=False)
            return
        response = {"type": "window_grant_result", "request_id": ident, "ok": False}
        try:
            body = WindowGrantMessage.model_validate(message)
            groups = share_targets(self.hub.runtime.db, device["owner_id"])
            offer = self.offers.get(device["id"])
            if not offer or offer[:2] != (device["socket"], body.targets_request_id):
                raise ValueError("choose a process from the current picker")
            matches = [(line, att) for line in groups for att in line["processes"]
                       if att["attachment_id"] == body.attachment_id and body.attachment_id in offer[2]]
            if len(matches) != 1 or body.grant_id in self.known:
                raise ValueError("the selected process has ended; choose a live attached process")
            line, att = matches[0]
            old = replace_grant(self.hub.runtime.db, device["id"], body, offer[2][body.attachment_id])
            self.offers.pop(device["id"], None)
            self.known[body.grant_id] = device["id"]
            response.update(ok=True, target={**att, "line_id": line["line_id"],
                                             "line_name": line["line_name"]})
            for grant_id in old:
                await self.revoke(grant_id)
            await self.changed(device["id"])
        except (ValidationError, ValueError):
            response["error"] = "the selected process is unavailable; choose a live attached process"
        if self.connected(device):
            await device["socket"].send_json(response)

    async def revoke(self, grant_id, tell_helper=True):
        self.actions.pop(grant_id, None)
        device_id = self.known.pop(grant_id, None)
        self.hub.runtime.db._exec("DELETE FROM screen_window_grants WHERE id=?", (grant_id,))
        device = self.hub.devices.get(device_id)
        if device and tell_helper:
            try:
                await device["socket"].send_json({"type": "revoke_window", "grant_id": grant_id})
            except (OSError, RuntimeError, WebSocketDisconnect):
                pass  # Server authorization is already gone, even if the helper disconnected.
        if device_id:
            await self.changed(device_id)

    async def expire(self):
        active = {row["id"] for row in self.hub.runtime.db._exec(GRANTS).fetchall()}
        for grant_id in list(self.known):
            if grant_id not in active:
                await self.revoke(grant_id)

    async def disconnected(self, device_id):
        self.offers.pop(device_id, None)
        for grant_id, owner in list(self.known.items()):
            if owner == device_id:
                await self.revoke(grant_id, tell_helper=False)
