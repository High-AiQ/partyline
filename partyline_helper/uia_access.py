"""Local, independent window consent and read-only snapshot lifecycle."""
import asyncio
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .prompt_processes import run as run_prompt

from .uia_process import read
from .timing import Timing
from .window_events import WindowEvents
from partyline.file_events import Changes
from .uia_gate import DispatchGate
from .uia_window_identity import live, unmark

MAX_WALKS = 4
MAX_RETAINED_IDS = 120_000  # match the server tree cap, including IDs merged by filtered reads


def select_window(platform=sys.platform, run=run_prompt):
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
        self.runtimes = {}  # runtime id -> the element id an event from it belongs to
        self.listed = {}  # element id -> the event counter when the read that listed it began
        self.epoch = None  # snapshot ID of the walk whose IDs are valid; parts of one walk share it
        self.walks = {}  # cursor -> the unread rest of that walk
        self.event_status = None
        self.event_counter = None
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
        self.runtimes, self.listed = {}, {}

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
            if grant.get("marker") and not getattr(self, "preserve_update", False):
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
        timing = Timing()
        with timing.phase("read_ms"):
            result = await self._snapshot(options, timing)
        result.setdefault("timing", {}).update(timing.values)
        return result

    async def _snapshot(self, options, timing):
        """A full read resets IDs; a filtered read only adds live targets to the current ID set."""
        if self.platform != "win32":
            return {"elements_unavailable": "not Windows"}
        grant, generation = self.grant, self.generation
        status = self.event_status() if self.event_status else {}
        counter = status.get("event_counter")
        cursor = (options or {}).get("cursor")
        state = self.walks.get(cursor) if cursor else None
        if cursor and self.event_counter != counter and not (options or {}).get("tolerate_events"):
            return {"elements_unavailable": "tree inconsistent: event during continuation; refresh"}
        if cursor and state is None:
            return {"elements_unavailable": "cursor expired; start a new snapshot"}
        scoped = bool((options or {}).get("query_scope"))
        if not cursor and not scoped and not (options or {}).get("inspect"):
            self.forget()
            self.event_counter = counter
        if not grant:
            return {"elements_unavailable": self.unavailable}
        with timing.phase("window_check_ms"):
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
        queued = timing.clock()
        def reader(*args, **kwargs):
            timing.values["worker_queue_ms"] = timing.elapsed(queued)
            return self.reader(*args, **kwargs)
        if (options or {}).get("inspect"):
            target = options["inspect"]
            result = await asyncio.to_thread(reader, grant["hwnd"], probe={
                "id": target, "path": self.paths.get(target)})
        elif (options or {}).get("query_scope"):
            result = await asyncio.to_thread(reader, grant["hwnd"], frame, query=options["query_scope"])
        else:
            result = await asyncio.to_thread(reader, grant["hwnd"], frame, state, self.deep)
        if self.event_status:
            result.update(self.event_status(), captured_event_counter=counter)
        if generation != self.generation or self.grant is not grant:
            return {"elements_unavailable": "consent revoked"}
        with timing.phase("window_check_ms"):
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
            self.keep(result, cursor, scoped=scoped, counter=counter)
            result.update(window_title=grant["title"], process_name=grant["process"])
        elif result.get("elements_unavailable") == "timeout" and state is None:
            self.deep = False  # the one-call prefetch outran the budget: read per parent from now on
        return result

    def keep(self, result, cursor, scoped=False, counter=None):
        """Remember every part's IDs and paths until a new snapshot starts; hand back the next cursor."""
        if not scoped:
            if not cursor:
                self.epoch = result.get("snapshot_id")
            result["snapshot_id"] = self.epoch
        for item in result["elements"]:
            if "id" in item:
                self.listed[item["id"]] = counter
                self.elements[item["id"]] = {"id": item["id"], "control_type": item.get("control_type"),
                                             "name": item.get("name")}
        self.paths.update(result.pop("paths", {}))
        self.runtimes.update((tuple(runtime), ident) for runtime, ident in result.pop("runtimes", ()))
        while len(self.runtimes) > 2 * MAX_RETAINED_IDS:
            del self.runtimes[next(iter(self.runtimes))]
        while len(self.elements) > MAX_RETAINED_IDS:
            oldest = next(iter(self.elements))
            self.elements.pop(oldest)
            self.paths.pop(oldest, None)
            self.listed.pop(oldest, None)
        if rest := result.pop("state", None):
            token = uuid.uuid4().hex[:12]
            self.walks[token] = rest
            while len(self.walks) > MAX_WALKS:
                del self.walks[next(iter(self.walks))]
            result["next_cursor"] = token

    def event_sources(self, since):
        """The listed elements events after counter `since` came from, each with its listed ancestors.

        A chain is `[id, parent, ...]`, nearest first, from the child-index paths of the reads kept.
        `unsure` names sources whose chain may be stale: an ancestor, or an event with no known or
        listed sender, came after the source was listed, so children may have moved. `unplaced`
        counts events whose sender was never listed.
        """
        state = getattr(self, "event_state", None)
        if state is None:
            return None
        raw = state.sources_since(since)
        ids, unplaced = set(), int(raw["unplaced"])
        for runtime in raw["sources"]:
            if ident := self.runtimes.get(runtime):
                ids.add(ident)
            else:
                unplaced += 1
        by_path = {tuple(path): ident for ident, path in self.paths.items()}
        latest, blind = state.latest()
        last = {}
        for runtime, count in latest.items():
            if ident := self.runtimes.get(runtime):
                last[ident] = max(last.get(ident, 0), count)
            else:
                blind = max(blind, count)  # a sender no read listed could have moved anything
        chains, unsure = [], []
        for ident in sorted(ids):
            path = self.paths.get(ident) or []
            chain = [ident, *(by_path[tuple(path[:end])] for end in range(len(path) - 1, -1, -1)
                              if tuple(path[:end]) in by_path)]
            chains.append(chain)
            listed = self.listed.get(ident)
            if listed is None or blind > listed or any(last.get(above, 0) > listed for above in chain[1:]):
                unsure.append(ident)
        return {"ids": chains, "unsure": unsure, "unplaced": unplaced, "overflow": raw["overflow"]}

    async def watch(self):
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
