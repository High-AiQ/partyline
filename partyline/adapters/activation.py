"""Per-activation identity: environment, claim markers, and receipts.

An activation is the process this server spawned for one attachment, and
several facts belong to it alone: extra environment that isolates the
CLI's state per attachment, the claim token that names this activation in
its own transcript, the freshness boundary that separates a resumed
process's new records from replayed history, and the staged
startup-delivery receipt. They live in this mixin so the base runtime
stays small and every adapter inherits the same notions.
"""

from __future__ import annotations

import uuid

# The marker every transcript adapter pastes with its briefing and each
# wake until a transcript records it. A session that carries it is this
# activation's by construction — nothing else writes this pty, and no
# other activation shares the nonce.
CLAIM_PREFIX = "[partyline-claim: "

# A claim marker is recorded near the top of a session, in the briefing or
# the first wake. Bounding the scan keeps a stranger's multi-megabyte
# transcript from being read in full on every poll.
SCAN_BYTES = 512 * 1024


class Activation:
    """Hooks and state scoped to one running activation of an adapter."""

    _nonce: str = ""
    _claim_proven: bool = False

    def spawn_env(self) -> dict[str, str]:
        """Extra environment for the spawned process, by activation.

        Adapters that isolate per-attachment CLI state — a vendor home of
        their own — declare it here instead of editing ``os.environ`` or
        duplicating the pty spawn in ``start()``.
        """
        return {}

    def pastes_claim(self) -> bool:
        """Whether this attachment's harness must claim a transcript by content.

        Mirrors the ``transcript`` manifest capability (the single source
        of truth is the manifest; `partyline.adapter_capabilities` reads
        the same field server-side).
        """
        capabilities = (self.att.get("adapter_metadata") or {}).get("capabilities") or {}
        return bool(capabilities.get("transcript"))

    @property
    def _claim_token(self) -> str:
        """The one string that names this activation and no other.

        Identity cannot be inferred — not from spawn order, session order,
        or any clock — so it is stated: the token is pasted into this pty
        with the briefing and with every wake until a transcript records
        it, and the session that recorded it is ours by construction. It
        is per-activation, not per-attachment: an attachment id is stable
        across resumes, so every transcript the attachment ever wrote
        still carries an id-based token — a fresh nonce each run makes
        only this activation's own sessions eligible.
        """
        if not self._nonce:
            self._nonce = uuid.uuid4().hex[:12]
        return f"{CLAIM_PREFIX}{self.att['id']}/{self._nonce}]"

    def _with_claim(self, text: str) -> str:
        """A paste, carrying the claim token until a transcript proves it."""
        if not self.pastes_claim() or self._claim_proven or not text.strip():
            return text
        return f"{text}\n\n{self._claim_token}"

    def _claim_in_line(self, line) -> bool:
        """Whether one raw transcript line records this activation's token."""
        return bool(self._nonce) and self._claim_token in line

    def observe_claim(self, line) -> None:
        """Mark this activation proven when a transcript line names it.

        Adapters with private tails (not the shared ``_tail_jsonl``) call
        this with each complete line they read, so the speech gate opens
        from their own session exactly as it does from the shared tail.
        """
        if not isinstance(line, str):
            line = str(line)
        if self._claim_in_line(line):
            self._mark_claim_proven()

    def _mark_claim_proven(self) -> None:
        """This activation's own token has been observed in its transcript."""
        self._claim_proven = True

    def recorded_claim(self, path: str) -> bool:
        """Whether this transcript file records this activation's token.

        The scan is over raw lines, so it holds for every vendor's record
        vocabulary; the token's characters never need JSON escaping.
        """
        if not self._nonce:
            return False
        try:
            with open(path, encoding="utf-8", errors="replace") as file:
                scanned = 0
                for line in file:
                    scanned += len(line)
                    if scanned > SCAN_BYTES:
                        return False
                    if self._claim_token in line:
                        return True
        except OSError:
            return False
        return False

    def foreign_claim(self, path: str) -> bool:
        """Whether this file records another *attachment's* claim marker.

        A marker naming a different attachment id means the file belongs
        to a pty we do not own — adopting it is how two same-directory
        attachments once traded speech, so the shared tail refuses it out
        loud rather than relay a stranger's words. Markers naming this
        attachment (a prior activation's nonce, e.g. the session a resume
        reopens) are not foreign: the resume is legitimate, and the speech
        gate still holds until this activation's own nonce appears. A file
        with no marker at all is not foreign either — it is simply not
        proven yet.
        """
        if not self.pastes_claim():
            return False
        foreign = ours = False
        try:
            with open(path, encoding="utf-8", errors="replace") as file:
                scanned = 0
                for line in file:
                    scanned += len(line)
                    if scanned > SCAN_BYTES:
                        break
                    if self._claim_in_line(line):
                        ours = True
                    start = 0
                    while (idx := line.find(CLAIM_PREFIX, start)) != -1:
                        att_id, sep, _ = line[idx + len(CLAIM_PREFIX):].partition("/")
                        if sep and att_id and att_id != str(self.att.get("id", "")):
                            foreign = True
                        start = idx + 1
        except OSError:
            return False
        return foreign and not ours

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

    def mark_startup_delivery_received(self) -> None:
        """A staged startup digest appeared as structured process input."""
        if self._startup_delivery_result is None and not self._stopping:
            self._startup_delivery_result = True
            self._startup_delivery.set()

    async def wait_startup_delivery_received(self) -> bool:
        """Wait for structured receipt, or for the process to exit first."""
        await self._startup_delivery.wait()
        return self._startup_delivery_result is True
