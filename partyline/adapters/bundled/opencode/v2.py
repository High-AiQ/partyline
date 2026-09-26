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

from partyline.adapters import Adapter
from partyline.adapters.bundled.opencode.wakes import WakeSettlement
from partyline.adapters.receipts import BEGAN, ENDED, receipt

logger = logging.getLogger(__name__)


class PartylineAdapter(WakeSettlement, Adapter):
    kind = "opencode-v2"
    _CLAIMED: set[tuple[str, str]] = set()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._wakes_init()
        self._store: Path | None = None
        self._session_id: str | None = None
        self._claim_seq = 0
        self._seen: set[str] = set()
        self._busy = False

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
        return {"OPENCODE_DB": os.environ.get("OPENCODE_DB", "opencode-v2.db")}

    def _resolve_store(self) -> Path:
        # This diagnostic prints a path only: no server, session, or model call.
        executable = (self.att["command"] or ["opencode2"])[0]
        result = subprocess.run(
            [executable, "debug", "paths", "db"], check=True, capture_output=True,
            text=True, timeout=15, cwd=self.att["cwd"],
            env=dict(os.environ, **self.spawn_env()),
        )
        path = Path(result.stdout.strip())
        if not path.is_absolute():
            raise ValueError("OpenCode v2 must use an absolute, on-disk transcript database")
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
                return session
        return None

    @staticmethod
    def _decode(raw) -> dict:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    async def _poll(self):
        with contextlib.closing(self._connect()) as db:
            rows = db.execute(
                "SELECT id, type, data FROM session_message "
                "WHERE session_id = ? AND seq >= ? ORDER BY seq",
                (self._session_id, self._claim_seq),
            ).fetchall()
        for ident, kind, raw in rows:
            if ident in self._seen:
                continue
            data = self._decode(raw)
            if not data:
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
                            await self.post(self.att["name"], "agent", text)
            elif kind == "user":
                self.observe_claim(raw)
                await self._observe_user_part(raw, part_id=ident)
                if not self._busy:
                    self._busy = True
                    await receipt(self.att, BEGAN)
                self.mark_ready()
            elif kind == "idle":
                if self._busy:
                    self._busy = False
                    await receipt(self.att, ENDED)
                self._schedule_unproved_repool()
            self._seen.add(ident)

    async def _run(self):
        self._store = await asyncio.to_thread(self._resolve_store)
        submitted = False
        for attempt in range(90):
            if not self.alive():
                return
            try:
                self._session_id = self._find_session()
            except sqlite3.Error:
                pass
            if self._session_id:
                self._CLAIMED.add((str(self._store), self._session_id))
                if self.on_cli_session:
                    self.on_cli_session(self._session_id)
                break
            # 2.0.18 can leave --prompt in the composer without submitting it.
            # Only press Enter once it is visibly loaded; readiness and speech
            # still require the nonce in a structured user row, never the screen.
            if not submitted and attempt >= 6 and self._claim_token in self.screen_text():
                await self._write_all(b"\r")
                submitted = True
            await asyncio.sleep(0.5)
        else:
            await self.post("system", "system", f"{self.att['name']}: no claimed OpenCode v2 "
                            "session appeared after 45s; check the terminal for startup errors.")
            return
        while self.alive():
            try:
                await self._poll()
            except sqlite3.Error as exc:
                logger.debug("OpenCode v2 poll skipped: %s", exc)
            await asyncio.sleep(0.5)

    async def stop(self):
        self._CLAIMED.discard((str(self._store), self._session_id))
        await super().stop()
