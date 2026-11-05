"""Durable pending reaps, with line ownership for handover artifacts.

Keep original paths: a rename would break absolute redirects and inherited
TMPDIR. A successor link gives a discoverable entry without copying live files.
The private manifest survives attachment deletion and server restart.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _registry():
    from .attachment_tmp import instance_key, temp_root
    from .tmp_levels import private_levels
    return private_levels(temp_root(), 'partyline', instance_key(), '.pending-reaps')


def remember(att_id, conv_id=None, successor=None, jobs=()):
    from .attachment_tmp import ID_PATTERN, guarded_path
    if not ID_PATTERN.fullmatch(att_id):
        raise ValueError('invalid attachment id')
    path = guarded_path(att_id)
    if path is None:
        return None
    registry = _registry()
    target = registry / f'{att_id}.json'
    previous = json.loads(target.read_text()) if target.exists() else {}
    if not previous or conv_id is not None:
        fd, scratch = tempfile.mkstemp(dir=registry)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'attachment_id': att_id, 'conv_id': conv_id,
                           'successor': successor, 'path': str(path),
                           'processes': {**previous.get('processes', {}),
                                         **{str(job['host_pid']): process_identity(job['host_pid'])
                                            for job in jobs}}}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(scratch, target)
            if os.name == 'posix':
                directory_fd = os.open(registry, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            Path(scratch).unlink(missing_ok=True)
    if successor:
        from .attachment_tmp import ensure_tmp_dir
        from .tmp_levels import private_levels
        parent = Path(ensure_tmp_dir({'id': successor}))
        retained = private_levels(parent, 'retained')
        link = retained / att_id
        if link.is_symlink() and os.readlink(link) != str(path):
            raise ValueError('conflicting retained directory link')
        if not link.is_symlink():
            try:
                link.symlink_to(path, target_is_directory=True)
            except OSError:
                # Windows directory symlinks require a privilege not every
                # server user has. The retained absolute path remains usable.
                if sys.platform != 'win32':
                    raise
    return path


def forget(att_id):
    from .attachment_tmp import base_dir
    from .tmp_owners import forget as forget_owners
    forget_owners(att_id)
    registry = base_dir() / '.pending-reaps'
    if not registry.is_symlink():
        (registry / f'{att_id}.json').unlink(missing_ok=True)


def reap_pending(active=()):
    from .attachment_tmp import ID_PATTERN, base_dir, guarded_path, reap_tmp_dir
    registry = base_dir() / '.pending-reaps'
    if registry.is_symlink() or not registry.is_dir():
        return
    for entry in registry.iterdir():
        if entry.suffix != '.json' or not ID_PATTERN.fullmatch(entry.stem) or entry.stem in active:
            continue
        if guarded_path(entry.stem) is None:
            forget(entry.stem)
        else:
            reap_tmp_dir(entry.stem)


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except FileNotFoundError:
        return None
    except OSError:
        return 'unknown'


def tracked_jobs_alive(att_id):
    from .attachment_tmp import base_dir
    registry = base_dir() / '.pending-reaps'
    if registry.is_symlink():
        return True
    try:
        payload = json.loads((registry / f'{att_id}.json').read_text())
        return any(identity and process_identity(pid) in (identity, 'unknown')
                   for pid, identity in payload.get('processes', {}).items())
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True


def reap(att_id):
    """Remove only a guarded, demonstrably unused directory; keep failed reaps pending."""
    from .attachment_tmp import dir_size, guarded_path
    from .tmp_processes import in_use
    path = guarded_path(att_id)
    if path is None:
        return None
    from .tmp_owners import owned_state
    pids, certain = owned_state(att_id)
    if tracked_jobs_alive(att_id) or not certain or in_use(path, pids):
        remember(att_id)
        return None
    freed = dir_size(path, budget=None)
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        remember(att_id)
        return None
    forget(att_id)
    return freed
