"""Private Claude Code adapter; tails the CLI's JSONL transcript."""

import asyncio
import glob
import json
import os
import shlex
from datetime import datetime

from partyline.adapters.base import Adapter as BaseAdapter
from partyline.adapters.compaction import is_compaction_record

# How many records to read before deciding a transcript is not ours. The
# session's first stamped record arrives within the first few lines; the
# margin is for permission-mode and snapshot preamble.
PREAMBLE_RECORDS = 20

# The CLI stamps its own records, so its clock and ours can disagree a little.
# The adoption floor never reaches back past an earlier attachment's spawn, so
# this allowance cannot cross an ownership boundary.
CLOCK_SKEW = 5.0


def _stamp(iso_ts) -> float | None:
    """When a record was written, or None if it carries no usable stamp."""
    try:
        return datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class PartylineAdapter(BaseAdapter):
    kind = "claude"

    # When each live attachment spawned, and which transcripts they have
    # adopted. Together they keep one adapter's discovery from latching onto
    # another's session and reposting its speech under the wrong handle.
    _LIVE: dict[str, float] = {}
    _CLAIMED: set[str] = set()
    _DISCOVERY = asyncio.Lock()

    _transcript: str = ""

    async def start(self):
        await super().start()
        self._LIVE[self.att["id"]] = self.spawned_at

    async def stop(self):
        self._LIVE.pop(self.att["id"], None)
        self._CLAIMED.discard(self._transcript)
        await super().stop()

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["claude"]
        if self.resume:
            cmd += ["--resume", self.att["id"]]
        elif "--session-id" not in cmd:
            cmd += ["--session-id", self.att["id"]]
        hook_url = self.att.get("hook_url")
        if hook_url and "--settings" not in cmd:
            cmd += ["--settings", json.dumps(self._hook_settings(hook_url))]
        return cmd

    @staticmethod
    def _hook_settings(hook_url: str) -> dict:
        """Process-scoped harness receipts plus the existing attention hook.

        ``UserPromptSubmit`` / ``Stop`` are the paired turn boundaries. The
        same curl posts the event JSON; ``SubagentStop`` is omitted so a child
        finishing cannot clear the parent jack.
        """
        curl = (f"curl -s -m 5 -X POST {shlex.quote(hook_url)}"
                " -H 'Content-Type: application/json' --data-binary @-")
        handler = [{"hooks": [{"type": "command", "command": curl}]}]
        return {"hooks": {
            "Notification": handler,
            "UserPromptSubmit": handler,
            "Stop": handler,
        }}

    def transcript_glob(self) -> str:
        return os.path.expanduser(f"~/.claude/projects/*/{self.att['id']}.jsonl")

    def _pinned_is_ours(self, path: str) -> bool:
        """Whether the pinned transcript belongs to the process we spawned.

        A fresh attachment's pinned name is its own attachment id, so the
        file can only exist because this process created it. A resume pins a
        session file that already exists — it is the session being resumed —
        so its presence proves nothing: a CLI that re-execed without
        ``--resume`` opened a fresh session and left this one untouched, and
        tailing it would follow a file nobody writes, mute but reported
        ready. Only a write since our spawn tells the two apart.

        This is evidence, not proof. Once the updater drops the pin the new
        session has no structural link to the old one, and nothing in the
        transcript can restore it; the durable fix is upstream, in not
        letting a CLI self-update mid-attach.
        """
        if not self.resume:
            return True
        try:
            return os.path.getmtime(path) >= self.spawned_at - CLOCK_SKEW
        except OSError:
            return False

    def _session_start(self, path: str) -> float | None:
        """When this transcript's session opened, or None if it is not ours.

        Ours names our working directory. Its first stamped record dates the
        session; a file still holding only unstamped preamble was created
        just now, so its mtime dates it instead.
        """
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in self._LIVE and stem != self.att["id"]:
            return None
        cwd_seen = False
        try:
            with open(path, encoding="utf-8", errors="replace") as file:
                for _ in range(PREAMBLE_RECORDS):
                    line = file.readline()
                    if not line:
                        break
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if cwd := record.get("cwd"):
                        if cwd != self.att["cwd"]:
                            return None
                        cwd_seen = True
                    if (stamp := _stamp(record.get("timestamp"))) is not None:
                        return stamp if cwd_seen else None
            return os.path.getmtime(path) if cwd_seen else None
        except OSError:
            return None

    def _adoption_window(self) -> tuple[float, float]:
        """The span of session start times this attachment may claim.

        Sessions are told apart by when they opened. Ours cannot predate our
        spawn, and it cannot postdate the spawn of an attachment started
        after us — that later session belongs to that attachment. Without the
        upper bound, two CLIs started seconds apart in one directory adopt
        each other's transcripts and speak under each other's names, with
        claim order deciding which (found reviewing #124). The floor never
        reaches back past an attachment that started before us, so the skew
        allowance is dropped entirely once an attachment started before us:
        a session opened between their spawn and ours is theirs, and reaching
        back for it by a few seconds is exactly the swap being prevented.
        """
        others = [at for ident, at in self._LIVE.items() if ident != self.att["id"]]
        earlier = [at for at in others if at <= self.spawned_at]
        later = [at for at in others if at > self.spawned_at]
        floor = self.spawned_at if earlier else self.spawned_at - CLOCK_SKEW
        return floor, min(later) if later else float("inf")

    def _find_transcript(self) -> str | None:
        """The pinned transcript, or the session the CLI actually opened.

        ``build_command`` pins the session id so the transcript's name is
        known before the CLI writes it — but the process partyline spawns is
        not always the process that runs. A ``claude update`` at attach makes
        the CLI re-exec itself with a normalized argv, dropping the pin and
        opening a randomly-named session instead (2026-08-24: opus attached
        this way and could not speak for 42 minutes). Adoption by working
        directory and session start recovers the session the CLI chose,
        whatever it ended up called.
        """
        if hits := glob.glob(self.transcript_glob()):
            if self._pinned_is_ours(hits[0]):
                self._transcript = hits[0]
                return hits[0]
        floor, ceiling = self._adoption_window()
        unpinned = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
        started = {path: self._session_start(path) for path in unpinned
                   if path not in self._CLAIMED}
        eligible = {path: at for path, at in started.items()
                    if at is not None and floor <= at < ceiling}
        # Earliest first: the session nearest our own spawn is ours.
        for path in sorted(eligible, key=lambda path: eligible[path]):
            self._CLAIMED.add(path)
            self._transcript = path
            return path
        return None

    async def _discover(self) -> str | None:
        """Resolve this attachment's transcript, one adapter at a time.

        The adoption window already decides ownership by spawn order rather
        than by who claims first, so this lock is belt to that brace: it
        matches the codex adapter's discipline and removes the interleaving
        entirely rather than reasoning about it.
        """
        async with self._DISCOVERY:
            return self._find_transcript()

    async def _await_transcript(self) -> str | None:
        """Poll until this process's transcript appears, or the CLI dies.

        Giving up here used to end the adapter while the CLI kept running:
        the attachment stayed live and mentionable, its cursor kept
        advancing, and nothing it said could reach the line again. A CLI that
        is slow, updating, or re-execing is not a CLI that will never speak,
        so the 45s mark warns once and the search goes on for as long as the
        process is alive. Silence is never a verdict.
        """
        waited, warned = 0.0, False
        while self.alive():
            await asyncio.sleep(1.0)
            waited += 1.0
            if path := await self._discover():
                if warned:
                    await self.post(
                        "system", "system",
                        f"{self.att['name']}: transcript found after "
                        f"{int(waited)}s — the line is reachable again.",
                    )
                return path
            if self.resume:
                continue
            if waited in (12.0, 24.0):
                os.write(self.master, b"\r")
                await asyncio.sleep(1.0)
                await self.send_keys(self.briefing())
            elif waited > 45.0 and not warned:
                warned = True
                await self.post(
                    "system", "system",
                    f"{self.att['name']}: no transcript after 45s — still watching, "
                    f"but nothing it says can reach the line until one appears. "
                    f"If this persists, run the CLI manually once in "
                    f"{self.att['cwd']}, then re-attach.",
                )
        return None

    async def _run(self):
        await asyncio.sleep(5.0)
        if not self.alive():
            return
        if not self.resume:
            await self.send_keys(self.briefing())

        path = await self._await_transcript()
        if path is None:
            return

        seen: set[str] = set()

        async def handle(obj):
            if is_compaction_record("claude", obj):
                return
            if obj.get("isSidechain") or obj.get("type") != "assistant":
                return
            if not self._fresh(obj.get("timestamp")):
                return
            uid = obj.get("uuid")
            if uid and uid in seen:
                return
            if uid:
                seen.add(uid)
            content = (obj.get("message") or {}).get("content") or []
            texts = [block.get("text", "") for block in content
                     if isinstance(block, dict) and block.get("type") == "text"]
            body = "\n\n".join(text for text in texts if text.strip())
            if body.strip():
                await self.post(self.att["name"], "agent", body)

        await self._tail_jsonl(path, handle)
