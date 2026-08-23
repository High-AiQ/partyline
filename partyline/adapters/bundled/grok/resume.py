"""Align Grok's mutable transcript with speech Partyline actually delivered.

An ordinal in a CLI-owned file is not a durable watermark: resume and
compaction may put the same records at different positions.  Partyline's own
message history is durable, but message bodies cannot be globally deduplicated
because a process may legitimately repeat one.  The safe boundary is a unique
sequence at the end of delivered speech.  Within that boundary an exact LCS
matches occurrences in order; unmatched transcript records are the backlog.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable
from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
from typing import TypeVar

from .markers import match_marked_records, unsafe_resume_backlog
from .transcript import AssistantRecord

MAX_ANCHOR = 64
MAX_MATCH_PAIRS = 100_000
Scan = TypeVar("Scan")


class AlignmentError(ValueError):
    """The restored transcript has no single evidence-backed resume boundary."""


@dataclass(frozen=True)
class DeliveryAlignment:
    """Assistant ordinals already delivered, plus the unmatched flush size."""

    skip: frozenset[int]
    backlog: int
    anchor_length: int


def file_identity(path: Path) -> tuple[int, int, int] | None:
    """What the transcript path names right now, or ``None`` if unreadable."""
    try:
        status = path.stat()
    except OSError:
        return None
    return (status.st_ino, status.st_size, status.st_mtime_ns)


async def settled_snapshot(
    adapter, path: Path, scan: Callable[[Path], Scan | None]
) -> tuple[Scan, tuple[int, int, int]] | None:
    """Read a transcript only after one identity remains stable around the scan."""
    previous = None
    stable_for = 0.0
    waited = 0.0
    while adapter.alive() and waited < adapter.SETTLE_TIMEOUT:
        current = adapter._identity(path)
        if current is None:
            return None
        if current == previous:
            stable_for += adapter.POLL_SECONDS
            if stable_for >= adapter.SETTLE_SECONDS:
                scanned = scan(path)
                if scanned is not None and adapter._identity(path) == current:
                    return scanned, current
                previous, stable_for = None, 0.0
        else:
            previous, stable_for = current, 0.0
        await adapter._poll()
        waited += adapter.POLL_SECONDS
    return None


async def settled_scan(adapter, path: Path, scan: Callable[[Path], Scan | None]) -> Scan | None:
    snapshot = await settled_snapshot(adapter, path, scan)
    return None if snapshot is None else snapshot[0]


async def align_delivery_history(adapter, path: Path) -> bool:
    """Replace a file ordinal with Partyline's occurrence-aware boundary."""
    adapter._backlog_to_record = 0
    snapshot = await settled_snapshot(adapter, path, adapter._assistant_records)
    if snapshot is None or not snapshot[0]:
        return False
    records, identity = snapshot
    try:
        aligned = align_delivered_sequence(records, adapter._delivered_bodies or [])
    except AlignmentError as exc:
        # Ambiguity is a decision, not a guessed watermark. Skip this
        # unverifiable flush but leave the live tail able to relay whatever is
        # appended next; refusing replay must not permanently mute it.
        adapter._accounted = len(records)
        adapter._delivery_skip.clear()
        # A refusal skips the restored history, so there is no flush to
        # announce. Leaving a count from an earlier alignment here would
        # attach a stale number to whatever relays next.
        adapter._pending_backlog = 0
        adapter._delivery_plan = (
            identity, tuple(record.fingerprint for record in records)
        )
        if not adapter._refused_resync:
            adapter._refused_resync = True
            await adapter.post(
                "system", "system",
                f"{adapter.att['name']}: {exc}; skipped restored history to avoid "
                "replay, but new speech will still relay",
            )
        return True
    skip = set(aligned.skip)
    marked = match_marked_records(
        records, skip, adapter._delivered_transcript_records,
        adapter._legacy_relayed_bodies,
    )
    skip.update(marked)
    backlog = max(0, aligned.backlog - len(marked))
    if unsafe_resume_backlog(backlog, len(records)):
        # A small hatch repairs muted speech. A large one is evidence that the
        # mutable transcript no longer aligns; replaying it can execute hours
        # of old mentions as new instructions. Refuse and tail only appends.
        adapter._accounted = len(records)
        adapter._delivery_skip.clear()
        adapter._pending_backlog = 0
        adapter._backlog_to_record = 0
        adapter._delivery_plan = (
            identity, tuple(record.fingerprint for record in records)
        )
        if not adapter._refused_resync:
            adapter._refused_resync = True
            await adapter.post(
                "system", "system",
                f"{adapter.att['name']}: resume backlog of {backlog} looks like "
                "misaligned history — skipped; new speech will relay",
            )
        return True
    adapter._accounted = 0
    adapter._delivery_skip = skip
    adapter._delivery_plan = (
        identity, tuple(record.fingerprint for record in records)
    )
    adapter._refused_resync = False
    adapter._pending_backlog = backlog
    adapter._backlog_to_record = adapter._pending_backlog
    return True


