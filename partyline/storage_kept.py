"""Durable failure reasons; startup does not retry unreadable mirrors indefinitely."""

import hashlib
import json
import os
from pathlib import Path
import tempfile


def directory(db):
    return Path(db.path + '.storage-kept')


def entry(db, path):
    return directory(db) / (hashlib.sha256(os.fsencode(path)).hexdigest() + '.json')


def remember(db, path, reason):
    directory(db).mkdir(parents=True, exist_ok=True)
    target = entry(db, path)
    descriptor, temporary = tempfile.mkstemp(dir=directory(db), suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump({'path': str(path), 'reason': str(reason)}, stream)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def forget(db, path):
    entry(db, path).unlink(missing_ok=True)


def reason(db, path):
    try:
        value = json.loads(entry(db, path).read_text())['reason']
        return value if isinstance(value, str) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
