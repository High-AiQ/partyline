"""Transactional exclusive leases; names belong to a line and serve its descendants."""

import re
import time

from fastapi import HTTPException

from .hierarchy import ancestors

MAX_QUEUE = 64
NAME = r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'


def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(NAME, name):
        raise HTTPException(422, 'resource name must be 1-64 letters, digits, dots or dashes')


def resolve(db, line, name):
    validate_name(name)
    for conv in [line, *ancestors(db, line)]:
        if db._exec('SELECT 1 FROM line_resources r JOIN conversations c ON c.id=r.conv_id '
                    'WHERE r.conv_id=? AND r.name=? AND c.archived_at IS NULL',
                    (conv, name)).fetchone():
            return conv
    raise HTTPException(404, 'resource is not declared on this line or its ancestors')


def _sweep(conn):
    # Check every holder AND waiter before granting: removed, stopped, archived
    # attachments cannot retain a resource after a crash.
    conn.execute("DELETE FROM line_resource_claims WHERE attachment_id NOT IN "
                 "(SELECT a.id FROM attachments a JOIN conversations c ON c.id=a.conv_id "
                 "WHERE a.status IN ('starting','running') AND c.archived_at IS NULL)")
    conn.execute('DELETE FROM line_resource_claims WHERE NOT EXISTS '
                 '(SELECT 1 FROM line_resources r WHERE r.conv_id=line_resource_claims.conv_id '
                 'AND r.name=line_resource_claims.name)')
    for resource in conn.execute('SELECT r.* FROM line_resources r JOIN conversations c '
                                 'ON c.id=r.conv_id WHERE c.archived_at IS NULL').fetchall():
        key = (resource['conv_id'], resource['name'])
        if conn.execute('SELECT 1 FROM line_resource_claims WHERE conv_id=? AND name=? '
                        'AND granted_at IS NOT NULL', key).fetchone():
            continue
        row = conn.execute('SELECT * FROM line_resource_claims WHERE conv_id=? AND name=? '
                           'ORDER BY id LIMIT 1', key).fetchone()
        if row is None:
            continue
        now = time.time()
        att = conn.execute('SELECT * FROM attachments WHERE id=?',
                           (row['attachment_id'],)).fetchone()
        message = conn.execute(
            'INSERT INTO messages(conv_id,sender,sender_type,body,created_at,audience_attachment_id) '
            'VALUES(?,?,?,?,?,?)',
            (att['conv_id'], 'system', 'system',
             f"you now hold {row['name']}; start your job. Release it when done.", now, att['id']))
        conn.execute('UPDATE line_resource_claims SET granted_at=?,notice_id=?,notified=0 WHERE id=?',
                     (now, message.lastrowid, row['id']))


def sweep(db):
    with db.lock, db.conn:
        db.conn.execute('BEGIN IMMEDIATE')
        _sweep(db.conn)


def manage(db, conv, operation, name=None):
    if operation == 'list':
        return report(db, conv)
    validate_name(name)
    with db.lock, db.conn:
        db.conn.execute('BEGIN IMMEDIATE')
        if operation == 'declare':
            db.conn.execute('INSERT OR IGNORE INTO line_resources VALUES(?,?)', (conv, name))
        elif operation == 'remove':
            if db.conn.execute('SELECT 1 FROM line_resource_claims WHERE conv_id=? AND name=?',
                               (conv, name)).fetchone():
                raise HTTPException(409, 'release holders and cancel waiters before removing a resource')
            db.conn.execute('DELETE FROM line_resources WHERE conv_id=? AND name=?', (conv, name))
        else:
            raise HTTPException(422, 'operation must be list, declare or remove')
    return report(db, conv)


def acquire(db, conv, name, att_id, note=''):
    validate_name(name)
    if not isinstance(note, str) or len(note) > 500:
        raise HTTPException(422, 'note is capped at 500 characters')
    with db.lock, db.conn:
        db.conn.execute('BEGIN IMMEDIATE')
        _sweep(db.conn)
        valid = db.conn.execute(
            "SELECT 1 FROM line_resources r JOIN conversations c ON c.id=r.conv_id "
            "JOIN attachments a ON a.id=? JOIN conversations h ON h.id=a.conv_id "
            "WHERE r.conv_id=? AND r.name=? AND c.archived_at IS NULL "
            "AND h.archived_at IS NULL AND a.status IN ('starting','running')",
            (att_id, conv, name)).fetchone()
        if not valid:
            raise HTTPException(409, 'resource or attachment is no longer active')
        existing = db.conn.execute('SELECT * FROM line_resource_claims '
                                   'WHERE conv_id=? AND name=? AND attachment_id=?',
                                   (conv, name, att_id)).fetchone()
        if existing is None:
            count = db.conn.execute('SELECT count(*) FROM line_resource_claims '
                                    'WHERE conv_id=? AND name=? AND granted_at IS NULL',
                                    (conv, name)).fetchone()[0]
            if count >= MAX_QUEUE:
                raise HTTPException(409, 'resource queue is full (64 waiters)')
            now = time.time()
            held = db.conn.execute('SELECT 1 FROM line_resource_claims WHERE conv_id=? AND name=?',
                                   (conv, name)).fetchone()
            db.conn.execute('INSERT INTO line_resource_claims '
                            '(conv_id,name,attachment_id,note,created_at,granted_at,notified) '
                            'VALUES(?,?,?,?,?,?,1)',
                            (conv, name, att_id, note, now, None if held else now))
        rows = _claims(db.conn, conv, name)
        holder = next((r for r in rows if r['granted_at'] is not None), None)
        queue = [r for r in rows if r['granted_at'] is None]
        own = next(r for r in rows if r['attachment_id'] == att_id)
        return {'status': 'held' if own['granted_at'] is not None else 'queued',
                'position': next((i for i, r in enumerate(queue, 1)
                                  if r['attachment_id'] == att_id), 0), 'holder': holder}


def release(db, conv, name, att_id):
    with db.lock, db.conn:
        db.conn.execute('BEGIN IMMEDIATE')
        db.conn.execute('DELETE FROM line_resource_claims WHERE conv_id=? AND name=? '
                        'AND attachment_id=?', (conv, name, att_id))
        _sweep(db.conn)
    return {'status': 'released'}


def _claims(conn, conv, name):
    return [dict(r) for r in conn.execute(
        'SELECT q.attachment_id,q.note,q.created_at,q.granted_at,a.name AS handle,'
        'a.conv_id AS holder_line FROM line_resource_claims q '
        'JOIN attachments a ON a.id=q.attachment_id WHERE q.conv_id=? AND q.name=? ORDER BY q.id',
        (conv, name)).fetchall()]


def report(db, conv):
    with db.lock:
        resources = db.conn.execute('SELECT name FROM line_resources WHERE conv_id=? ORDER BY name',
                                    (conv,)).fetchall()
        result = []
        for r in resources:
            claims = _claims(db.conn, conv, r['name'])
            result.append({'name': r['name'], 'capacity': 1,
                           'holder': next((c for c in claims if c['granted_at'] is not None), None),
                           'queue': [c for c in claims if c['granted_at'] is None]})
        return {'resources': result}
