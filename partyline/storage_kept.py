"""Cleanup reasons and explicit retry suppression, stored with the service database."""

import os


def remember(db, path, reason, *, suppress_retry=False):
    db._exec('INSERT INTO storage_cleanup_kept(path,reason,suppress_retry) VALUES(?,?,?) '
             'ON CONFLICT(path) DO UPDATE SET reason=excluded.reason, '
             'suppress_retry=excluded.suppress_retry', (str(path), str(reason)[:2400], int(suppress_retry)))


def forget(db, path):
    db._exec('DELETE FROM storage_cleanup_kept WHERE path=?', (str(path),))


def reason(db, path, *, suppressed_only=False):
    row = db._exec('SELECT reason,suppress_retry FROM storage_cleanup_kept WHERE path=?',
                   (str(path),)).fetchone()
    return row['reason'] if row and (not suppressed_only or row['suppress_retry']) else None


def prune(db):
    for row in db._exec('SELECT path FROM storage_cleanup_kept').fetchall():
        if not os.path.lexists(row['path']):
            forget(db, row['path'])
