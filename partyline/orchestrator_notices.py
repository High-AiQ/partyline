"""Durable task reports, with deduplicated and retryable notification delivery."""

import time

from . import reports
from .mention_relay import LIVE, live_manager, post_private
from .orchestrator_sha_check import clip, report_text
from .orchestrator_store import task


async def tell(runtime, ident, text, source=None):
    att = runtime.db.get_attachment(ident)
    if att:
        return await post_private(
            runtime, att['conv_id'], 'system', 'system', f"@{att['name']} {text}",
            audience=ident, source=source)


async def report(runtime, row):
    db = runtime.db
    row = task(db, row['conv_id'])
    if row['status'] not in ('done', 'approved', 'blocked') and not (
            row['status'] == 'in_review' and row['policy'] == 'captain') and row['stall_stage'] != 3:
        return
    if row['report_id'] is None:
        text = report_text(db, row)
        record, wake = reports.add(db, row['root_id'], row['conv_id'], 'task server', text, notify=True)
        db._exec('UPDATE task_reviews SET report_id=? WHERE conv_id=?', (record['id'], row['conv_id']))
    else:
        record = reports.get(db, row['report_id'])
        if record['notified_at'] is not None:
            return
        # Retry only the existing report, including after an acknowledgement.
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
        await tell(runtime, captain['id'], f"needs attention: report {record['id']}")
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
