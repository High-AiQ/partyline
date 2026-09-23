"""Partyline adapter for DeepSeek Harness's long-lived ACP stdio server.

The child is a real ``dsh --profile acp`` process in Partyline's PTY. ACP is
newline-delimited JSON-RPC, not a terminal composer, so this adapter writes
protocol frames followed by ``\\n`` instead of wrapping them in bracketed paste
markers. Chat speech comes only from the claimed plain ``session.v3.jsonl``;
ACP ``session/update`` notifications are deliberately not relayed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tty
from pathlib import Path

from partyline.adapters import Adapter
from partyline.adapters.receipts import BEGAN, ENDED, receipt

logger = logging.getLogger(__name__)


class PartylineAdapter(Adapter):
    kind = "deepseek"
    _CLAIMED: set[str] = set()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_id: str | None = None
        self._transcript: Path | None = None
        self._wire_buffer = ""
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._tail_task: asyncio.Task | None = None
        self._seen: set[int] = set()

    @property
    def _sessions_root(self) -> Path:
        home = Path(os.environ.get("DSH_HOME", "~/.dsh")).expanduser()
        return home / "sessions"

    def build_command(self) -> list[str]:
        command = list(self.att["command"]) or ["dsh", "--profile", "acp"]
        for index, argument in enumerate(command[:-1]):
            if argument == "--patch":
                command[index + 1] = os.path.expanduser(os.path.expandvars(command[index + 1]))
        return command

    def _prepare_pty(self) -> None:
        """Disable terminal echo/canonical translation before ACP framing starts."""
        if self.master is not None:
            tty.setraw(self.master)

    async def stop(self):
        if self._tail_task:
            self._tail_task.cancel()
        if self._transcript:
            self._CLAIMED.discard(str(self._transcript))
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        await super().stop()

    async def _write_frame(self, frame: dict):
        # ACP's line framing is required: bracketed-paste escapes are not JSON.
        await self._write_all((json.dumps(frame, separators=(",", ":")) + "\n").encode())

    async def _request(self, method: str, params: dict) -> dict:
        self._request_id += 1
        request_id = self._request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write_frame({"jsonrpc": "2.0", "id": request_id,
                                     "method": method, "params": params})
            result = await asyncio.wait_for(future, timeout=900)
            if not isinstance(result, dict):
                raise RuntimeError(f"dsh ACP {method} returned a non-object result")
            return result
        finally:
            self._pending.pop(request_id, None)

    async def _send_request(self, method: str, params: dict) -> None:
        """Put a request on the wire and return; its result is not waited for.

        ``session/prompt`` answers only when the model's whole turn ends —
        minutes for a local 27B model — and a delivery that waited for it held
        the sender's HTTP request open the entire time: the composer sat on
        "uploading…" long after the message and image were in the chat. The
        turn's end is observed from the transcript; the response is noise
        unless it is an error, which is logged.
        """
        self._request_id += 1
        request_id = self._request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        def settled(done: asyncio.Future) -> None:
            self._pending.pop(request_id, None)
            if not done.cancelled() and done.exception() is not None:
                logger.warning("dsh ACP %s failed for %s: %s",
                               method, self.att.get("name"), done.exception())

        future.add_done_callback(settled)
        await self._write_frame({"jsonrpc": "2.0", "id": request_id,
                                 "method": method, "params": params})

    async def on_output(self, data: bytes):
        self._wire_buffer += data.decode("utf-8", errors="replace")
        while "\n" in self._wire_buffer:
            line, self._wire_buffer = self._wire_buffer.split("\n", 1)
            try:
                frame = json.loads(line.rstrip("\r"))
            except json.JSONDecodeError:
                continue
            if not isinstance(frame, dict):
                continue
            request_id = frame.get("id")
            if isinstance(request_id, int) and request_id in self._pending:
                future = self._pending[request_id]
                if "error" in frame:
                    error = frame["error"]
                    detail = (
                        error.get("message", "unknown ACP error")
                        if isinstance(error, dict) else str(error)
                    )
                    if not future.done():
                        future.set_exception(RuntimeError(detail))
                elif "result" in frame and not future.done():
                    future.set_result(frame["result"])
            elif frame.get("method") == "session/request_permission":
                await self._answer_permission(frame)

    async def _answer_permission(self, frame: dict):
        params = frame.get("params") or {}
        options = params.get("options") or []
        selected = next(
            (
                item for item in options
                if isinstance(item, dict) and str(item.get("optionId", "")).startswith("allow")
            ),
            None,
        )
        if frame.get("id") is None:
            return
        if selected is None:
            outcome = {"outcome": "cancelled"}
        else:
            outcome = {"outcome": "selected", "optionId": selected["optionId"]}
        await self._write_frame({"jsonrpc": "2.0", "id": frame["id"],
                                 "result": {"outcome": outcome}})

    def _find_log(self, session_id: str) -> Path | None:
        root = self._sessions_root
        plain = sorted(root.glob(f"**/{session_id}/session.v*.jsonl"))
        if plain:
            path = plain[-1]
            if str(path) in self._CLAIMED:
                return None
            self._CLAIMED.add(str(path))
            return path
        compressed = list(root.glob(f"**/{session_id}/session.v*.jsonl.zstd"))
        if compressed:
            raise RuntimeError("DSH session persistence is compressed; set compression: none")
        return None

    @staticmethod
    def _snapshot_sequences(path: Path) -> set[int]:
        seen = set()
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and isinstance(value.get("seq"), int):
                    seen.add(value["seq"])
        except OSError:
            pass
        return seen

    async def _wait_for_log(self) -> Path:
        while self.alive():
            if path := self._find_log(self._session_id or ""):
                return path
            await asyncio.sleep(0.5)
        raise RuntimeError("dsh exited before creating its session transcript")

    async def _run(self):
        try:
            self._prepare_pty()
            await self._request("initialize", {
                "protocolVersion": 1, "clientCapabilities": {},
                "clientInfo": {"name": "partyline", "version": "1"},
            })
            if self.resume:
                self._session_id = str(self.att.get("cli_session") or "")
                if not self._session_id:
                    raise ValueError("dsh resume requires the stored ACP session id")
                existing = self._find_log(self._session_id)
                if existing is None:
                    raise RuntimeError(
                        "stored dsh session transcript is missing or already claimed"
                    )
                self._seen = self._snapshot_sequences(existing)
                await self._request("session/resume", {
                    "sessionId": self._session_id, "cwd": self.att["cwd"], "mcpServers": [],
                })
                self._transcript = existing
            else:
                result = await self._request("session/new", {
                    "cwd": self.att["cwd"], "mcpServers": [],
                })
                self._session_id = str(result.get("sessionId") or "")
                if not self._session_id:
                    raise RuntimeError("dsh ACP session/new returned no session id")
                if self.on_cli_session:
                    self.on_cli_session(self._session_id)
                await self._request("session/prompt", {
                    "sessionId": self._session_id,
                    "prompt": [{"type": "text", "text": self.briefing()}],
                })
                self._transcript = await self._wait_for_log()
            self.mark_ready()
            self._tail_task = asyncio.create_task(self._tail())
            await self._tail_task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._mark_not_ready()
            await self.post("system", "system", f"{self.att['name']}: ACP setup failed — {exc}")

    async def _tail(self):
        assert self._transcript is not None
        with self._transcript.open(encoding="utf-8", errors="replace") as file:
            while self.alive():
                position = file.tell()
                line = file.readline()
                if not line:
                    file.seek(position)
                    await asyncio.sleep(0.5)
                    continue
                if not line.endswith("\n"):
                    file.seek(position)
                    await asyncio.sleep(0.3)
                    continue
                self.observe_claim(line)
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    await self._handle_record(record)

    async def _handle_record(self, record: dict):
        seq = record.get("seq")
        if not isinstance(seq, int) or seq in self._seen:
            return
        self._seen.add(seq)
        kind = record.get("type")
        if kind == "turn/start":
            await receipt(self.att, BEGAN)
        elif kind == "turn/end":
            await receipt(self.att, ENDED)
        elif kind == "assistant/message":
            message = (record.get("data") or {}).get("message") or {}
            if message.get("role") != "assistant":
                return
            body = "\n\n".join(
                str(block.get("text", "")) for block in message.get("content") or []
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and block.get("text", "").strip()
                )
            )
            if body.strip():
                await self.post(self.att["name"], "agent", body)

    async def deliver(self, messages: list[dict]):
        if not self._session_id:
            raise RuntimeError("dsh ACP session is not ready")
        self._silent_until_wake = False
        await self._send_request("session/prompt", {
            "sessionId": self._session_id,
            "prompt": [{"type": "text", "text": self.format_digest(messages)}],
        })
