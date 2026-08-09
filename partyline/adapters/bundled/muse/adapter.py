"""Adapter for Meta's Muse Code interactive terminal.

Muse owns a durable JSONL log for each session. A fresh TUI accepts an initial
prompt, so the Partyline briefing is placed in argv and then used to identify
the exact new log. Resumes use Muse's stored UUID and append to that same log.
The log's canonical vocabulary is not the raw event vocabulary printed by
``muse exec --json``: committed speech is a ``runtime.session`` event here,
not a ``run.output.delta``. Only committed assistant messages are relayed;
terminal rendering is never treated as chat output.

Muse asks its terminal for a cursor position before drawing and exits when a
bare pty does not answer. The bundled adapter opts into Partyline's terminal
query responder and observes the following render before declaring readiness.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

from partyline.adapters import Adapter


CURSOR_QUERY = b"\x1b[6n"


class PartylineAdapter(Adapter):
    kind = "muse"
    answers_terminal_queries = True

    _claims_lock = threading.Lock()
    _claimed_sessions: set[str] = set()
    DISCOVERY_TIMEOUT = 90.0
    POLL_SECONDS = 0.5
    TUI_READY_TIMEOUT = 10.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._known_logs: set[Path] = set()
        self._session_id: str | None = None
        self._resume_offset: int | None = None
        self._probe_tail = b""
        self._saw_cursor_query = False
        self._tui_rendered = asyncio.Event()
        self._seen_messages: set[str] = set()

    @staticmethod
    def _session_root() -> Path:
        data_home = os.environ.get("XDG_DATA_HOME")
        base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
        return base / "muse" / "sessions"

    @classmethod
    def _release(cls, session_id: str | None) -> None:
        if session_id is None:
            return
        with cls._claims_lock:
            cls._claimed_sessions.discard(session_id)

    def _session_logs(self) -> list[Path]:
        root = self._session_root()
        if not root.is_dir():
            return []
        return [path for path in root.rglob("session.jsonl") if "subagent" not in path.parts]

    def _log_for_session(self, session_id: str) -> Path | None:
        return next((path for path in self._session_logs() if path.parent.name == session_id), None)

    async def start(self):
        self._known_logs = set(self._session_logs())
        if self.resume and (session_id := str(self.att.get("cli_session") or "").strip()):
            path = self._log_for_session(session_id)
            if path is not None:
                try:
                    self._resume_offset = path.stat().st_size
                except OSError:
                    self._resume_offset = None
        await super().start()

    async def stop(self):
        self._release(self._session_id)
        await super().stop()

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["muse", "--yolo"]
        if "--no-session-log" in cmd:
            raise ValueError("Muse's --no-session-log is incompatible with transcript tailing")
        if self.resume:
            session_id = str(self.att.get("cli_session") or "").strip()
            if not session_id:
                raise ValueError("Muse resume requires the stored session UUID")
            return [cmd[0], "resume", session_id, *cmd[1:]]
        # The structured copy of this exact prompt is an unforgeable link from
        # this attachment to the new session, even when two TUIs start together.
        return [*cmd, self.briefing()]

    async def on_output(self, data: bytes):
        combined = self._probe_tail + data
        saw_query = CURSOR_QUERY in combined
        self._probe_tail = combined[-(len(CURSOR_QUERY) - 1):]
        if saw_query:
            self._saw_cursor_query = True
        elif self._saw_cursor_query and data:
            # The base has answered the query, and Muse emitted another frame:
            # its input loop is initialized. This observes protocol progress;
            # the adapter never parses terminal content as chat output.
            self._tui_rendered.set()

    async def _wait_until_tui_rendered(self) -> None:
        try:
            await asyncio.wait_for(
                self._tui_rendered.wait(),
                timeout=self.TUI_READY_TIMEOUT,
            )
        except TimeoutError:
            # Cursor interrogation is a Muse 0.1.0 behavior, not an adapter
            # contract. A later TUI may skip it; transcript readiness must then
            # degrade to assumed instead of hanging the attachment forever.
            pass

    @staticmethod
    def _decode(line: str) -> dict | None:
        if not line.endswith("\n"):
            return None
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _workspace(record: dict) -> str | None:
        if record.get("payload_type") != "runtime.session.metadata":
            return None
        return ((record.get("payload") or {}).get("record") or {}).get("workspace_root")

    @staticmethod
    def _user_prompt(record: dict) -> str | None:
        # Two spellings for one fact. The echo provider logs a submitted prompt
        # as a command_intake record; the meta provider logs it as the run's
        # `started` event. An adapter that read only the first spelling matched
        # every echo rehearsal and then timed out on the first real session.
        if record.get("payload_type") == "runtime.command_intake.received":
            command = (((record.get("payload") or {}).get("record") or {}).get("command") or {})
            return command.get("prompt") if command.get("kind") == "turn_submit" else None
        if record.get("payload_type") == "runtime.session":
            payload = record.get("payload") or {}
            event = payload.get("event") or {}
            if payload.get("kind") == "run" and event.get("kind") == "started":
                prompt = event.get("prompt")
                return prompt if isinstance(prompt, str) else None
        return None

    @staticmethod
    def _assistant_message(record: dict) -> tuple[str | None, str] | None:
        if record.get("payload_type") != "runtime.session":
            return None
        payload = record.get("payload") or {}
        event = payload.get("event") or {}
        if payload.get("kind") != "run" or event.get("kind") != "assistant_message_committed":
            return None
        text = event.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        message_id = event.get("message_id")
        return (message_id if isinstance(message_id, str) else None, text)

    def _matches_fresh_session(self, path: Path) -> bool:
        workspace = None
        matched_prompt = False
        try:
            with path.open(encoding="utf-8", errors="replace") as file:
                for line in file:
                    record = self._decode(line)
                    if record is None:
                        continue
                    workspace = self._workspace(record) or workspace
                    matched_prompt = matched_prompt or self._user_prompt(record) == self.briefing()
        except OSError:
            return False
        if not matched_prompt or not workspace:
            return False
        try:
            return os.path.realpath(workspace) == os.path.realpath(self.att["cwd"])
        except (OSError, TypeError):
            return workspace == self.att["cwd"]

    def _find_and_claim(self) -> Path | None:
        with self._claims_lock:
            if self.resume:
                session_id = str(self.att.get("cli_session") or "").strip()
                path = self._log_for_session(session_id)
                candidates = [path] if path is not None else []
            else:
                candidates = [path for path in self._session_logs() if path not in self._known_logs]
            for path in sorted(candidates):
                session_id = path.parent.name
                if session_id in self._claimed_sessions:
                    continue
                if not self.resume and not self._matches_fresh_session(path):
                    continue
                self._claimed_sessions.add(session_id)
                self._session_id = session_id
                return path
        return None

    async def _tail(self, path: Path, offset: int | None) -> None:
        with path.open(encoding="utf-8", errors="replace") as file:
            # A resume normally snapshots the byte cursor before spawning. If
            # that stat failed, start at end-of-log now: replaying from zero can
            # race deliver(), clear resume silence, and flood old messages.
            if offset is None:
                file.seek(0, os.SEEK_END)
            else:
                file.seek(offset)
            self.mark_ready()
            while True:
                position = file.tell()
                line = file.readline()
                if not line:
                    if not self.alive():
                        return
                    await asyncio.sleep(self.POLL_SECONDS)
                    continue
                if not line.endswith("\n"):
                    if not self.alive():
                        return
                    file.seek(position)
                    await asyncio.sleep(0.3)
                    continue
                record = self._decode(line)
                message = self._assistant_message(record or {})
                if message is None:
                    continue
                message_id, body = message
                if message_id and message_id in self._seen_messages:
                    continue
                if message_id:
                    self._seen_messages.add(message_id)
                await self.post(self.att["name"], "agent", body)

    async def _run(self):
        try:
            waited = 0.0
            path = self._find_and_claim()
            while path is None and self.alive() and waited < self.DISCOVERY_TIMEOUT:
                await asyncio.sleep(self.POLL_SECONDS)
                waited += self.POLL_SECONDS
                path = self._find_and_claim()
            if path is None:
                if self.alive():
                    await self.post(
                        "system", "system",
                        f"@{self.att['name']}: no Muse session log appeared after "
                        f"{int(self.DISCOVERY_TIMEOUT)}s; transcript tailing stopped",
                    )
                return
            if self.on_cli_session is not None:
                self.on_cli_session(self._session_id)
            await self._wait_until_tui_rendered()
            offset = self._resume_offset if self.resume else 0
            await self._tail(path, offset)
        finally:
            self._release(self._session_id)
