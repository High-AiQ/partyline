"""Common runtime for interactive process adapters.

Each attachment is run in a real pseudo-terminal.  Input is pasted into that
terminal as keystrokes, while adapters choose the cleanest available way to
turn process output into chat messages.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import struct
import subprocess
import sys
import termios
import time
from collections.abc import Awaitable, Callable

import pyte

from partyline import process_memory
from partyline.adapters import activation, fence, pty_io, startup_prompt
from partyline.adapters.process_shutdown import stop_process_group
from partyline.adapters.jsonl_receipts import JsonlPasteReceipts, tail_jsonl
from partyline.adapters.task_logging import log_task_deaths
from partyline.adapters.briefing import (
    fresh_checkpoint_briefing, connection_briefing,
    BRIEFING,
    TOPIC_BRIEFING,
    child_env,
    format_digest,
    safe_rider,
)
from partyline.adapters.terminal import KEYS, screen_text, terminal_responses
from partyline.terminal_viewers import TerminalViewer, TerminalViewerRegistry


Post = Callable[[str, str, str], Awaitable[None]]
Status = Callable[[str], Awaitable[None]]


class Adapter(JsonlPasteReceipts, activation.Activation, pty_io.PtyWriter,
              startup_prompt.StartupPromptGuard):
    """Base class for a process connected through a pseudo-terminal."""

    kind = "process"
    answers_terminal_queries = False

    def __init__(self, att: dict, post: Post, on_status: Status, on_cli_session=None):
        self.att = att
        self.resume = bool(att.get("resume"))
        self._post_to_chat = post
        # A process killed mid-turn comes back to a CLI that resumes the
        # interrupted turn, so its first output is a fragment of work nobody
        # asked for — it has had no new input since it died. Stay quiet until
        # something is actually delivered. Wrapping the callback rather than
        # asking each adapter to check means external adapters get this too.
        self._silent_until_wake = self.resume
        self._explained_silence = False
        self.on_status = on_status
        self.on_cli_session = on_cli_session
        self.proc: subprocess.Popen | None = None
        self.master: int | None = None
        self.spawned_at = 0.0
        self._tasks: list[asyncio.Task] = []
        self._stopping = False
        self._ready = asyncio.Event()
        self._ready_result: bool | None = None
        self._startup_delivery = asyncio.Event()
        self._startup_delivery_result: bool | None = None
        self._term = pyte.Screen(120, 40)
        self._term_stream = pyte.ByteStream(self._term)
        self._terminal_query_tail = b""
        self._terminal_viewers = TerminalViewerRegistry(self.screen_text)
        self._jsonl_receipts_init()
        self._startup_prompt_init()

    async def post(self, sender: str, sender_type: str, body: str):
        """Send something to the chat, unless the process is resuming mid-turn.

        Transcript adapters additionally hold agent speech until this
        activation's own claim token has been observed in the tailed
        session: a file adopted by mistake then carries no speech at all
        rather than another attachment's words under this handle. System
        notices — exits, failures, refusals — always get through, because
        they are how a person finds out something went wrong.
        """
        if self.pastes_claim() and not self._claim_proven and sender_type == "agent":
            return
        if self._silent_until_wake and sender_type == "agent":
            if not self._explained_silence:
                self._explained_silence = True
                await self._post_to_chat(
                    "system", "system",
                    f"{self.att['name']} resumed mid-turn — leftover output from the "
                    "interrupted turn was not posted; @mention it to pick up where it left off",
                )
            return
        await self._post_to_chat(sender, sender_type, body)

    def build_command(self) -> list[str]:
        return list(self.att["command"])
    async def start(self):
        self.memory_limit = process_memory.process_memory_limit()
        self.spawn_argv = process_memory.scope_argv(
            fence.launch_argv(self), self.memory_limit,
        )
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        env = dict(child_env(os.environ, self.att), TERM="xterm-256color")
        env.update(self.spawn_env())
        # Adapters declare what to strip so a spawned CLI doesn't mistake itself
        # for a nested harness. A trailing "*" clears a whole prefix.
        for key in self.att.get("adapter_metadata", {}).get("env_unset", []):
            if key.endswith("*"):
                prefix = key[:-1]
                for existing in [k for k in env if k.startswith(prefix)]:
                    env.pop(existing, None)
            else:
                env.pop(key, None)

        def preexec():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            if not sys.platform.startswith("linux"):
                process_memory.apply_address_space_limit(self.memory_limit)

        self.spawned_at = time.time()
        self.proc = subprocess.Popen(
            self.spawn_argv, stdin=slave, stdout=slave, stderr=slave,
            cwd=self.att["cwd"], env=env, preexec_fn=preexec,
        )
        os.close(slave)
        os.set_blocking(master, False)
        self.master = master
        self._tasks = log_task_deaths(
            [asyncio.create_task(c) for c in (self._drain(), self._watch_exit(), self._run())],
            self.att,
        )
        await self.on_status("running")

    def mark_ready(self) -> None:
        """Declare this adapter claimed its session and can be resumed; an
        exit or stop before then completes ``wait_ready()`` with ``False``."""
        if self._ready_result is None and not self._stopping:
            self._ready_result = True
            self._ready.set()
            on_claimed = self.att.get("on_transcript_claimed")
            if on_claimed:
                on_claimed()

    async def wait_ready(self) -> bool:
        """Wait until readiness is declared, or this adapter can never be ready."""
        await self._ready.wait()
        return self._ready_result is True

    def _mark_not_ready(self) -> None:
        if self._ready_result is None:
            self._ready_result = False
            self._ready.set()
        if self._startup_delivery_result is None:
            self._startup_delivery_result = False
            self._startup_delivery.set()

    async def stop(self):
        self._stopping = True
        self.abort_startup_prompt()
        self._mark_not_ready()
        self._terminal_viewers.close()
        if self.proc:
            await stop_process_group(self.proc)
        for task in self._tasks:
            task.cancel()
        await self.on_status("detached")

    async def _drain(self):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        def readable():
            try:
                data = os.read(self.master, 65536)  # type: ignore[arg-type]
            except BlockingIOError:
                return
            except OSError:
                data = b""
            if data:
                queue.put_nowait(data)
            else:
                loop.remove_reader(self.master)
                queue.put_nowait(None)

        loop.add_reader(self.master, readable)
        try:
            while (data := await queue.get()) is not None:
                try:
                    self._term_stream.feed(data)
                except Exception:
                    pass
                self._terminal_viewers.publish(data)
                if self.answers_terminal_queries:
                    replies, self._terminal_query_tail = terminal_responses(
                        self._term, self._terminal_query_tail, data)
                    if replies:
                        os.write(self.master, replies)  # type: ignore[arg-type]
                await self.on_output(data)
        finally:
            try:
                loop.remove_reader(self.master)
            except Exception:
                pass
            self._terminal_viewers.close()

    async def _watch_exit(self):
        assert self.proc is not None
        rc = await asyncio.get_running_loop().run_in_executor(None, self.proc.wait)
        self.abort_startup_prompt()
        self._mark_not_ready()
        if not self._stopping:
            await self.on_status("exited")
            notice = process_memory.exit_notice(rc, self.memory_limit, self.att["name"])
            await self.post("system", "system", notice or f"{self.att['name']} exited (code {rc})")

    async def _run(self):
        """Adapter-specific background task."""
    async def on_output(self, data: bytes):
        """Receive bytes from the pty. Transcript adapters can ignore this."""

    async def deliver(self, messages: list[dict]):
        if not await self.wait_startup_delivery():
            return False
        # Being woken ends post-resume silence — only once the wake reached the pty:
        # clearing first lets a tail release held speech before the turn is recorded.
        text = self.format_digest(messages)
        marker = getattr(self, "_pending_paste_marker", None)
        self._pending_paste_marker = None
        if marker is None and getattr(self, "jsonl_paste_receipts", False):
            marker = self._new_paste_marker()
        tracked = self._track_jsonl_paste(text, messages, marker) if marker else False
        paste = f"{marker}\n\n{text}" if marker else text
        if paste.strip():
            try:
                await self.send_keys(paste)
            except BaseException:
                if tracked:
                    self._jsonl_receipts = [
                        receipt for receipt in self._jsonl_receipts
                        if receipt["marker"] != marker
                    ]
                raise
        self._silent_until_wake = False
        if tracked:
            return False

    def stage_startup_delivery(self, messages: list[dict]) -> bool:
        """Stage a wake in the process command, if this adapter supports it.

        The default interactive-process contract has no safe way to do that:
        callers must wait for ``wait_ready()`` before writing to its pty. An
        adapter whose CLI accepts an initial prompt can override this hook and
        make delivery part of process creation instead. Returning ``True``
        declares that ``start()`` will include the digest; the adapter must
        separately mark its structured receipt before the cursor advances.
        """
        return False

    # The digest's shape lives in briefing.py; cwd git and the task rider are
    # live delivery-time state, never staged. A transcript adapter's digest
    # carries its claim token until the tailed session records one.
    def format_digest(self, messages: list[dict]) -> str:
        return self._with_claim(format_digest(messages, safe_rider(self.att),
                                              str(self.att.get("cwd", "")),
                                              api=child_env({}, self.att)["PARTYLINE_API"]))

    async def send_keys(self, text: str):
        await self._write_all(b"\x1b[200~" + text.encode() + b"\x1b[201~")
        await asyncio.sleep(0.35)
        await self._write_all(b"\r")

    def screen_text(self) -> str:
        return screen_text(self._term)

    def attach_terminal_viewer(self) -> TerminalViewer:
        return self._terminal_viewers.attach()

    def detach_terminal_viewer(self, viewer: TerminalViewer) -> None:
        self._terminal_viewers.detach(viewer)

    def terminal_dimensions(self) -> tuple[int, int]:
        return self._term.columns, self._term.lines

    def write_terminal(self, data: bytes) -> None:
        assert self.master is not None
        os.write(self.master, data)

    def send_key(self, key: str):
        data = KEYS.get(key)
        if data is None:
            raise ValueError(f"unsupported key: {key}")
        assert self.master is not None
        os.write(self.master, data)

    def briefing(self) -> str:
        text = BRIEFING.format(name=self.att["name"], conv=self.att.get("conv_name", "?"))
        text += connection_briefing(self.att)
        if topic := (self.att.get("topic") or "").strip():
            text += TOPIC_BRIEFING.format(topic=topic)
        return self._with_claim(fresh_checkpoint_briefing(text, self.att.get("fresh_checkpoint")))

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def _tail_jsonl(self, path: str, handle_line):
        """Follow a JSONL transcript, ignoring incomplete or invalid records."""
        await tail_jsonl(self, path, handle_line)
