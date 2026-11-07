"""Local tool adapters: where each tool's add-on listens, what it may be asked, and the loopback client.

The add-on writes `<tool>-relay.json` (port, secret) next to helper.json and listens on 127.0.0.1 only.
Only the helper reads that file; the server never sees the secret or the port.
"""
import asyncio
import http.client
import json
import re
from dataclasses import dataclass

from .config import config_path

MAX_REPLY = 1024 * 1024
ENDED = {"blender": "app", "lease": "lease"}  # the add-on says why a session ended; "app" = its End button


@dataclass(frozen=True)
class ToolSpec:
    label: str
    discovery: str
    ops: tuple
    missing: str


SPECS = {
    "blender": ToolSpec("Blender", "blender-relay.json", ("exec", "scene_info"),
                        "no Blender add-on found: enable Partyline Relay in Blender and try again"),
}


class AddonError(Exception):
    """The add-on is missing, unreachable or answered with something unusable."""


class AddonClient:
    def __init__(self, spec, directory=None, connect=http.client.HTTPConnection):
        self.spec = spec
        self.directory = directory or config_path().parent
        self.connect = connect

    def _discover(self):
        try:
            data = json.loads((self.directory / self.spec.discovery).read_text())
            port, secret = data["port"], data["secret"]
        except (OSError, ValueError, KeyError, TypeError):
            raise AddonError(self.spec.missing) from None
        if type(port) is not int or not 0 < port < 65536 or not isinstance(secret, str) or not secret:
            raise AddonError(self.spec.missing)
        return port, secret, data

    def request(self, method, path, body=None, timeout=10):
        """(status, json) from the add-on; the Host header is always 127.0.0.1:<port>."""
        port, secret, _ = self._discover()
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Authorization": "Bearer " + secret}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        connection = self.connect("127.0.0.1", port, timeout=timeout)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_REPLY + 1)
            if len(raw) > MAX_REPLY:
                raise AddonError("the add-on's reply was too large")
            return response.status, (json.loads(raw) if raw else {})
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise AddonError(f"{self.spec.label} is not reachable ({exc.__class__.__name__})") from None
        finally:
            connection.close()

    async def ask(self, method, path, body=None, timeout=10):
        return await asyncio.to_thread(self.request, method, path, body, timeout)

    async def info(self):
        status, data = await self.ask("GET", "/status")
        if status != 200:
            raise AddonError(f"{self.spec.label} refused the connection (HTTP {status})")
        return data

    async def open_session(self, session_id, agent, checker):
        status, data = await self.ask("POST", "/session", {"id": session_id, "agent": agent,
                                                           "checker": checker}, timeout=30)
        if status != 200:
            raise AddonError(str(data.get("error") or f"{self.spec.label} refused the session"))
        return data

    async def renew(self, session_id):
        """None while the session lives; the reason string once it is gone (ended in the app or lapsed)."""
        status, data = await self.ask("POST", "/session/renew", {"id": session_id}, timeout=5)
        if status == 200:
            return None
        return ENDED.get(data.get("ended"), "unknown")

    async def close_session(self, session_id):
        await self.ask("POST", "/session/close", {"id": session_id}, timeout=5)

    async def call(self, session_id, call_id, op, args, timeout):
        status, data = await self.ask("POST", "/call", {"session": session_id, "call_id": call_id, "op": op,
                                                        "args": args, "timeout": timeout}, timeout + 4)
        if status == 409:
            return {"busy": True, "error": str(data.get("error") or f"{self.spec.label} is busy")}
        if status != 200:
            return {"error": str(data.get("error") or f"{self.spec.label} answered HTTP {status}")}
        return {"result": data}

    async def cancel(self, session_id, call_id):
        await self.ask("POST", "/cancel", {"session": session_id, "call_id": call_id}, timeout=5)


def spec_for(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name):
        return None
    return SPECS.get(name)
