"""Classify fence homes from ownership rows before any Git subprocess or byte walk."""

from pathlib import Path

from . import git_fence
from .storage_cleanup import attachment_reason
from .storage_survey import planned_ids


def retention(db, folder, line=None):
    attachment = db.get_attachment(folder.name)
    owner_id = attachment['conv_id'] if attachment else folder.name
    if db.get_conversation(owner_id) and not (line and owner_id == line['id']):
        return 'line still exists'
    if reason := attachment_reason(db, folder.name):
        return reason
    ids = {att['id'] for att in db.list_attachments(owner_id)}
    if ids & planned_ids(db) or any(attachment_reason(db, ident) for ident in ids):
        return 'line has a live or restart-planned attachment'
    return None


def folders(db, line=None):
    base = Path(git_fence.FENCE_ROOT)
    if not base.is_dir() or base.is_symlink():
        return
    allowed = {line['id'], *(att['id'] for att in db.list_attachments(line['id']))} if line else None
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        if allowed is None or folder.name in allowed:
            yield folder


def mirrors(folder, onerror):
    try:
        return sorted(folder.iterdir())
    except OSError as exc:
        onerror(str(folder), str(exc))
        return []
