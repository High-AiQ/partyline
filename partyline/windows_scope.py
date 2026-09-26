"""Build and clean up an attachment's native write permissions."""

from pathlib import Path
import re
import sys

from . import fence, runtime_lock
from .windows_fence import WindowsFence, contains
from .windows_git import write_paths
from .windows_command import resolve


class Scope:
    def __init__(self, policy, lock):
        self.policy, self.lock = policy, lock
        self.token = policy.token

    def close(self):
        with runtime_lock.exclusive(self.lock):
            self.policy.close()


def state_paths(adapter, environment):
    home = Path.home()
    kind = adapter.kind
    paths = {
        'claude': [environment.get('CLAUDE_CONFIG_DIR', home / '.claude')],
        'codex': [environment.get('CODEX_HOME', home / '.codex')],
        'grok': [home / '.grok'],
        'pi': [home / '.pi', home / '.partyline/sessions/pi' / adapter.att['id']],
        'antigravity': [home / '.gemini', home / '.partyline/sessions/antigravity'],
        'hermes': [environment.get('HERMES_HOME', home / '.hermes')],
        'deepseek': [environment.get('DSH_HOME', home / '.dsh')],
        'opencode': [home / '.config/opencode', home / '.local/share/opencode', home / '.cache/opencode'],
        'muse': [Path(environment.get('XDG_DATA_HOME', home / '.local/share')) / 'muse'],
        'cursor': [home / '.cursor'],
    }.get(kind, [])
    return [Path(path).expanduser() for path in paths]


def read_paths(adapter, environment):
    roots = [Path(sys.prefix), Path(sys.base_prefix), Path(__file__).parent]
    home = Path.home()
    personal = [home / '.gitconfig', home / '.config/git', home / '.git-credentials', home / '.ssh']
    personal += [Path(environment[key]).expanduser() for key in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM')
                 if environment.get(key)]
    roots.extend(path for path in personal if path.exists())
    command = getattr(adapter, 'spawn_argv', None)
    if command:
        for argument in resolve(command, environment)[:2]:
            path = Path(argument)
            if not path.is_file():
                continue
            root = path.parent
            for parent in path.parents:
                if parent.name.lower() == 'node_modules':
                    root = parent
                    break
            roots.append(root)
    if connection := adapter.att.get('_agent_connection_file'):
        roots.append(Path(connection))
    if adapter.kind == 'grok':
        from .adapters.bundled.grok.turn_hooks import hook_file, hooks_paths_file
        session = getattr(adapter, '_session_id', adapter.att['id'])
        roots.extend(path for path in (hook_file(session, adapter.att), hooks_paths_file(adapter.att))
                     if path.exists())
    return roots


def prepare(adapter, environment):
    """Called in a worker thread; locks cover each complete ACL transaction."""
    ident = adapter.att['id']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', ident):
        raise ValueError('invalid attachment ID for Windows state')
    base = Path.home() / '.partyline'
    private = base / 'sessions/windows' / ident
    protected = fence._protected_roots(adapter.att) + (adapter.att.get('db_paths') or [])
    writable = [private, *state_paths(adapter, environment)]
    for path in writable:
        if any(contains(path.resolve(), Path(item).resolve())
               or contains(Path(item).resolve(), path.resolve()) for item in protected):
            raise OSError(f'Windows CLI state overlaps a protected path: {path}')
    temporary = private / 'tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    environment.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
                       npm_config_cache=str(private / 'npm-cache'), UV_CACHE_DIR=str(private / 'uv-cache'))
    for path in writable:
        path.mkdir(parents=True, exist_ok=True)
    writable += [Path(path) for path in write_paths(adapter.att)]
    writable += [Path(path) for path in fence._grant_paths(adapter.att)]
    lock = base / 'windows-acl.lock'
    with runtime_lock.exclusive(lock):
        return Scope(WindowsFence(writable, protected, read_paths(adapter, environment)), lock)
