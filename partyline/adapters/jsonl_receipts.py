"""Per-paste receipts for adapters that read a shared JSONL transcript."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid


def _normal(text: str) -> str:
    return " ".join(text.split())


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_text(part) for part in value)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        return _text(value.get("content", ""))
    return ""


def _user_text(record: dict) -> str | None:
    kind = record.get("type")
    if kind == "attachment":  # Claude mid-turn queued command
        attachment = record.get("attachment") or {}
        if attachment.get("type") == "queued_command":
            return _text(attachment.get("prompt"))
    if kind == "user":  # Claude
        content = (record.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # User records can also contain tool-result blocks. Only direct
            # text parts represent the pasted prompt; nested tool output may
            # echo digest text without being input from the user.
            return "".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            )
        return None
    if kind == "message" and (record.get("message") or {}).get("role") == "user":
        return _text((record.get("message") or {}).get("content"))  # Pi
    if kind == "USER_INPUT" and record.get("source") == "USER_EXPLICIT":
        return _text(record.get("content"))  # Antigravity
    if kind == "user/message":  # DeepSeek Harness persisted ACP transcript
        data = record.get("data") or {}
        if data.get("role") == "user":
            return _text(data.get("content"))
    if kind == "response_item":  # Codex rollout
        item = record.get("payload") or {}
        if item.get("type") == "message" and item.get("role") == "user":
            return _text(item.get("content"))
    payload = record.get("payload") or {}
    if kind == "event_msg" and payload.get("type") == "user_message":
        return _text(payload.get("message"))  # Codex
    if kind == "event_msg" and payload.get("type") == "item_completed":
        item = payload.get("item") or {}
        if item.get("type") == "UserMessage":
            return _text(item.get("content"))
    return None


class JsonlPasteReceipts:
    """Track opted-in adapters' paste ids until a current user record proves them."""

    def _jsonl_receipts_init(self) -> None:
        self._jsonl_receipts: list[dict] = []
        self._jsonl_confirmed_ids: set[int] = set()
        self._jsonl_receipt_event = asyncio.Event()
        self._jsonl_receipt_sequence = 0
        self._pending_paste_marker: str | None = None

    @staticmethod
    def _new_paste_marker() -> str:
        return f"[partyline-paste: {uuid.uuid4().hex}]"

    def _track_jsonl_paste(self, text: str, messages: list[dict], marker: str) -> bool:
        if not getattr(self, "jsonl_paste_receipts", False):
            return False
        ids = [m["id"] for m in messages if isinstance(m.get("id"), int)]
        if not text.strip() or not ids:
            return False
        self._jsonl_receipt_sequence += 1
        # Keep the original receipt eligible while a retry waits in Presence.
        # The retry's actual paste takes ownership of the same ids here.
        wanted = set(ids)
        for receipt in self._jsonl_receipts:
            receipt["ids"] = [mid for mid in receipt["ids"] if mid not in wanted]
        self._jsonl_receipts = [receipt for receipt in self._jsonl_receipts if receipt["ids"]]
        self._jsonl_receipt_event.clear()
        self._jsonl_receipts.append({
            "digest": _normal(text), "ids": ids, "pasted_at": time.time(),
            "sequence": self._jsonl_receipt_sequence,
            "marker": marker, "proven": False,
        })
        return True

    async def _observe_jsonl_paste(self, record: dict) -> None:
        text = _user_text(record)
        if text is None:
            return
        await self.observe_paste_text(text)

    async def observe_paste_text(self, text: str) -> None:
        """Settle a paste from structured user text outside JSONL adapters."""
        observed = _normal(text)
        match = next((receipt for receipt in self._jsonl_receipts
                      if not receipt["proven"] and receipt["marker"] in observed), None)
        if match is not None:
            match["proven"] = True
        confirm = self.att.get("confirm_delivery_ids")
        while confirm is not None:
            kept, progressed = [], False
            for receipt in self._jsonl_receipts:
                if not receipt["proven"] or not await confirm(receipt["ids"]):
                    kept.append(receipt)
                    continue
                self._jsonl_confirmed_ids.update(receipt["ids"])
                self._jsonl_receipt_event.set()
                progressed = True
            self._jsonl_receipts = kept
            if not progressed:
                break

    def prepare_delivery_receipt(self, message_ids: list[int]) -> None:
        self._jsonl_receipt_event.clear()

    async def wait_delivery_received(self, message_ids: list[int]) -> bool:
        wanted = set(message_ids)
        while not wanted <= self._jsonl_confirmed_ids:
            if not self.alive():
                return False
            self._jsonl_receipt_event.clear()
            try:
                await asyncio.wait_for(self._jsonl_receipt_event.wait(), timeout=1)
            except TimeoutError:
                continue
        return True


