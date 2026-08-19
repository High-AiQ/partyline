"""Tail Grok's transcript across its atomic resume-time replacement.

Every wait goes through ``adapter._poll``. Tests that stop the tail must
patch that method — not ``adapter.asyncio.sleep`` and not this module's
``asyncio``. Splitting this file out of ``adapter.py`` without that pin
is what filled WSL RAM on 2026-08-19.
"""

from __future__ import annotations

import json
from pathlib import Path

from partyline.adapters.bundled.grok.resume import (
    announce_backlog,
    delivery_plan_matches,
    hold_undelivered_until_wake,
)


async def tail_grok_transcript(adapter, path: Path, handle) -> None:
    """Relay new assistant records from the live transcript file."""
    assert adapter._accounted is not None
    while adapter.alive():
        try:
            with path.open(encoding="utf-8", errors="replace") as file:
                if not delivery_plan_matches(adapter, file):
                    await resync_after_replace(adapter, path)
                    continue
                assistant_index = 0
                adapter.mark_ready()
                while adapter.alive():
                    position = file.tell()
                    line = file.readline()
                    if not line:
                        if adapter._replaced(file, path):
                            await resync_after_replace(adapter, path)
                            break
                        if adapter._restoring_to is not None:
                            pass  # a restore is still refilling this file
                        elif adapter._accounted > assistant_index:
                            # A watermark past the end of the file is a mute,
                            # not a wait: nothing can ever clear it. Refusing
                            # to replay must not become refusing to speak.
                            await resync_after_replace(adapter, path)
                            await adapter._poll()
                            break
                        await adapter._poll()
                        continue
                    if not line.endswith("\n"):
                        file.seek(position)
                        await adapter._poll()
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not adapter._is_assistant_record(record):
                        continue
                    assistant_index += 1
                    if hold_undelivered_until_wake(adapter, assistant_index, record):
                        assistant_index -= 1
                        file.seek(position)
                        await adapter._poll()
                        continue
                    if assistant_index <= adapter._accounted:
                        if assistant_index == adapter._restoring_to:
                            adapter._restoring_to = None  # the refill caught up
                        continue
                    adapter._accounted += 1
                    if assistant_index in adapter._delivery_skip:
                        continue
                    # New speech proves the restore finished.
                    adapter._resume_swap_pending = False
                    adapter._restoring_to = None
                    adapter._assistant_fingerprints.append(adapter._fingerprint(line))
                    await announce_backlog(adapter)
                    await handle(record)
        except OSError:
            if not adapter.alive():
                return
            await adapter._poll()


async def resync_after_replace(adapter, path: Path) -> None:
    """Re-anchor the replay watermark on the replacement file.

    Current server resumes take the delivery-history branch first. The
    fallback remains for callers without that server-owned boundary.

    Grok rewrites chat_history.jsonl when it compacts a session, dropping
    older records, so an ordinal counted against the previous file can
    exceed every index in the new one and mute all future replies. Align
    the records already seen with the start of the replacement — a
    compaction keeps the recent tail verbatim — and resume after the
    overlap. No overlap means nothing was retained, so every record in the
    replacement is genuinely new and must be relayed.

    The replacement is read only once it has stopped changing. Resuming a
    session replaces this file with an empty one and refills it, so a
    replacement read on arrival looks like a rewrite that retained
    nothing — the watermark drops to zero and the whole session is
    relayed to the room. That is the shape observed live on 2026-08-17,
    found by @sol: "no overlap" is only true of a *finished* file. If the
    replacement never settles, the previous watermark stands: relaying
    nothing is recoverable, relaying everything is not.
    """
    if adapter._delivered_bodies is not None:
        await adapter._align_delivery_history(path)
        return
    if adapter._resume_swap_pending:
        # Legacy fallback for callers without delivery history. Current
        # server resumes never assume a restored file is a positional
        # superset; the production incident proved that premise false.
        adapter._resume_swap_pending = False
        adapter._restoring_to = adapter._accounted
        return
    seen = adapter._assistant_fingerprints
    if not seen:
        # Nothing counted has a sequence to align; keep the ordinal.
        return
    incoming = await adapter._settled_assistant_scan(path)
    if not incoming:
        # Once per episode: the tail retries while the position is stale.
        if not adapter._refused_resync:
            adapter._refused_resync = True
            await adapter.post(
                "system", "system",
                f"@{adapter.att['name']}: the Grok transcript was replaced and has not "
                "settled; holding position and retrying rather than replaying history",
            )
        return
    adapter._refused_resync = False
    low, high = 0, min(len(seen), len(incoming))
    while low < high:
        mid = (low + high + 1) // 2
        if seen[-mid:] == incoming[:mid]:
            low = mid
        else:
            high = mid - 1
    adapter._accounted = low
