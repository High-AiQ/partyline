"""The one mapping from changed paths to the gate commands a light task runs.

A full task runs every AGENTS.md gate. A light task scales them to the diff:
docs, markdown and skills need none; Python gets ruff plus the tests that touch
the changed modules; the frontend gets verify and build. A path this table does
not know is never guessed at: it falls back to the full gates.

    uv run --locked python -m partyline.task_gates [path ...]

With no paths it reads the diff against origin/main (or main) and untracked files.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RUFF = "uv run --locked ruff check ."
FRONTEND = "cd frontend && npm run verify && npm run build"
FULL = [RUFF, "./scripts/capped-test", "uv run --locked coverage report", "./check-code-lines",
        "./scripts/check-no-media", FRONTEND]
TESTS = "./scripts/capped-test uv run --locked python -m unittest"
DOC_PREFIXES = ("docs/", "skills/")
VERSION = "partyline/__init__.py"


def _docs(path: str) -> bool:
    return path.endswith(".md") or path.startswith(DOC_PREFIXES)


def _frontend(path: str) -> bool:
    return path.startswith(("frontend/", "partyline/static/"))


def _tests_for(path: str, root: Path) -> list[str]:
    """Test modules for one Python path: itself, tests/test_<stem>*.py, and importers.

    A shared helper under tests/ (a fixture, not a test_ module) runs its importers.
    """
    tests = root / "tests"
    dotted = path[:-3].replace("/", ".")
    if path.startswith("tests/") and Path(path).name.startswith("test_"):
        return [dotted]
    names = {item.stem for item in tests.glob(f"test_{Path(path).stem}*.py")}
    if path.startswith("tests/"):
        names = set()
    for item in tests.glob("test_*.py"):
        text = item.read_text(encoding="utf-8", errors="replace")
        if f"{dotted}" in text or f"from {dotted.rsplit('.', 1)[0]} import {Path(path).stem}" in text:
            names.add(item.stem)
    return [f"tests.{name}" for name in sorted(names)]


def gates_for(paths: list[str], root: Path | str = ".") -> list[str]:
    """The gate commands for these changed paths, in order and without repeats."""
    root = Path(root)
    python = frontend = False
    modules: list[str] = []
    for path in dict.fromkeys(paths):
        if _docs(path):
            continue
        if _frontend(path):
            frontend = True
        elif path.endswith(".py") and path.startswith(("partyline/", "tests/")):
            python = True
            if path == VERSION:
                continue  # the semver bump every shipped change makes needs lint only
            found = _tests_for(path, root)
            if not found:
                return list(FULL)  # a module or shared helper no test reaches: do not guess
            modules.extend(found)
        else:
            return list(FULL)
    gates = [RUFF] if python else []
    if modules:
        gates.append(f"{TESTS} {' '.join(dict.fromkeys(modules))}")
    return gates + ([FRONTEND] if frontend else [])


def changed_paths(root: Path | str = ".") -> list[str]:
    """Paths changed against the base branch, including uncommitted and untracked ones."""
    def git(*args: str) -> list[str]:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
        return done.stdout.split("\n") if done.returncode == 0 else []

    for base in ("origin/main", "main"):
        merge_base = "".join(git("merge-base", "HEAD", base)).strip()
        if merge_base:
            break
    else:
        merge_base = "HEAD"
    found = git("diff", "--name-only", merge_base) + git("ls-files", "--others", "--exclude-standard")
    return [path for path in found if path]


def main(argv: list[str]) -> int:
    paths = argv or changed_paths()
    gates = gates_for(paths)
    print("\n".join(gates) if gates else "no gates: docs, markdown and skills changes only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
