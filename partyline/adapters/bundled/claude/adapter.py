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


def _stamp(iso_ts) -> float | None:
    """When a record was written, or None if it carries no usable stamp."""
    try:
        return datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class PartylineAdapter(BaseAdapter):
    kind = "claude"

    # Session ids partyline pinned for live attachments, and transcripts a
    # live attachment has adopted. Both keep one adapter's discovery from
    # latching onto another's transcript and reposting its speech under the
    # wrong handle.
    _PINNED: set[str] = set()
    _CLAIMED: set[str] = set()

    _transcript: str = ""

    async def stop(self):
        self._PINNED.discard(self.att["id"])
        self._CLAIMED.discard(self._transcript)
        await super().stop()

    def build_command(self) -> list[str]:
        # Reserved before the process exists: a neighbour attachment starting
        # in the same second must not adopt the session this one pinned.
        self._PINNED.add(self.att["id"])
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

    def _adoptable(self, path: str) -> bool:
        """Whether an unpinned transcript is this process's own session.

        Two properties identify it and exclude every neighbour: the records
        name our working directory, and the session's first stamped record
        was written after we spawned. A CLI the user runs by hand in the same
        directory fails the second test on its own history, and another
        attachment's session fails the ``_PINNED`` check before we look.
        """
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in self._PINNED and stem != self.att["id"]:
            return False
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
                            return False
                        cwd_seen = True
                    if (stamp := _stamp(record.get("timestamp"))) is not None:
                        return cwd_seen and stamp >= self.spawned_at - 5
        except OSError:
            return False
        return False

    def _find_transcript(self) -> str | None:
        """The pinned transcript, or the session the CLI actually opened.

        ``build_command`` pins the session id so the transcript's name is
        known before the CLI writes it — but the process partyline spawns is
        not always the process that runs. A ``claude update`` at attach makes
        the CLI re-exec itself with a normalized argv, dropping the pin and
        opening a randomly-named session instead; the pinned glob then never
        matches anything (2026-08-24: opus attached this way and could not
        speak for 42 minutes). Adoption by cwd and spawn time recovers the
        session the CLI chose, whatever it ended up called.
        """
        if hits := glob.glob(self.transcript_glob()):
            self._transcript = hits[0]
            return hits[0]
        unpinned = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
        for path in sorted(unpinned, key=os.path.getmtime, reverse=True):
            if path in self._CLAIMED or not self._adoptable(path):
                continue
            self._CLAIMED.add(path)
            self._transcript = path
            return path
        return None

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
            if path := self._find_transcript():
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
