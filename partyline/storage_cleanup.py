"""Event-driven storage reclamation. All callers run this work in a thread."""

from contextlib import nullcontext
import logging
import os
from pathlib import Path
import threading

from . import storage_survey as survey
from .agent_connection import connection_directory
from .mcp_attach import CONFIG_SUFFIX
from .storage_removal import remove_contents

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def result():
    return {"removed": [], "freed_bytes": 0, "skipped": []}


def kept(report, path, reason):
    report["skipped"].append({"path": str(path), "reason": str(reason)})


def attempt(report, path, action):
    """One failed candidate never prevents reclaiming the next one."""
    size = 0
    try:
        size = survey.Budget(seconds=float('inf')).size(path)
        reason = action()
        if reason:
            kept(report, path, reason)
        if not os.path.lexists(path):
            report["removed"].append(str(path))
    except Exception as exc:
        logger.exception("storage cleanup failed for %s; continuing", path)
        kept(report, path, getattr(exc, 'detail', None) or str(exc))
    finally:
        remaining = survey.Budget(seconds=float('inf')).size(path) if os.path.lexists(path) else 0
        report['freed_bytes'] += max(0, size - remaining)


def attachment_reason(db, ident):
    return survey._in_use(db, ident, survey.planned_ids(db))


def remove_path(path, *, excluded=()):
    if Path(path).is_symlink():
        raise ValueError("symbolic link retained")
    if Path(path).is_dir():
        remove_contents(path, excluded=excluded)
        Path(path).rmdir()
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

            def clean(home=home, kind=kind):
                with db._runtime_serialized():
                    reason = attachment_reason(db, home.name)
                    if reason:
                        return reason
                    # Reclassify after sizing: a restored line must keep its session.
                    att = db.get_attachment(home.name)
                    conv = db.get_conversation(att['conv_id']) if att else None
                    resumable = survey.resumable(att, conv, kind)
                    target = home / 'cache' if resumable else home
                    if target.exists():
                        remove_path(target)
                    return 'it can still be resumed (cache cleared)' if resumable else None

            attempt(report, home, clean)
    base = connection_directory(db.path)
    if base.is_symlink() or not base.is_dir():
        return
    paths = ([base / (ident + suffix) for suffix in ('.json', CONFIG_SUFFIX)]
             if ident else sorted(base.iterdir()))
    for path in paths:
        suffix = CONFIG_SUFFIX if path.name.endswith(CONFIG_SUFFIX) else '.json'
        if not path.name.endswith(suffix) or path.is_symlink() or not path.is_file():
            continue
        owner = path.name[:-len(suffix)]
        if ident and owner != ident:
            continue

        def clean(path=path, owner=owner):
            with db._runtime_serialized():
                reason = attachment_reason(db, owner)
                if reason:
                    return reason
                remove_path(path)
                return None

        attempt(report, path, clean)


def cleanup(db, *, attachment_id=None, line=None, purging=False, retry_mirrors=False):
    """Serialize full sweeps only; lifecycle cleanup must never queue behind them."""
    with _lock if attachment_id is None and line is None else nullcontext():
        report = result()
        ids = ([attachment_id] if attachment_id else
               [att['id'] for att in db.list_attachments(line['id'])] if line else [None])
        steps = [lambda ident=ident: clean_attachments(db, report, ident) for ident in ids]
        if attachment_id is None:
            from .storage_worktrees import clean_worktrees
            from .storage_fences import clean_fences
            steps.append(lambda: clean_worktrees(db, report, line, purging=purging))
            if line is None or purging:
                steps.append(lambda: clean_fences(db, report, line, retry_failed=retry_mirrors))
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
