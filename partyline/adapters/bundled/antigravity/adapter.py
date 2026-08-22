"""Adapter for Google's Antigravity CLI (`agy`).

`agy` creates its conversation id internally and accepts no caller-chosen id,
but it does accept `--log-file` — so each attachment pins a private log path
and reads its own `Created conversation <uuid>` line back out of it. That id
locates the transcript exactly:
``~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript.jsonl``.
No directory scanning, no claiming: two attachments started in one working
directory cannot resolve to the same conversation because neither guesses.

The transcript is one JSON object per step. Chat speech is a DONE
``PLANNER_RESPONSE`` from ``MODEL`` with content; tool loops appear as
planner steps carrying ``tool_calls`` plus ``GENERIC`` tool-result steps, both
of which stay off the line. Turn boundaries are real records too: a
``USER_INPUT`` step begins a turn and a planner response without tool calls
ends it, so both are reported as receipts.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from partyline.adapters import Adapter
from partyline.adapters.receipts import BEGAN, ENDED, receipt

LOG_ROOT = os.path.expanduser("~/.partyline/sessions/antigravity")
BRAIN_ROOT = Path.home() / ".gemini" / "antigravity-cli" / "brain"
CREATED = re.compile(r"Created conversation ([0-9a-fA-F-]{36})")


class PartylineAdapter(Adapter):
    kind = "antigravity"

    # A wake written into the pty is not a wake the TUI accepted: an idle
    # antigravity TUI can hold a pasted digest unsubmitted — the server's
    # cursor has advanced, presence is armed, and no turn ever starts
    # (docs/lessons.md). Verify each wake against the transcript: resend on a
    # pi-style schedule, then give up loudly rather than silently.
    RETRY_AT = (12.0, 24.0)
    GIVE_UP_AT = 45.0

    def __init__(self, att, post, on_status, on_cli_session=None):
        super().__init__(att, post, on_status, on_cli_session)
        self._outstanding: list[str] = []
        self._watchdog: asyncio.Task | None = None

    async def stop(self):
        if self._watchdog is not None:
            self._watchdog.cancel()
        await super().stop()

    async def deliver(self, messages: list[dict]):
        digest = self.format_digest(messages)
        await super().deliver(messages)
        if not digest.strip() or not self.alive():
            return
        self._outstanding.append(digest)
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._verify_delivery())

    @staticmethod
    def _contains(content: str, probe: str) -> bool:
        """Whitespace-normalized containment: the TUI may reflow a long paste,
        so a digest matches the submitted input up to whitespace runs."""
        return bool(probe) and " ".join(probe.split()) in " ".join(content.split())

    def _note_user_input(self, content: str):
        """A transcript input proves the TUI accepted any digest it contains."""
        self._outstanding = [d for d in self._outstanding if not self._contains(content, d)]

    async def _verify_delivery(self):
        waited = 0.0
        retries = list(self.RETRY_AT)
        while self._outstanding and self.alive():
            await asyncio.sleep(1.0)
            waited += 1.0
            if not self._outstanding:
                break
            if retries and waited >= retries[0]:
                retries.pop(0)
                for digest in list(self._outstanding):
                    await self.send_keys(digest)
            elif waited >= self.GIVE_UP_AT:
                self._outstanding.clear()
                await self.post(
                    "system", "system",
                    f"@{self.att['name']}: a wake was pasted but the TUI never took it "
                    "(no matching input in the transcript after 45s) — peek at its "
                    "terminal and press Enter, or @mention it again.",
                )

    def log_path(self) -> str:
        """One log file per attachment — the conversation id cannot be ambiguous."""
        return os.path.join(LOG_ROOT, self.att["id"] + ".log")

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["agy"]
        if "--log-file" not in cmd:
            cmd += ["--log-file", self.log_path()]
        if self.resume and self.att.get("cli_session") and "--conversation" not in cmd:
            # Re-attaching reopens the same conversation, so the process comes
            # back with its full context.
            cmd += ["--conversation", str(self.att["cli_session"])]
            if prompt := getattr(self, "_startup_prompt", ""):
                cmd += ["--prompt-interactive", prompt]
        return cmd

    def stage_startup_delivery(self, messages: list[dict]) -> bool:
        """Make a continuation part of the interactive resume command.

        `--prompt-interactive` is accepted at process creation, so the wake
        rides the resume argv instead of racing a TUI that may still be
        booting. Receipt is confirmed from the transcript's USER_INPUT record.
        """
        if not self.resume or not messages:
            return False
        prompt = self.format_digest(messages)
        if not prompt.strip():
            return False
        self._startup_prompt = prompt
        # The startup prompt is the first real wake after a resume, so output
        # from this turn is no longer leftover speech from before the restart.
        self._silent_until_wake = False
        return True

    def _conversation_from_log(self) -> str | None:
        try:
            text = Path(self.log_path()).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        match = CREATED.search(text)
        return match.group(1) if match else None

    async def _run(self):
        os.makedirs(LOG_ROOT, exist_ok=True)
        await asyncio.sleep(4.0)
        if not self.alive():
            return
        if not self.resume:
            await self.send_keys(self.briefing())

        conversation = str(self.att.get("cli_session") or "") if self.resume else ""
        waited = 0.0
        while not conversation and self.alive():
            conversation = self._conversation_from_log() or ""
            if conversation:
                break
            await asyncio.sleep(1.0)
            waited += 1.0
            if waited in (12.0, 24.0):
                # Probably held at a first-run or trust prompt: accept the
                # default and re-send the briefing.
                os.write(self.master, b"\r")
                await asyncio.sleep(1.0)
                await self.send_keys(self.briefing())
            elif waited > 45.0:
                await self.post(
                    "system", "system",
                    f"@{self.att['name']}: no conversation after 45s — the CLI is probably "
                    f"showing a first-run or trust prompt. Run `agy` manually once in "
                    f"{self.att['cwd']}, then re-attach.",
                )
                return
        if not conversation or not self.alive():
            return
        if self.on_cli_session:
            self.on_cli_session(conversation)

        transcript = BRAIN_ROOT / conversation / ".system_generated" / "logs" / "transcript.jsonl"
        while not transcript.exists() and self.alive():
            await asyncio.sleep(0.5)
        if not self.alive():
            return

        seen: set[str] = set()

        async def handle(record):
            if not self._fresh(record.get("created_at")):
                return
            # step_index alone repeats across chunks; created_at pins the write.
            key = f"{record.get('step_index')}:{record.get('created_at')}"
            if key in seen:
                return
            seen.add(key)
            content = record.get("content") or ""
            if record.get("source") == "USER_EXPLICIT" and record.get("type") == "USER_INPUT":
                self._note_user_input(content)
                prompt = getattr(self, "_startup_prompt", "")
                if prompt and self._contains(content, prompt):
                    self.mark_startup_delivery_received()
                await receipt(self.att, BEGAN)
            elif (
                record.get("source") == "MODEL"
                and record.get("type") == "PLANNER_RESPONSE"
                and record.get("status") == "DONE"
            ):
                if not record.get("tool_calls"):
                    await receipt(self.att, ENDED)
                if isinstance(content, str) and content.strip():
                    await self.post(self.att["name"], "agent", content)

        await self._tail_jsonl(str(transcript), handle)
