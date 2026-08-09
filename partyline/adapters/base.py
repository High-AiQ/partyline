"""Common runtime for interactive process adapters.

Each attachment is run in a real pseudo-terminal.  Input is pasted into that
terminal as keystrokes, while adapters choose the cleanest available way to
turn process output into chat messages.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import signal
import struct
import subprocess
import termios
import time
from collections.abc import Awaitable, Callable

import pyte

from partyline.adapters.briefing import BRIEFING, TOPIC_BRIEFING

from partyline.adapters.terminal import KEYS, screen_text, terminal_responses


Post = Callable[[str, str, str], Awaitable[None]]
Status = Callable[[str], Awaitable[None]]


class Adapter:
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

    async def post(self, sender: str, sender_type: str, body: str):
        """Send something to the chat, unless the process is resuming mid-turn.

        Only agent speech is held back. System notices — exits, failures — must
        always get through, because they are how a person finds out something
        went wrong.
        """
        if self._silent_until_wake and sender_type == "agent":
            if not self._explained_silence:
                self._explained_silence = True
                await self._post_to_chat(
                    "system", "system",
                    f"@{self.att['name']} resumed mid-turn — leftover output from the "
                    "interrupted turn was not posted; @mention it to pick up where it left off",
                )
            return
        await self._post_to_chat(sender, sender_type, body)

    def build_command(self) -> list[str]:
        return list(self.att["command"])

    async def start(self):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        env = dict(os.environ, TERM="xterm-256color")
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

        self.spawned_at = time.time()
        self.proc = subprocess.Popen(
            self.build_command(), stdin=slave, stdout=slave, stderr=slave,
            cwd=self.att["cwd"], env=env, preexec_fn=preexec,
        )
        os.close(slave)
        os.set_blocking(master, False)
        self.master = master
        self._tasks = [
            asyncio.create_task(self._drain()),
            asyncio.create_task(self._watch_exit()),
            asyncio.create_task(self._run()),
        ]
        await self.on_status("running")

    def mark_ready(self) -> None:
        """Declare that this adapter has claimed its session and can be resumed safely.

        Adapters call this only after their transcript/session is unambiguous and
        ready for another process to start. A process that exits or is stopped
        before then completes ``wait_ready()`` with ``False`` instead of leaving
        an orchestrator waiting forever.
        """
        if self._ready_result is None and not self._stopping:
            self._ready_result = True
            self._ready.set()

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
        self._mark_not_ready()
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            await asyncio.sleep(0.5)
            if self.proc.poll() is None:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
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

    async def _watch_exit(self):
        assert self.proc is not None
        rc = await asyncio.get_running_loop().run_in_executor(None, self.proc.wait)
        self._mark_not_ready()
        if not self._stopping:
            await self.on_status("exited")
            await self.post("system", "system", f"@{self.att['name']} exited (code {rc})")

    async def _run(self):
        """Adapter-specific background task."""

    async def on_output(self, data: bytes):
        """Receive bytes from the pty. Transcript adapters can ignore this."""

    async def deliver(self, messages: list[dict]):
        # Being woken is the thing that ends post-resume silence: from here on
        # the process is answering something real rather than finishing a turn
        # that was cut off.
        self._silent_until_wake = False
        text = self.format_digest(messages)
        if text.strip():
            await self.send_keys(text)

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

    def mark_startup_delivery_received(self) -> None:
        """A staged startup digest appeared as structured process input."""
        if self._startup_delivery_result is None and not self._stopping:
            self._startup_delivery_result = True
            self._startup_delivery.set()

    async def wait_startup_delivery_received(self) -> bool:
        """Wait for structured receipt, or for the process to exit first."""
        await self._startup_delivery.wait()
        return self._startup_delivery_result is True

    # Tail of every wake digest. The briefing states the rule once, but in a long
    # session it scrolls far out of the recent context — this keeps the rule next
    # to the newest messages, which is where drift actually happens.
    DIGEST_FOOTER = ("(reminder: processes only see messages that @mention them — @name any "
                     "process your reply is for; humans read everything; acknowledge handed "
                     "work in one line, then speak only for blockers, findings, or results)")

    def format_digest(self, messages: list[dict]) -> str:
        lines = "\n".join(f"[{m['sender']}]: {m['body']}" for m in messages)
        return f"{lines}\n{self.DIGEST_FOOTER}"

    async def send_keys(self, text: str):
        assert self.master is not None
        os.write(self.master, b"\x1b[200~" + text.encode() + b"\x1b[201~")
        await asyncio.sleep(0.35)
        os.write(self.master, b"\r")

    def screen_text(self) -> str:
        return screen_text(self._term)

    def send_key(self, key: str):
        data = KEYS.get(key)
        if data is None:
            raise ValueError(f"unsupported key: {key}")
        assert self.master is not None
        os.write(self.master, data)

    def briefing(self) -> str:
        text = BRIEFING.format(name=self.att["name"], conv=self.att.get("conv_name", "?"))
        if topic := (self.att.get("topic") or "").strip():
            text += TOPIC_BRIEFING.format(topic=topic)
        return text

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _fresh(self, iso_ts) -> bool:
        """Return whether a transcript record belongs to this running process."""
        if not self.att.get("resume"):
            return True
        if not iso_ts:
            return False
        try:
            from datetime import datetime
            timestamp = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return False
        return timestamp >= self.spawned_at - 5

    async def _tail_jsonl(self, path: str, handle_line):
        """Follow a JSONL transcript, ignoring incomplete or invalid records."""
        with open(path, encoding="utf-8", errors="replace") as file:
            # Opening the claimed transcript is the readiness boundary for
            # transcript adapters: a sequential restart may now safely advance
            # to the next process without two discovery loops claiming one file.
            self.mark_ready()
            while True:
                position = file.tell()
                line = file.readline()
                if not line:
                    if not self.alive():
                        return
                    await asyncio.sleep(0.5)
                    continue
                if not line.endswith("\n"):
                    # A half-written record: wait for the writer to finish it.
                    # If the writer is gone it never will be, and without this
                    # check the tail spins on that fragment forever.
                    if not self.alive():
                        return
                    file.seek(position)
                    await asyncio.sleep(0.3)
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                await handle_line(record)