def _read_batch(file, pending, path, anchor):
    """Read at most 64 KiB of new bytes and decode complete records."""
    current = os.fstat(file.fileno())
    try:
        target = os.stat(path)
    except FileNotFoundError:
        target = current
    if (current.st_dev, current.st_ino) != (target.st_dev, target.st_ino):
        return [], False, "replaced"
    offset = file.tell()
    changed = current.st_size < offset
    if not changed and anchor:
        file.seek(offset - len(anchor))
        changed = file.read(len(anchor)) != anchor
        file.seek(offset)
    if changed:
        file.seek(0)
        pending.clear()
        anchor.clear()
    chunk = file.read(65536)
    if chunk:
        anchor[:] = (anchor + chunk)[-64:]
    start = len(pending)
    pending.extend(chunk)
    lines = []
    end = chunk.rfind(b"\n")
    if end < 0:
        return lines, bool(chunk), None
    end += start
    complete = bytes(pending[:end + 1])
    del pending[:end + 1]
    for raw in complete.split(b"\n")[:-1]:
        line = raw.decode("utf-8", errors="replace") + "\n"
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = None
        lines.append((line, record))
    return lines, bool(chunk), None


async def tail_jsonl(adapter, path: str, handle_line) -> None:
    """Follow a JSONL transcript, scanning existing receipts before ready."""
    adapter._jsonl_tail_path = path
    file = await asyncio.to_thread(open, path, "rb", buffering=0)
    try:
        if await asyncio.to_thread(adapter.recorded_claim, path):
            adapter._mark_claim_proven()
        elif await asyncio.to_thread(adapter.foreign_claim, path):
            await adapter.post(
                "system", "system",
                f"{adapter.att['name']}: not adopting {os.path.basename(path)} — "
                "it carries another attachment's claim marker",
            )
            return
        # Consume existing records before opening readiness: the claim
        # callback may immediately repool an unproved paste. A preclaim user
        # record must get its chance to settle first. Keep the file at EOF so
        # handled records are not replayed after the readiness boundary.
        ready = False
        pending = bytearray()
        anchor = bytearray()
        while True:
            lines, read, change = await asyncio.to_thread(_read_batch, file, pending, path, anchor)
            if change:
                replacement = await asyncio.to_thread(open, path, "rb", buffering=0)
                await asyncio.to_thread(file.close)
                file = replacement
                pending.clear()
                anchor.clear()
                if await asyncio.to_thread(adapter.foreign_claim, path):
                    await adapter.post(
                        "system", "system",
                        f"{adapter.att['name']}: not adopting {os.path.basename(path)} — "
                        "it carries another attachment's claim marker",
                    )
                    return
                continue
            if not lines:
                if read:
                    continue
                partial = bool(pending)
                if not partial and not ready:
                    adapter.mark_ready()
                    ready = True
                if not adapter.alive():
                    return
                await asyncio.sleep(0.3 if partial else 0.5)
                continue
            for line, record in lines:
                if adapter._claim_in_line(line):
                    adapter._mark_claim_proven()
                if isinstance(record, dict):
                    await adapter._observe_jsonl_paste(record)
                    await handle_line(record)
    finally:
        await asyncio.to_thread(file.close)
