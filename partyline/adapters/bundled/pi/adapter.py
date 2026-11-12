"""Adapter for the `pi` coding agent.

`pi` accepts `--session-id` and `--session-dir`, so partyline pins both: the
transcript lands at a path nobody else can occupy, which makes discovery exact
rather than a guess based on timestamps. Chat output is read from that JSONL
transcript instead of from the screen, so replies arrive as clean text.
"""

from __future__ import annotations

import asyncio
import glob
import os

from partyline.adapters.events import watch_files

from partyline.adapters import Adapter
from partyline.adapters.compaction import is_compaction_record
from partyline.adapters.session_pin import pinned_session

SESSION_ROOT = os.path.expanduser("~/.partyline/sessions/pi")


class PartylineAdapter(Adapter):
    kind = "pi"
    jsonl_paste_receipts = True

    def session_dir(self) -> str:
        """One directory per attachment — the transcript cannot be ambiguous."""
        return os.path.join(SESSION_ROOT, self.att["id"])

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["pi"]
        if "--session-dir" not in cmd:
            cmd += ["--session-dir", self.session_dir()]
        if "--session-id" not in cmd:
            # Reusing the id on a resume reopens the same session, so the
            # process comes back with its full context.
            cmd += ["--session-id", pinned_session(self.att)]
        return cmd

    @watch_files(lambda self: [self.session_dir()])
    async def _run(self):
        os.makedirs(self.session_dir(), exist_ok=True)
        await asyncio.sleep(4.0)
        if not self.alive():
            return
        if not self.resume:
            await self.send_keys(self.briefing())

        started = self.event_time()
        path, waited = None, 0.0
        while path is None:
            # pi writes the transcript at startup, before the first turn.
            hits = sorted(glob.glob(os.path.join(self.session_dir(), "*.jsonl")),
                          key=os.path.getmtime, reverse=True)
            if hits:
                path = hits[0]
            elif not self.alive():
                return
            elif waited >= 45.0:
                await self.post(
                    "system", "system",
                    f"{self.att['name']}: no transcript after 45s — the CLI is probably "
                    f"showing a first-run or trust prompt. Run `pi` manually once in "
                    f"{self.att['cwd']}, then re-attach.",
                )
                return
            if path is None:
                await self.wait_for_change(max(0, 45.0 - waited))
                waited = self.event_time() - started

        seen: set[str] = set()

        async def handle(record):
            if is_compaction_record("pi", record):
                return
            if record.get("type") != "message":
                return
            if not self._fresh(record.get("timestamp")):
                return
            uid = record.get("id")
            if uid:
                if uid in seen:
                    return
                seen.add(uid)
            message = record.get("message") or {}
            if message.get("role") != "assistant":
                return
            # Reasoning blocks are deliberately dropped: only spoken text is chat.
            texts = [block.get("text", "") for block in message.get("content") or []
                     if isinstance(block, dict) and block.get("type") == "text"]
            body = "\n\n".join(t for t in texts if t.strip())
            if body.strip():
                await self.post(self.att["name"], "agent", body)

        await self._tail_jsonl(path, handle)
