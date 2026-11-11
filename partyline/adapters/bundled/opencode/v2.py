"""OpenCode 2 session_message transcripts; all input stays in the real TUI.

Schema: anomalyco/opencode v2, packages/schema/src/session-message.ts and
packages/core/src/session/sql.ts. Idle records close turns, including aborts;
assistant completion alone can precede another tool step.
"""

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from partyline.adapters import Adapter
from partyline.adapters.bundled.opencode.provider_log import ProviderLog
from partyline.adapters.bundled.opencode.wakes import WakeSettlement
from partyline.adapters.compaction import is_compaction_record
from partyline.adapters.receipts import BEGAN, ENDED, receipt
from partyline.mcp_attach import opencode_config_content, server_for

logger = logging.getLogger(__name__)
RESUME_READY_TIMEOUT_SECONDS = 30.0


class PartylineAdapter(WakeSettlement, Adapter):
    kind = "opencode-v2"
    _CLAIMED: dict[tuple[str, str], str] = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._wakes_init()
        self._store: Path | None = None
        self._session_id: str | None = None
        self._claim_seq = 0
        self._seen: set[str] = set()
        self.provider_failed = False
        self._provider_log = None
        self._busy = False
        self.last_transcript_progress = time.monotonic()
        self._row_versions: dict[str, int] = {}
        self._resume_claimed_at: float | None = None

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["opencode2"]
        # A remote/shared server would execute tools outside this process's fence.
        if any(arg in ("--server", "--no-standalone")
               or arg.startswith(("--server=", "--standalone=")) for arg in cmd):
            raise ValueError("OpenCode v2 requires a private --standalone server")
        if any(arg == "--prompt" or arg.startswith("--prompt=") for arg in cmd):
            raise ValueError("Partyline supplies the OpenCode v2 startup prompt")
        if "--standalone" not in cmd:
            cmd.append("--standalone")
        if "--auto" not in cmd:
            cmd.append("--auto")
        if self.resume and self.att.get("cli_session"):
            if any(arg in ("--session", "-s") or arg.startswith("--session=") for arg in cmd):
                raise ValueError("Partyline supplies the resumed OpenCode v2 session")
            cmd += ["--session", str(self.att["cli_session"])]
        prompt = self._with_claim(
            "Partyline resume check. Reply READY, then wait for the next instruction."
        ) if self.resume else self.briefing()
        return cmd + ["--prompt", prompt]

    def spawn_env(self) -> dict[str, str]:
        # V1 and v2 otherwise share opencode.db. Keep their schema migrations apart.
        return {"OPENCODE_DB": os.environ.get("OPENCODE_DB", "opencode-v2.db"), **self.mcp_env()}

    def mcp_env(self) -> dict[str, str]:
        # Merged into the inline config the preset wrapper also merges into;
        # OPENCODE_CONFIG_DIR is not used because it can hide the user's config.
        server = server_for(self.att)
        if server is None:
            return {}
        content = opencode_config_content(os.environ.get("OPENCODE_CONFIG_CONTENT", ""), server)
        return {} if content is None else {"OPENCODE_CONFIG_CONTENT": content}

    async def start(self):
        path = await asyncio.to_thread(self._resolve_path, "log")
        self._provider_log = await asyncio.to_thread(self._open_provider_log, path)
        await super().start()

    def _open_provider_log(self, path):
        return ProviderLog(path if path.suffix == ".log" else path / "opencode.log",
                           self._claim_token, self.att["cwd"])

    def _resolve_store(self) -> Path:
        return self._resolve_path("db")

    def _resolve_path(self, kind) -> Path:
        # This diagnostic prints a path only: no server, session, or model call.
        executable = (self.att["command"] or ["opencode2"])[0]
        result = subprocess.run(
            [executable, "debug", "paths", kind], check=True, capture_output=True,
            text=True, timeout=15, cwd=self.att["cwd"],
            env=dict(os.environ, **self.spawn_env()),
        )
        path = Path(result.stdout.strip())
        if not path.is_absolute():
            raise ValueError("OpenCode v2 must use an absolute, on-disk diagnostic path")
        return path

    def _connect(self):
        assert self._store is not None
        return sqlite3.connect(f"{self._store.as_uri()}?mode=ro", uri=True)

    def _find_session(self) -> str | None:
        """Only a user row containing this activation's nonce can claim a session."""
        with contextlib.closing(self._connect()) as db:
            rows = db.execute(
                "SELECT s.id, m.seq, m.data FROM session_v2 s "
                "JOIN session_message m ON m.session_id = s.id "
                "WHERE s.directory = ? AND s.parent_id IS NULL AND m.type = 'user' "
                "AND m.time_created >= ? AND instr(m.data, ?) > 0",
                (self.att["cwd"].replace("\\", "/"), int(self.spawned_at * 1000),
                 self._claim_token),
            ).fetchall()
        for session, seq, raw in rows:
            if self.resume and session != self.att.get("cli_session"):
                continue
            if (str(self._store), session) in self._CLAIMED:
                continue
            data = self._decode(raw)
            if isinstance(data.get("text"), str) and self._claim_token in data["text"]:
                self._claim_seq = seq
                self.observe_claim(data["text"])
                self._resume_claimed_at = time.monotonic()
                return session
        return None

    @staticmethod
    def _decode(raw) -> dict:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    async def _poll_provider(self):
        if self._provider_log is None:
            return
        errors = await asyncio.to_thread(self._provider_log.poll)
        if not errors:
            return
        self.provider_failed = True
        self._busy = False
        for cause, fresh in errors:
            if noted := self.att.get("on_provider_error"):
                await noted(cause, fresh)
            elif fresh:
                await self.post("system", "system",
                                f"⚠ @{self.att['name']}: model provider error — {cause}")
        await receipt(self.att, ENDED)

    async def _poll(self):
        with contextlib.closing(self._connect()) as db:
            rows = db.execute(
                "SELECT id, type, data FROM session_message "
                "WHERE session_id = ? AND seq >= ? ORDER BY seq",
                (self._session_id, self._claim_seq),
            ).fetchall()
        for ident, kind, raw in rows:
            version = hash((kind, raw))
            if self._row_versions.get(ident) != version:
                self._row_versions[ident] = version
                self.last_transcript_progress = time.monotonic()
            if ident in self._seen:
                continue
            data = self._decode(raw)
            if not data:
                continue
            if kind == "compaction":
                # The row type is the shape; only completed ones count. The
                # seen-set is the dedup: a re-read row never counts twice.
                if is_compaction_record("opencode-v2", {**data, "type": kind}):
                    noted = self.att.get("on_compaction")
                    if noted:
                        await noted(data.get("reason") or "auto")
                self._seen.add(ident)
                continue
            if kind == "assistant":
                timing = data.get("time")
                if not isinstance(timing, dict) or timing.get("completed") is None:
                    continue
                content = data.get("content", [])
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict) or part.get("type") != "text":
                            continue
                        text = part.get("text")
                        if isinstance(text, str) and text.strip():
                            self.provider_failed = False
                            await self.post(self.att["name"], "agent", text)
            elif kind == "user":
                self.observe_claim(raw)
                await self._observe_user_part(raw, part_id=ident)
                if not self._busy:
                    self._busy = True
                    await receipt(self.att, BEGAN)
                if not self.resume:
                    self.mark_ready()
            elif kind == "idle":
                if self._busy:
                    self._busy = False
                    await receipt(self.att, ENDED)
                # A resume claim starts a real model turn. The TUI can drop
                # input during that turn; open delivery only at its idle receipt.
                self.mark_ready()
                self._schedule_unproved_repool()
            self._seen.add(ident)
        # Readiness must not strand sequential recovery if the provider hangs
        # or errors without an idle row. This opens no delivery credit or idle.
        if (self.resume and self._resume_claimed_at is not None
                and time.monotonic() - self._resume_claimed_at >= RESUME_READY_TIMEOUT_SECONDS):
            self.mark_ready()
        # An idle TUI may discard a paste without producing another record.
        # Revisit unproved input even when there is no new idle row to tail.
        if not self._busy:
            self._schedule_unproved_repool()

    async def _run(self):
        try:
            await self._tail_session()
        except Exception as exc:
            self._mark_not_ready()
            logger.exception("OpenCode v2 transcript watcher failed")
            try:
                await self.post("system", "system", f"{self.att['name']}: OpenCode v2 "
                                f"transcript startup or monitoring failed: {exc}. "
                                "Stopping this process; unread messages remain pending.")
            finally:
                from ....attachment_stop_audit import direct_stop
                direct_stop(self.att["id"], "opencode.transcript_watcher_failure")
                await self.stop()
        finally:
            # A watcher that ends must never leave a readiness waiter stranded.
            self._mark_not_ready()
            self._release_claim()

    async def _tail_session(self):
        self._store = await asyncio.to_thread(self._resolve_store)
        paths = [self._store]
        if self._provider_log is not None:
            paths.append(self._provider_log.path)
        async with self.file_events(*paths, changes=self._changes):
            await self._follow_session()

    async def _follow_session(self):
        deadline = self.event_time() + 45.0
        submitted = False
        while self.event_time() < deadline:
            if not self.alive():
                return
            try:
                self._session_id = self._find_session()
            except sqlite3.Error:
                pass
            if self._session_id:
                self._CLAIMED[(str(self._store), self._session_id)] = self._claim_token
                if self.on_cli_session:
                    self.on_cli_session(self._session_id)
                break
            await self._poll_provider()
            # 2.0.18 can leave --prompt in the composer without submitting it.
            # Only press Enter once it is visibly loaded; readiness and speech
            # still require the nonce in a structured user row, never the screen.
            if not submitted and self._claim_token in self.screen_text():
                await self._write_all(b"\r")
                submitted = True
            await self.wait_for_change(max(0, deadline - self.event_time()))
        else:
            raise RuntimeError("no claimed OpenCode v2 session appeared after 45s; "
                               "check the terminal for startup errors")
        while self.alive():
            try:
                await self._poll()
            except sqlite3.Error as exc:
                logger.debug("OpenCode v2 poll skipped: %s", exc)
            await self._poll_provider()
            delay = None
            if self.resume and not self._ready.is_set() and self._resume_claimed_at is not None:
                delay = max(0, self._resume_claimed_at + RESUME_READY_TIMEOUT_SECONDS - time.monotonic())
            await self.wait_for_change(delay)

    def _release_claim(self):
        key = (str(self._store), self._session_id)
        if self._CLAIMED.get(key) == self._claim_token:
            del self._CLAIMED[key]

    async def stop(self):
        try:
            await super().stop()
        finally:
            self._release_claim()
