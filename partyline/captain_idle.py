"""Event-driven warning when a captain ends a turn with stranded work."""

import json
import logging

from . import features
from .approval_bubble import pending_approval_rows
from .hierarchy import ancestors, descendants, lead_attachment
from .mention_relay import LIVE, post_private
from .orchestrator_wait import live as wait_live


logger = logging.getLogger(__name__)


# A long board is counted, not recited: the alert is read by a person on a phone.
MAX_LISTED = 5


def _items(runtime, captain, lines):
    db = runtime.db
    items = []
    for line in lines:
        conv = db.get_conversation(line)
        name = (conv or {}).get('name') or line
        row = db._exec('SELECT status,merged FROM task_reviews WHERE conv_id=?', (line,)).fetchone()
        if row and not (row['status'] == 'done' or (row['status'] == 'approved' and row['merged'])):
            items.append((f'task:{line}:{row["status"]}:{row["merged"]}',
                          f'task «{name}» ({row["status"]})'))
        for report in db._exec('SELECT id,revision,child_conv_id FROM line_reports WHERE '
                               'parent_conv_id=? AND notify=1 AND acknowledged_at IS NULL',
                               (line,)).fetchall():
            # A retired line's report is history: nobody can act on it any more.
            if report['child_conv_id'] in lines:
                items.append((f'report:{report["id"]}:{report["revision"]}',
                              f'pending report #{report["id"]} on «{name}»'))
    for approval in pending_approval_rows(db, captain['conv_id'], runtime=runtime):
        # A person's decision is its own wake, and the banner already asks for it.
        if approval['kind'] == 'restart' or approval.get('human_only'):
            continue
        items.append((f'approval:{approval["kind"]}:{approval["request_id"]}:{approval["detail"]}',
                      f'{approval["kind"]} approval on «{approval["line"]}»: {approval["detail"]}'))
    return sorted(items)


def _listing(items):
    labels = [label.replace('@', '＠') for _, label in items]
    more = len(labels) - MAX_LISTED
    return '; '.join(labels[:MAX_LISTED]) + (f'; and {more} more' if more > 0 else '')


def _busy(runtime, presence, captain, lines):
    db = runtime.db
    returns = presence.returns
    if captain['id'] in returns.pending:
        for ident in returns.requesters.get(captain['id'], {}):
            target = db.get_attachment(ident)
            adapter = runtime.live.get(ident)
            if (target and adapter and runtime.activation_matches(adapter, target)
                    and target['id'] != captain['id'] and target.get('is_lead')
                    and target['status'] in LIVE and target['conv_id'] in lines):
                return True
    for line in lines:
        if line in presence.goal_stall.pending:
            return True
        for att in db.list_attachments(line):
            if att['id'] == captain['id']:
                continue
            if att['id'] in getattr(runtime, 'reattaching', set()):
                return True
            if att['status'] in LIVE and (presence.is_working(att['id']) or
                                         presence.queue.held_count(att['id']) or
                                         att['id'] in presence.returns.pending):
                return True
        row = db._exec('SELECT wait_until FROM task_reviews WHERE conv_id=?', (line,)).fetchone()
        if row and wait_live(dict(row)):
            return True
    if features.enabled('heartbeat'):
        heartbeat = db._exec('SELECT * FROM lead_heartbeat WHERE enabled=1').fetchone()
        if heartbeat and heartbeat['conv_id'] in lines:
            from .heartbeat_scheduler import deliverable_owner
            if deliverable_owner(runtime, heartbeat):
                if heartbeat['pending_message_id'] or not heartbeat['quiet_if_unchanged']:
                    return True
                from . import heartbeat_snapshot
                snapshot = heartbeat_snapshot.build(db, heartbeat['conv_id'], heartbeat['since_id'],
                                                    heartbeat['attachment_id'])
                if heartbeat_snapshot.is_actionable(snapshot):
                    return True
    return False


async def check(runtime, presence, captain):
    """Check once at the receipt, without scheduling another check."""
    if not captain or not captain.get('is_lead') or presence is None:
        return
    db = runtime.db
    if not hasattr(db, '_exec'):
        return
    lead = lead_attachment(db, captain['conv_id'])
    if not lead or lead['id'] != captain['id']:
        return
    # Retired lines hold no open work and no live process; a long-lived root has hundreds.
    lines = [captain['conv_id'], *descendants(db, captain['conv_id'], include_archived=False)]
    items = _items(runtime, captain, lines)
    key = json.dumps([key for key, _ in items], ensure_ascii=False)
    row = db._exec('SELECT items FROM captain_idle_verdicts WHERE attachment_id=?',
                   (captain['id'],)).fetchone()
    previous = row['items'] if row else None
    busy = (presence.is_working(captain['id']) or presence.queue.held_count(captain['id'])
            or _busy(runtime, presence, captain, lines))
    if previous != key or busy:
        db._exec('DELETE FROM captain_idle_verdicts WHERE attachment_id=?', (captain['id'],))
    if not items or busy or previous == key:
        return
    db._exec('INSERT OR REPLACE INTO captain_idle_verdicts(attachment_id,items) VALUES(?,?)',
             (captain['id'], key))
    summary = f'Open work: {_listing(items)}. Nothing is running or scheduled to wake anyone.'
    try:
        await runtime.post_message(captain['conv_id'], 'system', 'system', f'⚠ {summary}')
        await post_private(runtime, captain['conv_id'], 'system', 'system',
                           f'↩ @{captain["name"]} {summary} Use restart_implementer, reopen_task or '
                           'resume_work; or tell the person what you are blocked on.',
                           audience=captain['id'], private=True)
    except Exception:
        db._exec('DELETE FROM captain_idle_verdicts WHERE attachment_id=?', (captain['id'],))
        raise


def activity(runtime, conv_id, actor_id):
    """A worker starting again makes a later identical idle verdict new."""
    db = getattr(runtime, 'db', None)
    if db is None or not hasattr(db, '_exec') or not actor_id:
        return
    try:
        rows = db._exec('SELECT attachment_id FROM captain_idle_verdicts').fetchall()
        if not rows:
            return
        lines = {conv_id, *ancestors(db, conv_id)}
        for row in rows:
            ident = row['attachment_id']
            captain = db.get_attachment(ident)
            if ident != actor_id and captain and captain['conv_id'] in lines:
                db._exec('DELETE FROM captain_idle_verdicts WHERE attachment_id=?', (ident,))
    except Exception:
        logger.exception('Could not reset captain idle verdict on activity')


async def safe_check(runtime, presence, captain):
    """An alert failure must not interrupt turn returns or queued delivery."""
    try:
        await check(runtime, presence, captain)
    except Exception:
        logger.exception('Could not check captain idle state')
