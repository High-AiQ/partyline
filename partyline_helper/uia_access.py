"""Local, independent window consent and read-only snapshot lifecycle."""
import asyncio
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .uia_process import read
from .window_events import WindowEvents
from partyline.file_events import Changes
from .uia_gate import DispatchGate
from .uia_window_identity import live, unmark

MAX_WALKS = 4


def select_window(platform=sys.platform, run=subprocess.run):
    if platform != "win32":
        return None
    with tempfile.TemporaryDirectory(prefix="partyline-window-") as directory:
        path = str(Path(directory) / "selection.json")
        command = ([sys.executable, "uia-picker", path] if getattr(sys, "frozen", False) else
                   [sys.executable, "-m", "partyline_helper.uia_picker", path])
        try:
            run(command, timeout=65, check=True, creationflags=0x08000000)
            selection = json.loads(Path(path).read_text(encoding="utf-8"))
            return selection if selection.get("marker") else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None


def available_windows(platform=sys.platform):
    if platform != "win32":
        return []
    from .uia_window_list import windows
    return windows()


class WindowAccess:
    def __init__(self, session, picker=select_window, list_windows=available_windows, reader=read,
                 platform=sys.platform, on_revoke=None):
        self._changes = Changes()
        self.on_revoke = on_revoke
        self.session, self.picker, self.list_windows, self.reader = session, picker, list_windows, reader
        self.platform, self.grant, self.generation = platform, None, 0
        self.unavailable = "not consented"
        self.picking = False
        self.gate = DispatchGate()
        self.elements = {}
        self.paths = {}
        self.epoch = None  # snapshot ID of the walk whose IDs are valid; parts of one walk share it
        self.walks = {}  # cursor -> the unread rest of that walk
        self.deep = True  # prefetch the whole tree in one cache request until a read times out

    async def check(self, grant):
        windows = await asyncio.to_thread(self.list_windows)
        if windows is None:
            return "secure desktop active"
        found = any(item["hwnd"] == grant["hwnd"] and item["pid"] == grant["pid"] for item in windows)
        if found and grant.get("marker"):
            found = await asyncio.to_thread(live, grant)
        return None if found else "window closed"

    def forget(self):
        self.elements, self.paths, self.walks, self.epoch = {}, {}, {}, None

    def abandon_read(self):
        """Discard the read in flight; earlier parts' ids stay valid, since a late result is dropped."""
        self.generation += 1

    def revoke(self, reason="not consented"):
        grant = self.grant
        self.gate.invalidate()
        self.forget()
        self.generation += 1
        self.grant = None
        self.unavailable = reason
        self.session.status.window_title = None
        if grant:
            if grant.get("marker"):
                unmark(grant)
            self.session.status.changed()
            if self.on_revoke:
                self.on_revoke(reason)
            try:
                self.session.tools.audit.append("event", "window", "local", "window_read",
                                                f"revoked ({reason}): {grant['title']} ({grant['process']})")
            except OSError:
                pass  # revocation must succeed even if the audit disk failed

    async def choose(self):
        if self.picking:
            return
        self.picking = True
        generation = self.generation
        try:
            selected = await asyncio.to_thread(self.picker)
            if not selected or generation != self.generation:
                return
            if await self.check(selected) or generation != self.generation:
                return
            if self.grant:
                self.revoke("replaced")
            try:
                self.session.tools.audit.append("event", "window", "local", "window_read",
                                                f"granted: {selected['title']} ({selected['process']})")
            except OSError:
                return
            self.generation += 1
            self.grant = selected
            self._changes.notify()
            if getattr(self.session, "control", None) and self.session.control.granted:
                self.gate.grant()
            self.unavailable = "not consented"
            self.session.status.window_title = selected["title"]
            self.session.status.changed()
        finally:
            self.picking = False

    async def snapshot(self, options=None):
        """Read one part of the window. Without a cursor that starts a new snapshot and drops the old IDs."""
        if self.platform != "win32":
            return {"elements_unavailable": "not Windows"}
        grant, generation = self.grant, self.generation
        cursor = (options or {}).get("cursor")
        state = self.walks.get(cursor) if cursor else None
        if cursor and state is None:
            return {"elements_unavailable": "cursor expired; start a new snapshot"}
        if not cursor:
            self.forget()
        if not grant:
            return {"elements_unavailable": self.unavailable}
        reason = await self.check(grant)
        if generation != self.generation or self.grant is not grant:
            return {"elements_unavailable": "consent revoked"}
        if reason:
            if reason == "secure desktop active":
                self.gate.invalidate()
            if reason == "window closed":
                self.revoke(reason)
            return {"elements_unavailable": reason}
        frame = None
        share = self.session.share
        if share and self.session.accepted:
            frame = self.session.last_uia_frame
        result = await asyncio.to_thread(self.reader, grant["hwnd"], frame, state, self.deep)
        if generation != self.generation or self.grant is not grant:
            return {"elements_unavailable": "consent revoked"}
        reason = await self.check(grant)
        if generation != self.generation or self.grant is not grant:
            return {"elements_unavailable": "consent revoked"}
        if reason:
            if reason == "secure desktop active":
                self.gate.invalidate()
            if reason == "window closed":
                self.revoke(reason)
            return {"elements_unavailable": reason}
        if "elements" in result:
            if (share is not self.session.share or not self.session.accepted
                    or frame != self.session.last_uia_frame):
                for element in result["elements"]:
                    element.pop("frame_bounds", None)
            self.keep(result, cursor)
            result.update(window_title=grant["title"], process_name=grant["process"])
        elif result.get("elements_unavailable") == "timeout" and state is None:
            self.deep = False  # the one-call prefetch outran the budget: read per parent from now on
        return result

    def keep(self, result, cursor):
        """Remember every part's IDs and paths until a new snapshot starts; hand back the next cursor."""
        if not cursor:
            self.epoch = result.get("snapshot_id")
        result["snapshot_id"] = self.epoch
        for item in result["elements"]:
            if "id" in item:
                self.elements[item["id"]] = {"id": item["id"], "control_type": item.get("control_type"),
                                             "name": item.get("name")}
        self.paths.update(result.pop("paths", {}))
        if rest := result.pop("state", None):
            token = uuid.uuid4().hex[:12]
            self.walks[token] = rest
            while len(self.walks) > MAX_WALKS:
                del self.walks[next(iter(self.walks))]
            result["next_cursor"] = token

    async def watch(self, sleep=asyncio.sleep):
        async with WindowEvents(self._changes) as events:
            while True:
                grant = self.grant
                if grant:
                    reason = await self.check(grant)
                    if reason == "window closed" and self.grant is grant:
                        self.revoke(reason)
                    elif reason == "secure desktop active":
                        self.gate.invalidate()
                    elif not reason and self.gate.revoked.is_set() and getattr(self.session, "control", None):
                        if self.session.control.granted:
                            self.gate.grant()
                await events.wait()
