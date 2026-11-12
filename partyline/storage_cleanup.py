"""Event-driven storage reclamation. All callers run this work in a thread."""

import logging
import os
from pathlib import Path
import shutil
import threading

from . import storage_survey as survey
from .agent_connection import connection_directory
from .mcp_attach import CONFIG_SUFFIX

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def result():
    return {"removed": [], "freed_bytes": 0, "skipped": []}


def kept(report, path, reason):
    report["skipped"].append({"path": str(path), "reason": str(reason)})


def attempt(report, path, action):
    """One failed candidate never prevents reclaiming the next one."""
    try:
        size = survey.Budget(seconds=float('inf')).size(path)
        reason = action()
        if reason:
            kept(report, path, reason)
        elif not os.path.lexists(path):
            report["removed"].append(str(path))
            report["freed_bytes"] += size
    except Exception as exc:
        logger.exception("storage cleanup failed for %s; continuing", path)
        kept(report, path, getattr(exc, 'detail', None) or str(exc))


def attachment_reason(db, ident):
    return survey._in_use(db, ident, survey.planned_ids(db))


def remove_path(path):
    if Path(path).is_symlink():
        raise ValueError("symbolic link retained")
    if Path(path).is_dir():
        shutil.rmtree(path)
    else:
        Path(path).unlink(missing_ok=True)


def clean_attachments(db, report, ident=None):
    for kind in survey.SESSION_HOME_KINDS:
        base = Path(survey.SESSIONS_ROOT) / kind
        homes = ([base / ident] if ident else sorted(base.iterdir())) if base.is_dir() else []
        for home in homes if not base.is_symlink() else []:
            if (ident and home.name != ident) or home.is_symlink() or not home.is_dir():
                continue
            if reason := attachment_reason(db, home.name):
                kept(report, home, reason)
                continue

            def clean(home=home):
                reason = attachment_reason(db, home.name)
                if reason:
                    return reason
                # Reclassify after sizing: a restored line must keep its session.
                att = db.get_attachment(home.name)
                conv = db.get_conversation(att['conv_id']) if att else None
                resumable = bool(att and att.get('cli_session') and not (conv or {}).get('archived_at'))
                target = home / 'cache' if resumable else home
                if target.exists():
                    remove_path(target)
                return 'it can still be resumed (cache cleared)' if resumable else None

            # Count a retained home's cache separately, so freed bytes stay accurate.
            before = survey.Budget(seconds=float('inf')).size(home)
            attempt(report, home, clean)
            if home.exists():
                report['freed_bytes'] += max(0, before - survey.Budget(seconds=float('inf')).size(home))
    base = connection_directory(db.path)
    if base.is_symlink() or not base.is_dir():
        return
    for path in sorted(base.iterdir()):
        suffix = CONFIG_SUFFIX if path.name.endswith(CONFIG_SUFFIX) else '.json'
        if not path.name.endswith(suffix) or path.is_symlink() or not path.is_file():
            continue
        owner = path.name[:-len(suffix)]
        if ident and owner != ident:
            continue

        def clean(path=path, owner=owner):
            reason = attachment_reason(db, owner)
            if reason:
                return reason
            remove_path(path)
            return None

        attempt(report, path, clean)


def cleanup(db, *, attachment_id=None, line=None):
    """Serialize events with ownership changes; no timer or filesystem polling."""
    with _lock, db._runtime_serialized():
        report = result()
        steps = [lambda: clean_attachments(db, report, attachment_id)]
        if attachment_id is None:
            from .storage_worktrees import clean_worktrees
            from .storage_fences import clean_fences
            steps += [lambda: clean_worktrees(db, report, line), lambda: clean_fences(db, report, line)]
        for step in steps:
            try:
                step()
            except Exception:
                logger.exception('storage cleanup step failed; continuing')
        return report


async def automatic(db, **kwargs):
    import asyncio

    try:
        return await asyncio.to_thread(cleanup, db, **kwargs)
    except Exception:
        logger.exception('automatic storage cleanup failed; continuing')
        return result()
