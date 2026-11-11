"""Task maintenance subscriptions for database state and Git integration refs."""

from pathlib import Path
import time

from .file_events import FileEvents
from .line_worktree import line_cwd
from .orchestrator_store import all_tasks
from .reports import NOTIFY_CLAIM_SECONDS
from .task_workspaces import workspaces


def git_roots(db):
    folders = set()
    for row in all_tasks(db):
        folders.update(filter(None, (line_cwd(db, row['root_id']), line_cwd(db, row['conv_id']))))
        for item in [*row['repositories'], *workspaces(db, row['conv_id'])]:
            folders.update(filter(None, (item.get('repository'), item.get('path'))))
    roots = set()
    for cwd in folders:
        path = Path(cwd) / '.git'
        if path.is_file():
            text = path.read_text().strip()
            if text.startswith('gitdir: '):
                path = (Path(cwd) / text[8:]).resolve()
        common = path / 'commondir'
        if common.is_file():
            path = (path / common.read_text().strip()).resolve()
        if path.is_dir():
            roots.add(path)
            roots.add(path / 'packed-refs')
            roots.add(path / 'worktrees')
            heads = [path / 'HEAD', *(path / 'worktrees').glob('*/HEAD')]
            for head in heads:
                roots.add(head)
                try:
                    text = head.read_text().strip()
                except FileNotFoundError:
                    continue
                if text.startswith('ref: '):
                    roots.add(path / text[5:])
    return sorted(roots)


def wait_deadline(db):
    now = time.time()
    waits = db._exec('SELECT MIN(wait_until) FROM task_reviews WHERE wait_until>?',
                     (now,)).fetchone()[0]
    claim = db._exec('SELECT MIN(r.notifying_at) FROM line_reports r '
                     'JOIN task_reviews t ON t.report_id=r.id '
                     'JOIN conversations c ON c.id=t.conv_id '
                     'WHERE r.notified_at IS NULL AND r.notifying_at IS NOT NULL '
                     'AND c.archived_at IS NULL').fetchone()[0]
    deadlines = [value for value in (waits, None if claim is None else claim + NOTIFY_CLAIM_SECONDS)
                 if value is not None]
    return max(0, min(deadlines) - now) if deadlines else None


async def tasks(runtime, tick):
    with runtime.db.events.subscribe('task_reviews', 'attachments', 'conversations',
                                     'line_reports', 'task_workspaces', 'settings') as events:
        while True:
            # Re-register before the authoritative scan, including new repositories.
            async with FileEvents(*git_roots(runtime.db), changes=events.changes):
                with events.processing():
                    failed = await tick(runtime)
                    delay = wait_deadline(runtime.db)
                    if failed is True:
                        # no-poll (e): retry an actual maintenance/report delivery failure.
                        delay = 5 if delay is None else min(5, delay)
                await events.wait(delay)
