"""Which repositories a line's reviews may name, and how a name finds its repository.

One accepted set per line — its own checkout, every subtree line's checkout,
attachment folders and write grants — answers every review door and prints
itself in every refusal, so a worker told "no" learns what would have worked.
"""

from __future__ import annotations

import os

from .hierarchy import subtree_conversation_ids
from .line_worktree import _git, line_cwd, repo_and_worktree, repo_root
from .task_workspaces import workspaces
from .worktree_paths import branch_name


class ReviewError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def places_of(db, line_id: str) -> list[str]:
    """Where a line works: its checkout, its attachments' folders and its write grants.

    A task line can sit in one repository while its implementer commits in a
    sibling it holds a write grant for; that sibling is the line's own work.
    """
    from .write_set_routes import list_write_grants

    places = [line_cwd(db, line_id) or ""]
    places += [att["cwd"] or "" for att in db.list_attachments(line_id)]
    for grant in list_write_grants(db, line_id):
        path = grant["path"]
        places.append(path if os.path.isdir(path) else os.path.dirname(path))
    return places


def accepted_repositories(db, conv_id: str) -> list[tuple[str, str]]:
    """``(repository root, the subtree line that works in it)``, own checkout first."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in workspaces(db, conv_id):
        seen.add(os.path.realpath(item["repository"]))
        found.append((item["repository"], conv_id))
    for line_id in subtree_conversation_ids(db, conv_id):
        for place in places_of(db, line_id):
            root, _worktree = repo_and_worktree(place)
            if root and os.path.realpath(root) not in seen:
                seen.add(os.path.realpath(root))
                found.append((root, line_id))
    return found


def describe(accepted: list[tuple[str, str]]) -> str:
    return ", ".join(root for root, _line in accepted) or "none"


def _same(left: str, right: str) -> bool:
    try:
        return os.path.samefile(left, right)  # symlinks and case-insensitive volumes
    except OSError:
        return os.path.realpath(left) == os.path.realpath(right)


def _named(accepted: list[tuple[str, str]], name: str) -> tuple[str, str] | None:
    """A repository named by absolute path, by a path inside it, or by a bare folder name."""
    if os.path.isabs(name):
        wanted = repo_root(name) or name
        return next((item for item in accepted if _same(item[0], wanted)), None)
    tail = name.strip("/").replace("\\", "/")
    hits = [item for item in accepted
            if item[0].replace("\\", "/").rstrip("/").lower().endswith("/" + tail.lower())
            or os.path.basename(item[0]).lower() == tail.lower()]
    return hits[0] if len(hits) == 1 else None


def _repositories_in(folder: str) -> list[str]:
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, name) for name in names
            if os.path.lexists(os.path.join(folder, name, ".git"))]


def branch_candidates(db, conv_id: str, accepted: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Repositories that could hold this line's own work without a grant.

    Siblings of an accepted repository, and direct children of the tree root's
    folder. They join the accepted set only for a SHA the line's branch there
    contains (`on_line_branch`) — nothing else ties them to the line.
    """
    folders = [os.path.dirname(root) for root, _line in accepted]
    top, parent = conv_id, (db.get_conversation(conv_id) or {}).get("parent_id")
    while parent:
        top, parent = parent, (db.get_conversation(parent) or {}).get("parent_id")
    if (top_cwd := line_cwd(db, top)):
        folders.append(top_cwd)
    known = {os.path.realpath(root) for root, _line in accepted}
    found: list[tuple[str, str]] = []
    for folder in dict.fromkeys(folders):
        for path in _repositories_in(folder):
            if os.path.realpath(path) not in known:
                known.add(os.path.realpath(path))
                found.append((path, conv_id))
    return found


def on_line_branch(db, conv_id: str, root: str, sha: str) -> bool:
    """The repository has this line's branch (`line/<worktree name>`) and it contains `sha`."""
    cwd = line_cwd(db, conv_id)
    if not cwd or not sha:
        return False
    branch = f"refs/heads/{branch_name(cwd)}"
    try:
        return _git("merge-base", "--is-ancestor", sha, branch, cwd=root).returncode == 0
    except OSError:
        return False


def resolve_repository(
    db, conv_id: str, repository: str, sha: str | None = None
) -> tuple[str, str | None]:
    """``(repository root, the subtree line that works in it)``; empty names the line's own.

    With a ``sha``, a sibling carrying the line's own branch at that commit counts too.
    """
    from .review_worktrees import repo_of

    if not repository or not str(repository).strip():
        return repo_of(db, conv_id), None
    name = str(repository).strip()
    accepted = accepted_repositories(db, conv_id)
    hit = _named(accepted, name)
    if hit is None and sha:
        near = _named(branch_candidates(db, conv_id, accepted), name)
        if near and on_line_branch(db, conv_id, near[0], sha):
            hit = near
    if hit is None:
        raise ReviewError(
            403,
            f"{name} is not this line's repository and no line in its subtree works in it — "
            "review worktrees may only be created in a subtree repository. Repositories "
            f"accepted for this line: {describe(accepted)}. A sibling repository joins the set "
            "when this line holds a write grant for it (POST …/write-set), or when its "
            f"`{branch_name(line_cwd(db, conv_id) or '')}` branch contains the commit.")
    return hit
