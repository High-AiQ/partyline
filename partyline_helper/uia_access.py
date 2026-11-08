"""Local, independent window consent and read-only snapshot lifecycle."""
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .uia_process import read


def select_window(platform=sys.platform, run=subprocess.run):
    if platform != "win32":
        return None
    with tempfile.TemporaryDirectory(prefix="partyline-window-") as directory:
        path = str(Path(directory) / "selection.json")
        command = ([sys.executable, "uia-picker", path] if getattr(sys, "frozen", False) else
                   [sys.executable, "-m", "partyline_helper.uia_picker", path])
        try:
            run(command, timeout=65, check=True, creationflags=0x08000000)
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, subprocess.SubprocessError):
            return None


def available_windows(platform=sys.platform):
    if platform != "win32":
        return []
    from .uia_window_list import windows
    return windows()


class WindowAccess:
    def __init__(self, session, picker=select_window, list_windows=available_windows, reader=read,
                 platform=sys.platform):
        self.session, self.picker, self.list_windows, self.reader = session, picker, list_windows, reader
        self.platform, self.grant, self.generation = platform, None, 0
        self.unavailable = "not consented"
        self.picking = False

    async def check(self, grant):
        windows = await asyncio.to_thread(self.list_windows)
        if windows is None:
            return "secure desktop active"
        return (None if any(item["hwnd"] == grant["hwnd"] and item["pid"] == grant["pid"]
                            for item in windows) else "window closed")

    def revoke(self, reason="not consented"):
        grant = self.grant
        self.generation += 1
        self.grant = None
        self.unavailable = reason
        self.session.status.window_title = None
        if grant:
            self.session.status.changed()
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
            self.unavailable = "not consented"
            self.session.status.window_title = selected["title"]
            self.session.status.changed()
        finally:
            self.picking = False

    async def snapshot(self):
        if self.platform != "win32":
            return {"elements_unavailable": "not Windows"}
        grant, generation = self.grant, self.generation
        if not grant:
            return {"elements_unavailable": self.unavailable}
        reason = await self.check(grant)
        if generation != self.generation or self.grant is not grant:
            return {"elements_unavailable": "consent revoked"}
        if reason:
            if reason == "window closed":
                self.revoke(reason)
            return {"elements_unavailable": reason}
        frame = None
        share = self.session.share
        if share and self.session.accepted:
            frame = self.session.last_uia_frame
        result = await asyncio.to_thread(self.reader, grant["hwnd"], frame)
        if generation != self.generation or self.grant is not grant:
            return {"elements_unavailable": "consent revoked"}
        reason = await self.check(grant)
        if generation != self.generation or self.grant is not grant:
            return {"elements_unavailable": "consent revoked"}
        if reason:
            if reason == "window closed":
                self.revoke(reason)
            return {"elements_unavailable": reason}
        if "elements" in result:
            if (share is not self.session.share or not self.session.accepted
                    or frame != self.session.last_uia_frame):
                for element in result["elements"]:
                    element.pop("frame_bounds", None)
            result.update(window_title=grant["title"], process_name=grant["process"])
        return result

    async def watch(self, sleep=asyncio.sleep):
        while True:
            await sleep(1)
            grant = self.grant
            if grant and await self.check(grant) == "window closed" and self.grant is grant:
                self.revoke("window closed")
