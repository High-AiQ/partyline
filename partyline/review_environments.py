"""Instance-owned review environment selection."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from .line_worktree import _git


class Environment(BaseModel):
    repository: str = Field(min_length=1, max_length=2048)
    subpath: str = Field(default='.', max_length=1024)
    setup_command: str = Field(default='', max_length=4096)
    test_command: str = Field(default='', max_length=4096)
    set_by: str = ''
    set_at: float = 0

    @field_validator('repository')
    @classmethod
    def valid_repository(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('repository is required')
        return value

    @field_validator('subpath')
    @classmethod
    def valid_subpath(cls, value):
        path = Path(value or '.')
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('subpath must be relative and stay inside the repository')
        return path.as_posix()


class Environments(BaseModel):
    entries: list[Environment] = Field(default_factory=list, max_length=500)

    @field_validator('entries')
    @classmethod
    def unique(cls, entries):
        keys = [(normalize(e.repository), e.subpath) for e in entries]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate repository and subpath')
        return entries


def normalize(value: str) -> str:
    value = value.strip().rstrip('/')
    if os.path.isabs(value):
        return os.path.realpath(value)
    scp = re.match(r'^(?:[^@/]+@)?([^:/]+):(.+)$', value)
    if scp and '://' not in value:
        host, path = scp.groups()
    else:
        parsed = urlsplit(value)
        host, path = parsed.hostname or '', parsed.path
        if parsed.port:
            host += f':{parsed.port}'
        if not host:
            return value.removesuffix('.git').rstrip('/')
    return f'{host.lower()}/{path.strip("/")}'.removesuffix('.git')


def repository_key(root: str) -> str:
    result = _git('remote', 'get-url', 'origin', cwd=root)
    if result.returncode == 0 and result.stdout.strip():
        return normalize(result.stdout.strip())
    return os.path.realpath(root)


def entries_for(db, root: str, changed: list[str]) -> list[Environment]:
    rows = db._exec('SELECT * FROM review_environments').fetchall()
    key = repository_key(root)
    candidates = [Environment(**dict(row)) for row in rows if normalize(row['repository']) == key]
    chosen = {}
    for name in changed:
        parts = Path(name).parts
        matches = [entry for entry in candidates
                   if parts[:len(Path(entry.subpath).parts)] == Path(entry.subpath).parts]
        if matches:
            entry = max(matches, key=lambda item: len(Path(item.subpath).parts))
            chosen[entry.subpath] = entry
    return list(chosen.values())


def changed_files(db, conv_id: str, root: str, sha: str) -> list[str]:
    from .task_workspaces import workspaces
    base = next((item['base_sha'] for item in workspaces(db, conv_id)
                 if os.path.realpath(item['repository']) == os.path.realpath(root)), None)
    if base:
        result = _git('diff', '--name-only', '-z', base, sha, '--', cwd=root)
    else:
        result = _git('diff-tree', '--root', '--no-commit-id', '--name-only', '-r', '-z', sha, cwd=root)
    if result.returncode:
        raise ValueError('cannot determine changed files for review')
    return [name for name in result.stdout.split('\0') if name]
