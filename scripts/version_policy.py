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


@dataclass(frozen=True)
class Change:
    subject: str
    before: Version
    after: Version

    @property
    def changes_version(self) -> bool:
        return self.before != self.after


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


def history_verdict(base: Version, head: Version, changes: list[Change]) -> str | None:
    """Validate the result and the commit that owns its one version transition."""
    subjects = [change.subject for change in changes]
    bump = required_bump(subjects)
    endpoint_failure = verdict(base, head, subjects)
    if endpoint_failure:
        return endpoint_failure

    transitions = [change for change in changes if change.changes_version]
    if bump is None:
        if transitions:
            return "a non-release change set must not contain a version transition"
        return None
    if len(transitions) != 1:
        return f"expected one version transition in the change set, found {len(transitions)}"

    owner = transitions[0]
    owner_bump = required_bump([owner.subject])
    if owner_bump != bump:
        return (
            f"the {bump} version transition belongs in a {bump}-impact commit; "
            f"it occurred in {owner.subject!r}"
        )
    expected_after = owner.before.bumped(bump)
    if owner.after != expected_after:
        return (
            f"the version-owning commit must bump {owner.before} to {expected_after}, "
            f"got {owner.after}"
        )
    if owner.after != head:
        return (
            f"the version-owning commit ends at {owner.after}, but the change set ends at "
            f"{head}; update the release commit against the current base"
        )
    return None


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


HELPER_SHARED = {"partyline/file_events.py", "partyline/file_watch_paths.py", "partyline/process_events.py",
                 "partyline/file_notify_kqueue.py", "partyline/file_notify_linux.py",
                 "partyline/file_notify_windows.py", "partyline/point_geometry.py",
                 "partyline/screen_look_data.py", "partyline/screen_tree.py",
                 "partyline/screen_tree_ids.py", "partyline/screen_tree_query.py"}
HELPER_VERSION_PATH = "partyline_helper/__init__.py"


def helper_path(path: str) -> bool:
    return path.startswith(("partyline_helper/", "packaging/windows/")) or path in HELPER_SHARED


def revision_version(revision: str, path: str = "partyline/__init__.py") -> Version:
    try:
        source = git("show", f"{revision}:{path}")
    except subprocess.CalledProcessError:
        if path == HELPER_VERSION_PATH:
            return Version(0, 0, 0)
        raise
    if path == HELPER_VERSION_PATH and not any(
        isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__"
                                             for t in node.targets)
        for node in ast.parse(source).body
    ):
        return Version(0, 0, 0)
    return source_version(source)


def commit_history(base: str, head: str, path: str = "partyline/__init__.py",
                   scope: str | None = None) -> list[Change]:
    output = git("rev-list", "--reverse", "--no-merges", f"{base}..{head}")
    return [
        Change(
            subject=scoped_subject(revision, scope),
            before=revision_version(f"{revision}^", path),
            after=revision_version(revision, path),
        )
        for revision in output.splitlines()
    ] if output else []


def helper_init_content(revision: str) -> str:
    try:
        source = git("show", f"{revision}:{HELPER_VERSION_PATH}")
    except subprocess.CalledProcessError:
        source = ""
    tree = ast.parse(source)
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets))]
    return ast.dump(tree)


def scoped_subject(revision: str, scope: str | None) -> str:
    subject = git("show", "-s", "--format=%s", revision)
    if scope is None:
        return subject
    paths = git("diff-tree", "--no-commit-id", "--name-only", "-r", revision).splitlines()
    if scope == "helper":
        relevant = any(helper_path(p) and p != HELPER_VERSION_PATH for p in paths)
        if not relevant and HELPER_VERSION_PATH in paths:
            relevant = helper_init_content(f"{revision}^") != helper_init_content(revision)
    else:
        relevant = any((not helper_path(p) or p in HELPER_SHARED)
                       and not p.startswith(("tests/", "docs/", "scripts/", ".github/")) for p in paths)
    return subject if relevant else "chore: outside release scope"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base revision of the change set")
    parser.add_argument("--head", default="HEAD", help="head revision (default: HEAD)")
    args = parser.parse_args(argv)

    for scope, path in (("server", "partyline/__init__.py"), ("helper", HELPER_VERSION_PATH)):
        changes = commit_history(args.base, args.head, path, scope)
        if not changes:
            parser.error(f"no non-merge commits found in {args.base}..{args.head}")
        base, head = revision_version(args.base, path), revision_version(args.head, path)
        if scope == "helper" and base == Version(0, 0, 0) and head == Version(1, 0, 0):
            transitions = [change for change in changes if change.changes_version]
            if len(transitions) != 1 or required_bump([transitions[0].subject]) is None:
                print("FAIL: helper initialization must accompany a helper feature or fix")
                return 1
            print("helper version initialized at 1.0.0")
            continue
        failure = history_verdict(base, head, changes)
        if failure:
            print(f"FAIL: {scope}: {failure}")
            return 1
        bump = required_bump([change.subject for change in changes])
        print(f"{scope} version policy satisfied: {base} -> {head} ({bump or 'no release'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
