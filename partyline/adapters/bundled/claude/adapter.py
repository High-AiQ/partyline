"""Private Claude Code adapter; tails the CLI's JSONL transcript."""

import asyncio
import contextlib
import glob
import json
import os
import shlex

from partyline.adapters.base import Adapter as BaseAdapter
from partyline.adapters.compaction import is_compaction_record

# How much of a paste is used to recognise it again, and the shortest paste
# worth recognising. A wake carrying only a line or two is not distinctive
# enough to name a session by, so it is never used as evidence.
MARKER_LENGTH = 400
MARKER_MINIMUM = 80

# A session that recorded our briefing recorded it near the top. Bounding the
# scan keeps a stranger's multi-megabyte transcript from being read in full on
# every poll.
SCAN_BYTES = 512 * 1024


class PartylineAdapter(BaseAdapter):
    kind = "claude"

    # Transcripts a live attachment has adopted, and the discovery it holds
    # from briefing through claim, so two adapters cannot evaluate the same
    # unclaimed candidates at once.
    _CLAIMED: set[str] = set()
    _DISCOVERY = asyncio.Lock()

    _transcript: str = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Everything this adapter has written into its pty. Nothing else
        # writes there, so a transcript that recorded one of these is ours.
        self._pastes: list[str] = []

    def _note_paste(self, text: str) -> None:
        marker = " ".join(text.split())[:MARKER_LENGTH]
        if len(marker) >= MARKER_MINIMUM and marker not in self._pastes:
            self._pastes.append(marker)

    async def deliver(self, messages: list[dict]):
        """Remember the wake before it is typed.

        A resumed attachment gets no briefing, so its first delivery is the
        first thing that can identify its session. Recording the digest
        before the keys are written means a CLI that records it instantly
        cannot beat us to it.
        """
        self._note_paste(self.format_digest(messages))
        await super().deliver(messages)

    async def stop(self):
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
        ready.

        Only a write at or after our spawn tells the two apart, and the
        comparison takes no allowance: the file's mtime and ``spawned_at``
        are both this host's clock, so a second of slack buys nothing and
        admits the previous process's last write as proof of the new one.
        """
        if not self.resume:
            return True
        try:
            return os.path.getmtime(path) >= self.spawned_at
        except OSError:
            return False

    def _recorded_our_paste(self, path: str) -> bool:
        """Whether this transcript recorded something we typed into our pty.

        Timing cannot tell two same-directory sessions apart. A CLI that
        self-updates opens its session late — possibly after an attachment
        that started after us — so neither session-creation order nor spawn
        order survives the very case this adapter exists to handle (found
        reviewing #124, twice). The briefing is the one signal we control:
        we wrote it into this pty and nothing else did, so a transcript that
        recorded it is ours by construction rather than by inference. A
        resumed attachment has no briefing, so its first wake serves the same
        purpose: the fresh session claims itself on the next delivery.
        """
        if not self._pastes:
            return False
        try:
            with open(path, encoding="utf-8", errors="replace") as file:
                scanned = 0
                for line in file:
                    scanned += len(line)
                    if scanned > SCAN_BYTES:
                        return False
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("cwd") and record["cwd"] != self.att["cwd"]:
                        return False
                    if record.get("type") != "user":
                        continue
                    content = (record.get("message") or {}).get("content")
                    if not isinstance(content, str):
                        continue
                    flat = " ".join(content.split())
                    if any(marker in flat for marker in self._pastes):
                        return True
        except OSError:
            return False
        return False

    def _find_transcript(self) -> str | None:
        """The pinned transcript, or the session the CLI actually opened.

        ``build_command`` pins the session id so the transcript's name is
        known before the CLI writes it — but the process partyline spawns is
        not always the process that runs. A ``claude update`` at attach makes
        the CLI re-exec itself with a normalized argv, dropping the pin and
        opening a randomly-named session instead (2026-08-24: opus attached
        this way and could not speak for 42 minutes).

        A resumed attachment has nothing to match until its first wake
        arrives, and then matches on that. Until then it waits rather than
        guessing: a wrong guess trades a mute attachment for one speaking
        under another process's name.
        """
        if hits := glob.glob(self.transcript_glob()):
            if self._pinned_is_ours(hits[0]):
                self._transcript = hits[0]
                return hits[0]
        for path in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
            if path in self._CLAIMED or not self._recorded_our_paste(path):
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
                self._note_paste(self.briefing())
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
        # One fresh attachment resolves at a time, from briefing to claim:
        # matching is by content, so interleaving cannot mispair sessions,
        # but serializing keeps two adapters from racing for one candidate.
        # A resume stays out of the lock — it waits for its first wake, which
        # may be many minutes away, and must not hold the line shut.
        async with (contextlib.nullcontext() if self.resume else self._DISCOVERY):
            if not self.resume:
                self._note_paste(self.briefing())
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
