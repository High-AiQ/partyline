"""Enforce Partyline's Conventional-Commit-to-SemVer policy for one change set."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from dataclasses import dataclass


SUBJECT_RE = re.compile(
    r"^(?P<type>feat|fix|docs|refactor|test|chore)"
    r"(?:\([a-z0-9_.-]+\))?(?P<breaking>!)?: .+"
)
VERSION_RE = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")
BUMP_PRIORITY = {None: 0, "patch": 1, "minor": 2, "major": 3}


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Version:
        match = VERSION_RE.fullmatch(value)
        if match is None:
            raise ValueError(f"{value!r} is not a plain SemVer version (MAJOR.MINOR.PATCH)")
        return cls(*(int(match[name]) for name in ("major", "minor", "patch")))

    def bumped(self, kind: str) -> Version:
        if kind == "major":
            return Version(self.major + 1, 0, 0)
        if kind == "minor":
            return Version(self.major, self.minor + 1, 0)
        if kind == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        raise ValueError(f"unknown bump kind: {kind}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def required_bump(subjects: list[str]) -> str | None:
    """Return the highest SemVer impact declared by the commit subjects."""
    required = None
    for subject in subjects:
        match = SUBJECT_RE.fullmatch(subject)
        if match is None:
            raise ValueError(f"non-conventional commit subject: {subject}")
        if match["breaking"]:
            candidate = "major"
        elif match["type"] == "feat":
            candidate = "minor"
        elif match["type"] == "fix":
            candidate = "patch"
        else:
            candidate = None
        if BUMP_PRIORITY[candidate] > BUMP_PRIORITY[required]:
            required = candidate
    return required


def source_version(source: str) -> Version:
    """Read the literal ``__version__`` without importing application code."""
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "__version__":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return Version.parse(node.value.value)
    raise ValueError("partyline/__init__.py has no literal __version__ assignment")


def verdict(base: Version, head: Version, subjects: list[str]) -> str | None:
    """Return an actionable failure, or ``None`` when the policy is satisfied."""
    bump = required_bump(subjects)
    if bump is None:
        if head != base:
            return (
                f"version changed from {base} to {head}, but this change set contains only "
                "docs/test/refactor/chore commits"
            )
        return None
    expected = base.bumped(bump)
    if head != expected:
        return (
            f"{bump} bump required by the change set: expected {expected} from {base}, got {head}"
        )
    return None


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def revision_version(revision: str) -> Version:
    return source_version(git("show", f"{revision}:partyline/__init__.py"))


def commit_subjects(base: str, head: str) -> list[str]:
    output = git("log", "--no-merges", "--format=%s", f"{base}..{head}")
    return output.splitlines() if output else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base revision of the change set")
    parser.add_argument("--head", default="HEAD", help="head revision (default: HEAD)")
    args = parser.parse_args(argv)

    subjects = commit_subjects(args.base, args.head)
    if not subjects:
        parser.error(f"no non-merge commits found in {args.base}..{args.head}")
    base = revision_version(args.base)
    head = revision_version(args.head)
    failure = verdict(base, head, subjects)
    if failure:
        print(f"FAIL: {failure}")
        return 1
    bump = required_bump(subjects)
    print(f"version policy satisfied: {base} -> {head} ({bump or 'no release'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
