"""Docker workloads: what the host daemon runs, seen and attributed by line.

Containers belong to the daemon, not to any attachment's cgroup, so no CLI
memory budget bounds them. A line that holds the docker grant is told to label
what it starts (``partyline.conversation`` / ``partyline.attachment``, handed to
its processes as ``PARTYLINE_DOCKER_LABELS``); this module lists the daemon's
containers on a slow cadence, attributes them by label, flags running ones with
no RAM cap, names the survivors of a closed line, and stops one by id for its
owner. It never removes a container: outputs and shared services stay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from urllib.parse import quote

from fastapi import HTTPException

from . import docker_api, docker_relay
from .hierarchy import descendants
from .system_notice import post_system_notice

logger = logging.getLogger(__name__)
LABEL_CONVERSATION = "partyline.conversation"
LABEL_ATTACHMENT = "partyline.attachment"
INTERVAL = 15.0
NOTICE_WINDOW = 600.0
LIVE = ("starting", "running")
ID = re.compile(r"[0-9a-f]{12,64}")
BUDGET_WARNING = ("daemon work runs outside every attachment's memory budget and the write fence: "
                  "a container is bounded only by limits set on it")


def label_env(att: dict) -> str:
    """``PARTYLINE_DOCKER_LABELS``: ``key=value`` words a launcher passes as ``--label``."""
    return f"{LABEL_CONVERSATION}={att['conv_id']} {LABEL_ATTACHMENT}={att.get('id', '')}"


def _used(stats) -> int | None:
    memory = (stats or {}).get("memory_stats") or {}
    if memory.get("usage") is None:
        return None
    return max(0, memory["usage"] - ((memory.get("stats") or {}).get("inactive_file") or 0))


async def _describe(item: dict, gate: asyncio.Semaphore) -> dict:
    labels = item.get("Labels") or {}
    running = item.get("State") == "running"
    limit = used = None
    if running:
        async with gate:
            try:
                status, inspected = await docker_api.request("GET", f"/containers/{item['Id']}/json")
                if status == 200 and inspected:
                    limit = (inspected.get("HostConfig") or {}).get("Memory")
                status, stats = await docker_api.request(
                    "GET", f"/containers/{item['Id']}/stats?stream=false&one-shot=true")
                used = _used(stats) if status == 200 else None
            except (OSError, TimeoutError):
                pass
    return {"id": item["Id"], "name": ((item.get("Names") or ["?"])[0]).lstrip("/"),
            "image": item.get("Image"), "state": item.get("State"), "status": item.get("Status"),
            "conversation_id": labels.get(LABEL_CONVERSATION), "attachment_id": labels.get(LABEL_ATTACHMENT),
            "memory_limit_bytes": limit or None, "memory_used_bytes": used,
            "uncapped": running and limit == 0}


class Inventory:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._at = float("-inf")
        self.containers: list[dict] = []
        self.sampled_at: float | None = None
        self.error: str | None = None

    async def sample(self, runtime, *, force: bool = False) -> bool:
        """Refresh at most every ``INTERVAL`` s, and only while a docker grant exists."""
        if not force and self._clock() - self._at < INTERVAL:
            return False
        self._at = self._clock()
        if not await asyncio.to_thread(docker_relay.any_grant, runtime.db):
            self.containers, self.sampled_at, self.error = [], None, None
            return False
        try:
            status, items = await docker_api.request("GET", "/containers/json?all=1")
            if status != 200 or not isinstance(items, list):
                raise OSError(f"docker daemon answered {status} to the container list")
            gate = asyncio.Semaphore(4)
            self.containers = await asyncio.gather(*(_describe(item, gate) for item in items))
            self.error = None
        except (OSError, TimeoutError) as exc:
            self.error = str(exc) or type(exc).__name__
            logger.warning("docker workloads: cannot list containers: %s", self.error)
        self.sampled_at = time.time()
        return True

    def summary(self) -> dict | None:
        if self.sampled_at is None:
            return None
        running = [c for c in self.containers if c["state"] == "running"]
        used = [c["memory_used_bytes"] for c in running if c["memory_used_bytes"] is not None]
        return {"running": len(running), "memory_used_bytes": sum(used) if used else None,
                "uncapped": sum(c["uncapped"] for c in running),
                "unattributed": sum(c["conversation_id"] is None for c in running),
                "sampled_at": self.sampled_at}

    def view(self, db, visible: set[str] | None) -> dict:
        """Containers with their line named; ``visible`` limits a machine to its own subtree."""
        rows = []
        for c in self.containers:
            if visible is not None and c["conversation_id"] not in visible:
                continue
            line = db.get_conversation(c["conversation_id"]) if c["conversation_id"] else None
            rows.append({**c, "line": line["name"] if line else None,
                         "attribution": "attributed" if c["conversation_id"] else "unattributed"})
        return {"enabled": self.sampled_at is not None, "sampled_at": self.sampled_at,
                "error": self.error, "containers": rows}


inventory = Inventory()
_noticed: dict[str, tuple[frozenset, float]] = {}


def _line(c: dict) -> str:
    limit = "no RAM cap" if c["uncapped"] else f"{(c['memory_limit_bytes'] or 0) / 1024**3:.1f} GB cap"
    return f"{c['name']} ({c['id'][:12]}, {limit})"


async def announce_survivors(runtime, conv_id: str) -> None:
    """After a detach left a line with no live process: name its containers still running."""
    try:
        if any(a["status"] in LIVE for a in runtime.db.list_attachments(conv_id)) \
                or not await asyncio.to_thread(docker_relay.any_grant, runtime.db):
            return
        filters = json.dumps({"label": [f"{LABEL_CONVERSATION}={conv_id}"], "status": ["running"]})
        status, items = await docker_api.request("GET", f"/containers/json?filters={quote(filters)}")
        if status != 200 or not items:
            return
        found = await asyncio.gather(*(_describe(item, asyncio.Semaphore(4)) for item in items))
        ids = frozenset(c["id"] for c in found)
        before = _noticed.get(conv_id)
        if before is not None and before[0] == ids and time.monotonic() - before[1] < NOTICE_WINDOW:
            return
        _noticed[conv_id] = (ids, time.monotonic())
        await post_system_notice(
            runtime, conv_id,
            "⚠ docker containers from this line are still running with no process attached: "
            + ", ".join(_line(c) for c in found)
            + " — stop one with POST /api/docker-workloads/<id>/stop (it is stopped, never removed)")
    except Exception:
        logger.exception("docker workloads: survivor check for %s failed", conv_id)


async def stop_owned(runtime, principal, ident: str) -> dict:
    """Stop one container by id: a person may stop any; a process only its line's own or below."""
    ident = ident.lower()
    if not ID.fullmatch(ident):
        raise HTTPException(400, "name the container by its id (12-64 hex characters), never by name")
    try:
        status, info = await docker_api.request("GET", f"/containers/{ident}/json")
        if status != 200 or not isinstance(info, dict) or not str(info.get("Id", "")).startswith(ident):
            raise HTTPException(404, f"no container with id {ident}")
        owner = ((info.get("Config") or {}).get("Labels") or {}).get(LABEL_CONVERSATION)
        if principal.kind == "machine":
            home = principal.conv_id
            mine = {home, *descendants(runtime.db, home)} if home else set()
            if owner not in mine:
                raise HTTPException(
                    403, "only a person may stop a container this line (or one under it) did not start")
        status, _body = await docker_api.request("POST", f"/containers/{info['Id']}/stop?t=10", timeout=30.0)
    except (OSError, TimeoutError) as exc:
        raise HTTPException(502, f"cannot reach the docker daemon: {exc}") from exc
    if status not in (204, 304):
        raise HTTPException(502, f"docker daemon answered {status} to the stop")
    name = ((info.get("Name") or "").lstrip("/")) or info["Id"][:12]
    if owner and runtime.db.get_conversation(owner):
        await post_system_notice(
            runtime, owner,
            f"⏹ container {name} ({info['Id'][:12]}) stopped by {principal.name} (stopped, not removed)")
    await inventory.sample(runtime, force=True)
    return {"ok": True, "id": info["Id"], "name": name, "was_running": status == 204}
