"""Print scoped gate commands for changed paths; full suites belong to a suite line.

    uv run --locked python -m partyline.task_gates [path ...]

Without paths, inspect the diff against origin/main (or main) and untracked files.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

RUFF = "uv run --locked ruff check ."
TESTS = "./scripts/capped-test uv run --locked python -m unittest"
NO_DIRECT = "echo 'no direct tests; covered by the suite run'"
VERSION = "partyline/__init__.py"


def _tests_for(path: str, root: Path) -> list[str]:
    """Direct test modules and importers, excluding browser/e2e suites."""
    dotted = path.removesuffix('.py').replace('/', '.')
    if path.startswith('tests/') and Path(path).name.startswith('test_'):
        return [dotted] if not path.startswith('tests/ui/') else []
    stem = Path(path).stem
    names = {item.stem for item in (root / 'tests').glob(f'test_{stem}*.py')}
    if path.startswith('partyline_helper/'):
        names.update(item.stem for item in (root / 'tests').glob(f'test_helper_{stem}*.py'))
    if path == 'scripts/capped-test':
        names.update(['test_process_memory', 'test_windows_memory', 'test_capped_task_mode'])
    if path.startswith('packaging/windows/'):
        names.add('test_windows_packaging')
    for item in (root / 'tests').glob('test_*.py'):
        source = item.read_text(encoding='utf-8', errors='replace')
        if (dotted in source or path in source
                or f"from {dotted.rsplit('.', 1)[0]} import {stem}" in source):
            names.add(item.stem)
    return [f'tests.{name}' for name in sorted(names)]


def _chrome_tests(path: str, root: Path) -> list[str]:
    stem = Path(path).stem.removesuffix('.test')
    found = set()
    for item in (root / 'partyline_chrome').glob('*.test.js'):
        if item.stem == f'{stem}.test' or item.stem.startswith(f'{stem}_') or (
                Path(path).name in item.read_text(encoding='utf-8')):
            found.add(item.relative_to(root).as_posix())
    return sorted(found)


def frontend_gates(paths: list[str], root: Path | str = '.') -> list[str]:
    files = [path.removeprefix('frontend/') for path in paths if path.startswith('frontend/')]
    files = list(dict.fromkeys(files))
    existing = [path for path in files if (Path(root) / 'frontend' / path).is_file()]
    gates = []
    if existing:
        quoted = shlex.join(existing)
        gates.extend([f'cd frontend && npx prettier --check --ignore-unknown {quoted}',
                      f'cd frontend && npx eslint --no-warn-ignored {quoted}'])
    gates.append('cd frontend && npm run check')
    if files:
        gates.append(f'cd frontend && npx vitest related {shlex.join(files)} --run --passWithNoTests')
    return gates + ['cd frontend && npm run build']


def gates_for(paths: list[str], root: Path | str = '.') -> list[str]:
    """Union of commands reaching this diff; an unknown path never widens tests."""
    root = Path(root)
    modules, javascript, frontend = [], [], []
    lint = missing = False
    for path in dict.fromkeys(paths):
        if path.endswith('.md') or path.startswith(('docs/', 'skills/')):
            continue
        if path.startswith(('frontend/', 'partyline/static/')):
            frontend.append(path)
            continue
        lint = True
        if path == VERSION:
            continue
        if path.startswith('partyline_chrome/'):
            found = _chrome_tests(path, root)
            javascript.extend(found)
        else:
            found = _tests_for(path, root)
            modules.extend(found)
        missing |= not found
    gates = [RUFF] if lint else []
    if modules:
        gates.append(f'{TESTS} {shlex.join(list(dict.fromkeys(modules)))}')
    if javascript:
        gates.append(f'node --test {shlex.join(list(dict.fromkeys(javascript)))}')
    if missing:
        gates.append(NO_DIRECT)
    return gates + (frontend_gates(frontend, root) if frontend else [])


def changed_paths(root: Path | str = '.') -> list[str]:
    """Paths changed against the base branch, including uncommitted and untracked ones."""
    def git(*args: str) -> list[str]:
        done = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=False)
        return done.stdout.split('\n') if done.returncode == 0 else []

    for base in ('origin/main', 'main'):
        merge_base = ''.join(git('merge-base', 'HEAD', base)).strip()
        if merge_base:
            break
    else:
        merge_base = 'HEAD'
    found = git('diff', '--name-only', merge_base) + git('ls-files', '--others', '--exclude-standard')
    return [path for path in found if path]


def main(argv: list[str]) -> int:
    gates = gates_for(argv or changed_paths())
    print('\n'.join(gates) if gates else 'no gates: docs, markdown and skills changes only')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
