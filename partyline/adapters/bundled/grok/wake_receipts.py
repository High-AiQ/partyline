"""Credit Grok wakes only after its structured transcript records the input."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass

from . import offloaded_prompt
from .transcript import user_input

# Receipt diagnostics. The unresolved failure is an ordering question — which
# index was seeded, where the paste boundary sat, which record arrived, and
# whether a match became a credit — and none of that needs the text. Bodies
# and credentials are never logged; a digest is identified by a short
# fingerprint of its normalized form.
#
# Off by default, because the server configures only uvicorn's loggers: the
# root logger has no handler, so an INFO record from this module is discarded
# and an operator would see nothing. `PARTYLINE_RECEIPT_DIAGNOSTICS=1` in the
# server's environment attaches a handler and lowers the level for this module
# alone, which is what makes the evidence reachable without turning every
# partyline logger up in production.
#
# The check runs when a tracker is constructed, not at import: the supported
# way to set this is a line in the deployment checkout's `.env`, and `load_dotenv()`
# runs after this module has already been imported. Configuring at import time
# would read the environment before the file that sets it had been loaded.
logger = logging.getLogger(__name__)
DIAGNOSTICS_ENV = "PARTYLINE_RECEIPT_DIAGNOSTICS"


def _configure_diagnostics() -> None:
    if os.environ.get(DIAGNOSTICS_ENV, "").strip() in ("", "0", "false", "no"):
        return
    if any(getattr(h, "_partyline_receipts", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler._partyline_receipts = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def fingerprint(text: str) -> str:
    """Eight hex characters of the normalized digest. Not reversible."""
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:8]


def _who(adapter) -> str:
    """Which attachment, and which activation of it, is speaking.

    Two Grok sessions produce interleaved lines otherwise, and a replaced
    activation is a different process telling the same story.
    """
    att = getattr(adapter, "att", None) or {}
    return f"att={att.get('id')} owner={att.get('runtime_owner')}"


@dataclass
class PendingWake:
    digest: str
    message_ids: tuple[int, ...]
    after_prompt: int
    confirmed: bool = False


def _matches(content: str, digest: str) -> bool:
    """Match exactly through harmless transcript whitespace reflow."""
    return bool(digest.strip()) and " ".join(digest.split()) == " ".join(content.split())


class WakeReceipts:
    """Ordered pasted wakes and the newest transcript prompt already observed."""

    def __init__(self) -> None:
        _configure_diagnostics()
        self.prompt_index = -1
        self.pending: list[PendingWake] = []
        self._expected_waits: set[tuple[int, ...]] = set()
        self._waiters: dict[tuple[int, ...], asyncio.Event] = {}
        self._results: dict[tuple[int, ...], bool] = {}

    def seed(self, prompt_index: int, adapter=None) -> None:
        """Take the transcript's newest prompt as the anti-replay mark.

        The adapter is optional only so an existing caller cannot break; pass
        it. This is the event the unresolved failure turns on, and a seed line
        that cannot be attributed to an attachment and activation is the one
        line in the set that answers nothing.
        """
        previous = self.prompt_index
        self.prompt_index = max(self.prompt_index, prompt_index)
        logger.info(
            "wake receipt: %s seed from=%s to=%s applied=%s pending=%d",
            _who(adapter), previous, prompt_index, self.prompt_index,
            len(self.pending),
        )

    def expect_wait(self, message_ids: list[int]) -> None:
        self._expected_waits.add(tuple(message_ids))

    async def deliver(self, adapter, messages: list[dict]) -> bool | None:
        message_ids = tuple(
            message["id"] for message in messages if isinstance(message.get("id"), int)
        )
        if message_ids and any(wake.message_ids == message_ids for wake in self.pending):
            return False
        digest = adapter.format_digest(messages)
        if not message_ids:
            if digest.strip():
                await adapter.send_keys(digest)
            adapter._silent_until_wake = False
            return None
        pending = PendingWake(digest, message_ids, self.prompt_index)
        self.pending.append(pending)
        logger.info(
            "wake receipt: %s paste boundary=%s digest=%s len=%d messages=%d",
            _who(adapter), self.prompt_index, fingerprint(digest),
            len(digest), len(message_ids),
        )
        if message_ids in self._expected_waits:
            self._expected_waits.remove(message_ids)
            self._waiters[message_ids] = asyncio.Event()
        try:
            if digest.strip():
                await adapter.send_keys(digest)
        except BaseException:
            self.pending.remove(pending)
            self._waiters.pop(message_ids, None)
            raise
        adapter._silent_until_wake = False
        return False

    def _full_content(self, adapter, prompt_index: int, content: str) -> str:
        """Replace an offloaded preview with the text the session recorded.

        Grok stores a large paste as a truncated preview plus a pointer to
        ``prompts/prompt_<ordinal>.txt``; the preview cannot equal the digest,
        so a delivered wake went uncredited. Resolution is confined to that one
        session-owned file for that one ordinal — see ``offloaded_prompt``.
        Anything unresolvable keeps the preview and so credits nothing.
        """
        if not offloaded_prompt.is_offloaded(content):
            return content
        getter = getattr(adapter, "_transcript", None)
        transcript = getter() if callable(getter) else None
        resolved = offloaded_prompt.resolve(content, prompt_index, transcript)
        logger.info(
            "wake receipt: %s record %s offloaded outcome=%s",
            _who(adapter), prompt_index, "unresolved" if resolved is None else "resolved",
        )
        return content if resolved is None else resolved

    async def observe(self, adapter, record: object) -> None:
        parsed = user_input(record)
        if parsed is None:
            return
        prompt_index, content = parsed
        if prompt_index <= self.prompt_index:
            # The anti-replay rule, unchanged: a record at or below the mark is
            # history and may not confirm anything. Logged because this is the
            # branch that silently ends a wake's chance of ever being credited.
            logger.info(
                "wake receipt: %s record %s not after mark %s — anti-replay, "
                "unconfirmed pending=%d",
                _who(adapter), prompt_index, self.prompt_index,
                sum(1 for wake in self.pending if not wake.confirmed),
            )
            return
        self.prompt_index = prompt_index
        content = self._full_content(adapter, prompt_index, content)
        matched_index: int | None = None
        for index, wake in enumerate(self.pending):
            if (
                not wake.confirmed
                and wake.after_prompt < prompt_index
                and _matches(content, wake.digest)
            ):
                wake.confirmed = True
                matched_index = index
                break
        # Matching is not crediting: the cursor only moves if the delivery
        # callback accepts, and those are separate failures with separate fixes.
        logger.info(
            "wake receipt: %s record %s observed content=%s matched=%s",
            _who(adapter), prompt_index, fingerprint(content),
            "none" if matched_index is None else f"wake#{matched_index}",
        )
        if matched_index is None:
            for index, wake in enumerate(self.pending):
                if not wake.confirmed:
                    logger.info(
                        "wake receipt: %s unmatched wake#%d boundary=%s digest=%s "
                        "same_content=%s after_paste=%s",
                        _who(adapter), index, wake.after_prompt,
                        fingerprint(wake.digest),
                        _matches(content, wake.digest),
                        wake.after_prompt < prompt_index,
                    )

        # A later cumulative digest proves an earlier paste was skipped: its
        # structured user record arrived first, and it carries every earlier
        # message id. Mark those predecessors covered, but never jump a
        # disjoint exact-id batch.
        if matched_index:
            matched_ids = set(self.pending[matched_index].message_ids)
            predecessors = self.pending[:matched_index]
            if all(set(wake.message_ids) <= matched_ids for wake in predecessors):
                for wake in predecessors:
                    wake.confirmed = True

        confirmed = 0
        message_ids: list[int] = []
        for wake in self.pending:
            if not wake.confirmed:
                break
            confirmed += 1
            message_ids.extend(wake.message_ids)
        if not confirmed:
            return
        credit = adapter.att.get("confirm_delivery_ids")
        ordered_ids = list(dict.fromkeys(message_ids))
        granted = await credit(ordered_ids) if credit is not None else None
        logger.info(
            "wake receipt: %s credit wakes=%d ids=%d outcome=%s",
            _who(adapter), confirmed, len(ordered_ids),
            "absent" if credit is None else ("granted" if granted else "refused"),
        )
        if granted:
            for wake in self.pending[:confirmed]:
                if waiter := self._waiters.get(wake.message_ids):
                    self._results[wake.message_ids] = True
                    waiter.set()
            del self.pending[:confirmed]

    async def wait(self, message_ids: list[int]) -> bool:
        key = tuple(message_ids)
        waiter = self._waiters.get(key)
        if waiter is None:
            return False
        await waiter.wait()
        self._waiters.pop(key, None)
        return self._results.pop(key, False)

    def stop(self) -> None:
        self._expected_waits.clear()
        for key, waiter in self._waiters.items():
            self._results[key] = False
            waiter.set()
