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
import time
from pathlib import Path

from partyline.adapters import Adapter
from partyline.adapters.bundled.antigravity import logparse
from partyline.adapters.receipts import BEGAN, ENDED, receipt

LOG_ROOT = os.path.expanduser("~/.partyline/sessions/antigravity")
BRAIN_ROOT = Path.home() / ".gemini" / "antigravity-cli" / "brain"
CREATED = re.compile(r"Created conversation ([0-9a-fA-F-]{36})")
# How much of a digest's tail must be visible to prove it sits in the
# composer: a long paste scrolls, so only its end stays on the 40-line screen.
ECHO_PROBE = 40
# Flow control between writing a paste and its Enter, not a judgment: when
# the composer's echo never comes, the Enter goes anyway, as it always has.
PASTE_PACE = 5.0


class PartylineAdapter(Adapter):
    kind = "antigravity"

    MAX_NOTICES = 2

    def __init__(self, att, post, on_status, on_cli_session=None):
        super().__init__(att, post, on_status, on_cli_session)
        self._outstanding: list[tuple[str, float]] = []
        self._resend_counts: dict[str, int] = {}
        self._digest_messages: dict[str, list[dict]] = {}
        self._repool_messages: list[dict] = []
        self._notices = 0
        self._output_event = asyncio.Event()

    async def on_output(self, data: bytes):
        self._output_event.set()

    def _composer_shows(self, text: str) -> bool:
        """The CLI's redraw proves the paste sits in the composer."""
        probe = "".join(text.split())[-ECHO_PROBE:]
        return bool(probe) and probe in "".join(self.screen_text().split())

    async def send_keys(self, text: str):
        assert self.master is not None
        os.write(self.master, b"\x1b[200~" + text.encode() + b"\x1b[201~")
        deadline = time.time() + PASTE_PACE
        while self.alive() and not self._composer_shows(text):
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self._output_event.clear()
            try:
                await asyncio.wait_for(self._output_event.wait(), remaining)
            except TimeoutError:
                break
        os.write(self.master, b"\r")

    async def deliver(self, messages: list[dict]):
        if self.master is not None and any(
            self._composer_shows(digest) for digest, _ in self._outstanding
        ):
            os.write(self.master, b"\r")
        digest = self.format_digest(messages)
        await super().deliver(messages)
        if digest.strip() and self.alive():
            self._outstanding.append((digest, time.time()))
            self._digest_messages[digest] = list(messages)

    @staticmethod
    def _contains(content: str, probe: str) -> bool:
        """Whitespace-normalized containment: the TUI may reflow a long paste,
        so a digest matches the submitted input up to whitespace runs."""
        return bool(probe) and " ".join(probe.split()) in " ".join(content.split())

    async def _note_user_input(self, content: str, created_at) -> None:
        """Settle outstanding wakes against a real transcript input.

        A record may only judge digests pasted before it was written: a
        mention delivered mid-turn pastes a wake that an already-written
        record cannot contain, and judging it anyway would call a healthy
        paste skipped. Contained digests are verified. A digest the record
        predates-but-does-not contain was skipped — proven, not guessed —
        so it is re-sent up to 2 times; a skip after that re-pools for the
        next turn-end with one factual notice.
        """
        created = None
        if created_at:
            try:
                from datetime import datetime
                created = datetime.fromisoformat(
                    str(created_at).replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                created = None
        kept: list[tuple[str, float]] = []
        for digest, pasted_at in self._outstanding:
            if created is not None and pasted_at >= created:
                kept.append((digest, pasted_at))  # this record cannot judge it
                continue
            if self._contains(content, digest):
                self._notices = 0
                self._digest_messages.pop(digest, None)
                continue
            count = self._resend_counts.get(digest, 0) + 1
            self._resend_counts[digest] = count
            if count <= 2:
                kept.append((digest, pasted_at))
                await self.send_keys(digest)
            else:
                if self._notices < self.MAX_NOTICES:
                    self._notices += 1
                    await self.post(
                        "system", "system",
                        f"@{self.att['name']}: the CLI submitted other input after "
                        "this wake was pasted — wake queued for next turn-end",
                    )
                msgs = self._digest_messages.pop(digest, [])
                if msgs:
                    self._repool_messages.extend(msgs)
        self._outstanding = kept

    async def _note_log_line(self, line: str) -> None:
        """Settle outstanding wakes against a logged submission.

        The pinned log's HandleUserInput line is written at submit time, so
        it judges minutes before the transcript can. A line without a
        parseable timestamp cannot judge — degraded evidence is not a
        verdict. The transcript judge remains as the fallback channel.
        """
        if parsed := logparse.submission(line):
            await self._note_user_input(*parsed)

    async def _tail_log(self):
        """Follow the pinned `--log-file`, judging wakes by its submissions."""
        while not os.path.exists(self.log_path()) and self.alive():
            await asyncio.sleep(0.5)
        try:
            file = open(self.log_path(), encoding="utf-8", errors="replace")
        except OSError:
            return
        with file:
            file.seek(0, os.SEEK_END)  # only fresh lines may judge a wake
            while self.alive():
                line = file.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                await self._note_log_line(line)

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
                await self._note_user_input(content, record.get("created_at"))
                prompt = getattr(self, "_startup_prompt", "")
                if prompt and self._contains(content, prompt):
                    self.mark_startup_delivery_received()
                await receipt(self.att, BEGAN)
            elif (
                record.get("source") == "MODEL"
                and record.get("type") == "PLANNER_RESPONSE"
            ):
                status = record.get("status")
                ended = False
                if status in ("ERROR", "CANCELLED", "ABORTED", "FAILED"):
                    await receipt(self.att, ENDED)
                    ended = True
                elif status == "DONE":
                    if not record.get("tool_calls"):
                        await receipt(self.att, ENDED)
                        ended = True
                    if isinstance(content, str) and content.strip():
                        await self.post(self.att["name"], "agent", content)
                if ended and self._repool_messages:
                    to_flush = self._repool_messages[:]
                    self._repool_messages.clear()
                    await self.deliver(to_flush)

        log_tail = asyncio.create_task(self._tail_log())
        try:
            await self._tail_jsonl(str(transcript), handle)
        finally:
            log_tail.cancel()
