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
from typing import Awaitable, Callable

import pyte


BRIEFING = (
    'You are "{name}", a participant in the conversation "{conv}" with people and other '
    'processes. Incoming chat arrives as `[sender]: text`. Everything you write is posted '
    'under your name. Keep replies concise and conversational unless asked to do work. '
    'Use @name when a reply is for a particular participant: processes receive messages only '
    'when mentioned. Say hello in one short line to confirm you are connected.'
)

TOPIC_BRIEFING = " The conversation topic is standing context: «{topic}»"

Post = Callable[[str, str, str], Awaitable[None]]
Status = Callable[[str], Awaitable[None]]


class Adapter:
    """Base class for a process connected through a pseudo-terminal."""

    kind = "process"

    def __init__(self, att: dict, post: Post, on_status: Status, on_cli_session=None):
        self.att = att
        self.resume = bool(att.get("resume"))
        self.post = post
        self.on_status = on_status
        self.on_cli_session = on_cli_session
        self.proc: subprocess.Popen | None = None
        self.master: int | None = None
        self.spawned_at = 0.0
        self._tasks: list[asyncio.Task] = []
        self._stopping = False
        self._term = pyte.Screen(120, 40)
        self._term_stream = pyte.ByteStream(self._term)

    def build_command(self) -> list[str]:
        return list(self.att["command"])

    async def start(self):
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        env = dict(os.environ, TERM="xterm-256color")
        for key in self.att.get("adapter_metadata", {}).get("env_unset", []):
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

    async def stop(self):
        self._stopping = True
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
                await self.on_output(data)
        finally:
            try:
                loop.remove_reader(self.master)
            except Exception:
                pass

    async def _watch_exit(self):
        assert self.proc is not None
        rc = await asyncio.get_running_loop().run_in_executor(None, self.proc.wait)
        if not self._stopping:
            await self.on_status("exited")
            await self.post("system", "system", f"@{self.att['name']} exited (code {rc})")

    async def _run(self):
        """Adapter-specific background task."""

    async def on_output(self, data: bytes):
        """Receive bytes from the pty. Transcript adapters can ignore this."""

    async def deliver(self, messages: list[dict]):
        text = self.format_digest(messages)
        if text.strip():
            await self.send_keys(text)

    def format_digest(self, messages: list[dict]) -> str:
        lines = "\n".join(f"[{m['sender']}]: {m['body']}" for m in messages)
        return f"{lines}\n(reminder: mention @name to reach a process)"

    async def send_keys(self, text: str):
        assert self.master is not None
        os.write(self.master, b"\x1b[200~" + text.encode() + b"\x1b[201~")
        await asyncio.sleep(0.35)
        os.write(self.master, b"\r")

    def screen_text(self) -> str:
        lines = [line.rstrip() for line in self._term.display]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    KEYS = {
        "enter": b"\r", "esc": b"\x1b", "tab": b"\t", "space": b" ",
        "up": b"\x1b[A", "down": b"\x1b[B", "left": b"\x1b[D", "right": b"\x1b[C",
        "y": b"y", "n": b"n", "1": b"1", "2": b"2", "3": b"3", "4": b"4",
    }

    def send_key(self, key: str):
        data = self.KEYS.get(key)
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
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            while True:
                position = file.tell()
                line = file.readline()
                if not line:
                    if not self.alive():
                        return
                    await asyncio.sleep(0.5)
                    continue
                if not line.endswith("\n"):
                    file.seek(position)
                    await asyncio.sleep(0.3)
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                await handle_line(record)
