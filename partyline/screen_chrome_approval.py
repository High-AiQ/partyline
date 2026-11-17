"""Show a line when Chrome waits for the person to click Allow in a window shared with it.

The helper reports which of its window grants wait on Chrome's own Allow prompt (`chrome_approval`). The
server shows each waiting grant on the line that owns it and clears the notice when the helper reports the
prompt answered, the grant ends, or the computer disconnects. Pushed on change only; nothing polls."""
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .op_timing import pushed
from .screen_grants import device_grants


class ChromeApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant_ids: list[str] = Field(default_factory=list, max_length=64)


class ChromeApprovals:
    def __init__(self, hub):
        self.hub = hub
        self.sent = {}  # device id -> {line id: the notices that line was last shown}

    def notices(self, device_id):
        """Line id -> the waiting windows right now: only Chrome windows of a connected computer."""
        device = self.hub.devices.get(device_id)
        waiting = device.get("approvals") if device else None
        found = {}
        for grant in device_grants(self.hub.runtime.db, device_id) if waiting else ():
            if grant["id"] in waiting and grant["process"].lower() == "chrome.exe":
                found.setdefault(grant["conv_id"], []).append(
                    {"grant_id": grant["id"], "title": grant["title"], "device_name": grant["device_name"]})
        return found

    async def receive(self, device, message):
        try:
            body = ChromeApproval.model_validate({"grant_ids": message.get("grant_ids", [])})
        except ValidationError:
            return  # a malformed report shows nothing rather than dropping the helper
        device["approvals"] = set(body.grant_ids)
        await self.sync(device["id"])

    async def sync(self, device_id):
        """Push the lines whose notice changed, including a line whose last notice just ended."""
        now, before = self.notices(device_id), self.sent.get(device_id, {})
        lines = sorted(now.keys() | before.keys())
        shown = {conv_id: self.current(conv_id) for conv_id in lines}
        if now:
            self.sent[device_id] = now
        else:
            self.sent.pop(device_id, None)
        for conv_id in lines:  # a line shows every computer's prompt, so one clearing keeps the others
            if self.current(conv_id) != shown[conv_id]:
                await self.push(conv_id, self.current(conv_id))

    def current(self, conv_id):
        return [item for lines in self.sent.values() for item in lines.get(conv_id, [])]

    async def push(self, conv_id, notices, sockets=None):
        message = {"type": "chrome_approval", "conv_id": conv_id, "notices": notices}
        for ws in list(sockets if sockets is not None else self.hub.runtime.sockets.get(conv_id, ())):
            try:
                await pushed("screen", ws.send_json(message))
            except Exception:
                pass  # chat's own send path decides whether a socket is dead

    async def send_current(self, ws, conv_id):
        """A tab opened mid-prompt learns of it at once."""
        if notices := self.current(conv_id):
            await self.push(conv_id, notices, [ws])
