"""Durable task reports, with deduplicated and retryable notification delivery."""

import asyncio
import time

from . import reports
from .mention_relay import LIVE, live_manager, post_private
from .orchestrator_sha_check import clip, report_text
from .orchestrator_store import attachment_task, task


async def tell(runtime, ident, text, source=None):
    att = runtime.db.get_attachment(ident)
    if att:
        return await post_private(
            runtime, att['conv_id'], 'system', 'system', f"@{att['name']} {text}",
            audience=ident, source=source)


async def report(runtime, row):
    db = runtime.db
    row = await asyncio.to_thread(task, db, row['conv_id'])
    if row['status'] == 'in_review' and row['reviewer_stall_report_id'] is not None:
        await retry_notify(runtime, row, row['reviewer_stall_report_id'])
    if row['status'] not in ('done', 'approved', 'blocked') and not (
            row['status'] == 'in_review' and row['policy'] == 'captain') and row['stall_stage'] != 3:
        return
    freed = []
    if row['status'] in ('done', 'approved'):
        from .lease_lifecycle import release_for_task
        freed = await release_for_task(runtime, row)  # settled work holds no lease
        if freed:
            await runtime.post_message(
                row['conv_id'], 'system', 'system',
                f"{row['status']}: released the leases held by this task's processes: "
                f"{', '.join(freed)}.")
    if row['report_id'] is None:
        text = await asyncio.to_thread(report_text, db, row)
        if freed:
            note = f"\nReleased leases held by the task's processes: {', '.join(freed)}."
            text = clip(text, reports.MAX_BODY - len(note)) + note
        # Another caller may have reported while the Git checks ran.
        current = task(db, row['conv_id'])
        if current is None:
            return
        if current != row:
            return await report(runtime, current)
        record, wake = reports.add(db, row['root_id'], row['conv_id'], 'task server', text, notify=True)
        db._exec('UPDATE task_reviews SET report_id=? WHERE conv_id=?', (record['id'], row['conv_id']))
    else:
        return await retry_notify(runtime, row, row['report_id'])
    await wake_root(runtime, row, record, wake)


async def retry_notify(runtime, row, report_id):
    """Retry delivery of an existing report, without updating it or waking twice."""
    db = runtime.db
    record = reports.get(db, report_id)
    if record['notified_at'] is not None or record['acknowledged_at'] is not None:
        return
    with db.lock:
        wake = reports._claim_wake(db.conn, record['id'], time.time())
        db.conn.commit()
    record = reports.get(db, record['id'])
    await wake_root(runtime, row, record, wake)


async def wake_root(runtime, row, record, wake):
    db = runtime.db
    if not wake:
        return
    claim = record['notifying_at']
    captain = live_manager(runtime, row['root_id'])
    try:
        if captain is None:
            reports.release_wake_claim(db, record['id'], claim)
            return
        await tell(runtime, captain['id'], reports.report_pointer(record['id'], row['root_id']))
    except Exception:
        reports.release_wake_claim(db, record['id'], claim)
        raise
    reports.mark_notified(db, record['id'], claim)


async def notify_root(runtime, row, text):
    """One notified report that is not the task's terminal one, so it holds no report_id."""
    body = clip(f"Task {row['conv_id']}: {text}", reports.MAX_BODY)
    record, wake = reports.add(runtime.db, row['root_id'], row['conv_id'], 'task server',
                               body, notify=True)
    await wake_root(runtime, row, record, wake)


async def worker_lost(runtime, att_id, value):
    """Tell the parent captain when an undelivered task worker disappears."""
    db = runtime.db
    row = attachment_task(db, att_id)
    att = db.get_attachment(att_id)
    if not row or not att or att['status'] != value:
        return  # a stale activation cannot report over its live replacement
    implementer = row['implementer_id'] == att_id
    reviewer = row['reviewer_id'] == att_id and row['policy'] not in ('none', 'captain')
    if implementer and row['status'] not in ('implementing', 'idle'):
        return  # request_review, blocked or a terminal result was already delivered
    if not implementer and not (reviewer and row['status'] == 'in_review'):
        return
    role = 'implementer' if implementer else 'reviewer'
    line = db.get_conversation(row['conv_id']) or {}
    text = (f"task «{line.get('name') or row['conv_id']}» ({row['conv_id']}): {role} "
            f"@{att['name']} {value} before delivering; restart_{role} to resume.")
    captain = live_manager(runtime, row['root_id'])
    if captain:
        await tell(runtime, captain['id'], text)
    else:
        await runtime.post_message(row['root_id'], 'system', 'system', text)


async def spawn_refused(runtime, row, detail, *, implementer=False):
    role = 'implementer' if implementer else 'reviewer'
    retry = 'create_task with the same assignment' if implementer else 'request_review'
    text = f"{role} admission/spawn refused: {detail}. Retry {retry} after capacity is available."
    await tell(runtime, row['implementer_id'], text)
    from .hierarchy import lead_attachment
    captain = lead_attachment(runtime.db, row['root_id'])
    if captain:
        await tell(runtime, captain['id'], f"task {row['conv_id']}: {text}")
    else:
        await runtime.post_message(row['root_id'], 'system', 'system', text)


def peer(db, finisher):
    row = task(db, finisher['conv_id'])
    if not row or row['status'] in ('approved', 'done') or row['policy'] in ('none', 'captain'):
        return None
    ident = row['reviewer_id'] if finisher['id'] == row['implementer_id'] else row['implementer_id']
    other = db.get_attachment(ident) if ident else None
    return other if other and other['status'] in LIVE else None


def handed_to(runtime, source, target):
    returns = getattr(runtime, 'returns', None)
    if returns is not None:
        returns.handed_to(source, target)
