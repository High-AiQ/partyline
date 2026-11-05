"""Persist process ownership so denied unrelated processes cannot pin temp forever."""
import json
import os
import tempfile
from pathlib import Path

from .process_memory import process_snapshot
from .top_processes import _descendants


def scope_path(adapter):
    pid = getattr(getattr(adapter, 'proc', None), 'pid', None)
    scope = getattr(adapter, 'memory_scope', None)
    if not isinstance(pid, int) or not isinstance(scope, str):
        return None
    try:
        relative = next(line.split('::', 1)[1].strip()
                        for line in Path(f'/proc/{pid}/cgroup').read_text().splitlines()
                        if line.startswith('0::'))
        path = Path('/sys/fs/cgroup') / relative.lstrip('/')
        return next((parent for parent in (path, *path.parents) if parent.name == scope), None)
    except (OSError, StopIteration):
        return None


def scope_inventory(root):
    """A scope may disappear, but a permission-denied owned scope is uncertain."""
    found, stack = set(), [Path(root)] if root else []
    while stack:
        path = stack.pop()
        try:
            found.update(int(value) for value in (path / 'cgroup.procs').read_text().split())
            with os.scandir(path) as entries:
                stack.extend(Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False))
        except FileNotFoundError:
            if path.exists():
                return found, False
        except (OSError, ValueError):
            return found, False
    return found, True


def members(adapter, snapshot):
    pid = getattr(getattr(adapter, 'proc', None), 'pid', None)
    if not isinstance(pid, int):
        return set()
    return _descendants(snapshot[0], pid) | scope_inventory(scope_path(adapter))[0]


def _path(att_id):
    from .attachment_tmp import base_dir
    return base_dir() / '.tmp-owners' / f'{att_id}.json'


def _load(att_id):
    path = _path(att_id)
    if path.parent.is_symlink():
        raise ValueError('unsafe process ownership directory')
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def _contexts(payload):
    roots = payload.get('roots', {})
    if payload.get('root'):
        root = str(payload['root'])
        roots = {root: payload.get('processes', {}).get(root), **roots}
    scopes = set(payload.get('scopes', []))
    if payload.get('scope'):
        scopes.add(payload['scope'])
    return roots, scopes


def record(att_id, adapter):
    from .attachment_tmp import guarded_path
    from .tmp_levels import private_level
    from .tmp_retention import process_identity
    pid = getattr(getattr(adapter, 'proc', None), 'pid', None)
    if not isinstance(pid, int) or guarded_path(att_id) is None:
        return
    identity = process_identity(pid)
    if identity is None:
        return
    previous = _load(att_id)
    roots, scopes = _contexts(previous)
    processes = {old: birth for old, birth in previous.get('processes', {}).items()
                 if birth and process_identity(old) in (birth, 'unknown')}
    snapshot = process_snapshot()
    found = members(adapter, snapshot) if snapshot is not None else {pid}
    processes.update({str(member): process_identity(member) for member in found})
    roots = {old: birth for old, birth in roots.items() if old in processes}
    roots[str(pid)] = identity
    scope = scope_path(adapter)
    if scope:
        scopes.add(str(scope))
    path = _path(att_id)
    private_level(path.parent)
    fd, scratch = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'roots': roots, 'scopes': sorted(scopes), 'processes': processes}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(scratch, path)
        if os.name == 'posix':
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        Path(scratch).unlink(missing_ok=True)


def owned_state(att_id):
    from .tmp_retention import process_identity
    try:
        payload = _load(att_id)
        roots, scopes = _contexts(payload)
        found = {int(pid) for pid, identity in payload.get('processes', {}).items()
                 if identity and process_identity(pid) in (identity, 'unknown')}
        if any(int(root) in found for root in roots):
            snapshot = process_snapshot()
            if snapshot is not None:
                for root in roots:
                    if int(root) in found:
                        found.update(_descendants(snapshot[0], int(root)))
        certain = True
        for scope in scopes:
            scoped, complete = scope_inventory(scope)
            found.update(scoped)
            certain &= complete
        return found, certain
    except (OSError, ValueError, TypeError, AttributeError):
        return set(), False


def owned(att_id):
    return owned_state(att_id)[0]


def forget(att_id):
    path = _path(att_id)
    if not path.parent.is_symlink():
        path.unlink(missing_ok=True)