async def announce_backlog(adapter) -> None:
    """Say how much of a resume's flush had never reached the room before.

    A process that was muted keeps working, and everything it said in that
    window arrives at once when the mute ends. The words are genuine and worth
    delivering, but they can answer a room that has moved on — during one
    incident a lead came close to reverting merged work on instructions that
    read as current.

    The claim is deliberately narrow. ``backlog`` proves *previously
    undelivered*, not *old*: the transcript carries no timestamps, and a
    record may have been produced after the spawn but before alignment. The
    notice therefore says what was measured and leaves age to the reader.

    It is said as the first held record is relayed, not when the alignment is
    computed. Announcing a flush that a never-woken process never delivers
    would be its own false statement.
    """
    backlog, adapter._pending_backlog = adapter._pending_backlog, 0
    if backlog <= 0:
        return  # nothing was held back; a notice would be noise
    await adapter.post(
        "system", "system",
        f"{adapter.att['name']}: relaying {backlog} message(s) that never "
        "reached this line before now — they may answer an older state of it",
    )


def delivery_plan_matches(adapter, file) -> bool:
    """Whether a held file is the one whose delivered sequence was aligned."""
    planned = adapter._delivery_plan
    if planned is None:
        return True
    identity, fingerprints = planned
    try:
        current = os.fstat(file.fileno())
        if current.st_ino != identity[0] or current.st_size < identity[1]:
            return False
        records = adapter._assistant_records(Path(file.name))
        if records is None or len(records) < len(fingerprints):
            return False
        return tuple(
            record.fingerprint for record in records[:len(fingerprints)]
        ) == fingerprints
    except OSError:
        return False


def hold_undelivered_until_wake(adapter, assistant_index: int, record: object) -> bool:
    """Do not turn suppressed resume output into falsely delivered history."""
    return (
        adapter._delivered_bodies is not None
        and assistant_index not in adapter._delivery_skip
        and adapter._assistant_text(record) is not None
        and adapter._silent_until_wake
    )


def _unique_suffix_anchor(
    transcript: list[str], delivered: list[str]
) -> tuple[int, int]:
    """Return ``(transcript start, length)`` for one unique delivered suffix."""
    candidates = [
        index for index, body in enumerate(transcript) if body == delivered[-1]
    ]
    best: tuple[int, int] | None = None
    for length in range(1, min(MAX_ANCHOR, len(transcript), len(delivered)) + 1):
        expected = delivered[-length]
        candidates = [
            end for end in candidates
            if end >= length - 1 and transcript[end - length + 1] == expected
        ]
        if not candidates:
            break
        if len(candidates) == 1:
            best = (candidates[0] - length + 1, length)
    if best is None:
        raise AlignmentError("delivered speech has no unique suffix in the transcript")
    return best


def _lcs_right_indices(left: list[str], right: list[str]) -> set[int]:
    """Exact Hunt–Szymanski LCS, returning matched indices in ``right``."""
    if left == right:
        return set(range(len(right)))
    positions: dict[str, list[int]] = defaultdict(list)
    for index, body in enumerate(right):
        positions[body].append(index)
    pairs = sum(len(positions.get(body, ())) for body in left)
    if pairs > MAX_MATCH_PAIRS:
        raise AlignmentError(
            f"history alignment has {pairs} occurrence pairs; refusing an unsafe guess"
        )
    tails: list[int] = []
    tail_nodes: list[int] = []
    node_positions: list[int] = []
    node_previous: list[int] = []
    for body in left:
        # Descending positions ensure one delivered occurrence contributes at
        # most once. Equal-body ties choose deterministically; only which
        # indistinguishable occurrence is matched changes, never relay order.
        for position in reversed(positions.get(body, ())):
            length = bisect_left(tails, position)
            previous = tail_nodes[length - 1] if length else -1
            node = len(node_positions)
            node_positions.append(position)
            node_previous.append(previous)
            if length == len(tails):
                tails.append(position)
                tail_nodes.append(node)
            else:
                tails[length] = position
                tail_nodes[length] = node

    matched: set[int] = set()
    node = tail_nodes[-1] if tail_nodes else -1
    while node >= 0:
        matched.add(node_positions[node])
        node = node_previous[node]
    return matched


def align_delivered_sequence(
    records: list[AssistantRecord], delivered: list[str]
) -> DeliveryAlignment:
    """Classify the restored transcript using Partyline's delivered sequence.

    The unique suffix is the authoritative boundary.  Matching the prefix by
    occurrence prevents a repeated body from becoming global deduplication;
    an identical record appended after this one resume flush remains new.
    """
    postable = [
        (assistant_index, record.body)
        for assistant_index, record in enumerate(records, start=1)
        if record.body is not None
    ]
    if not delivered or not postable:
        raise AlignmentError("resume history has no delivered sequence to align")
    bodies = [body for _, body in postable]
    anchor_start, anchor_length = _unique_suffix_anchor(bodies, delivered)
    delivered_prefix = delivered[:-anchor_length]
    transcript_prefix = bodies[:anchor_start]
    matched = _lcs_right_indices(delivered_prefix, transcript_prefix)
    matched.update(range(anchor_start, anchor_start + anchor_length))
    skipped = frozenset(postable[index][0] for index in matched)
    return DeliveryAlignment(
        skip=skipped,
        backlog=len(postable) - len(skipped),
        anchor_length=anchor_length,
    )
