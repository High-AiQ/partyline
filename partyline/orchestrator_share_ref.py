"""Share a host commit with a running task through its private Git refs mirror."""

import re

from fastapi import HTTPException

from .git_fence import SHARED_PREFIX, _read_ref, _write_mirror_text, mirror_store
from .mention_relay import LIVE
from .orchestrator_contracts import MessageTaskIn, ShareRefOut
from .orchestrator_handles import message_task
from .orchestrator_store import require_root, task
from .line_worktree import rev
from .review_scope import _named
from .task_workspaces import workspaces

_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _workspace(db, conv_id: str, repository: str | None) -> dict:
    rows = workspaces(db, conv_id)
    if not rows:
        raise HTTPException(409, "this task has no workspace repository")
    if repository is None:
        return rows[0]
    accepted = [(row["repository"], conv_id) for row in rows]
    hit = _named(accepted, repository)
    if hit is None:
        raise HTTPException(400, "repository is not one of this task's workspace repositories")
    return next(row for row in rows if row["repository"] == hit[0])


def _commit(repository: str, ref_or_sha: str) -> str:
    if (not ref_or_sha or ref_or_sha.startswith("-") or "\0" in ref_or_sha
            or any(char.isspace() for char in ref_or_sha)):
        raise HTTPException(400, "ref_or_sha must be non-empty and contain no whitespace, NUL, "
                            "or leading dash")
    sha = rev(repository, "rev-parse", "--verify", "--quiet", "--end-of-options",
              f"{ref_or_sha}^{{commit}}")
    if not sha or rev(repository, "cat-file", "-t", sha) != "commit":
        raise HTTPException(400, "ref_or_sha does not resolve to a commit in the selected repository")
    return sha


async def share_ref(runtime, actor, conv_id: str, body) -> ShareRefOut:
    """Publish exactly one shared ref, then privately tell the live implementer."""
    db = runtime.db
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, "task not found")
    require_root(db, actor, row["root_id"])
    implementer = db.get_attachment(row["implementer_id"])
    if implementer is None or implementer["status"] not in LIVE:
        raise HTTPException(409, "this task has no live implementer; call restart_implementer")
    if not _NAME.fullmatch(body.name) or body.name.startswith(".") or ".." in body.name:
        raise HTTPException(400, "name must match [A-Za-z0-9._-], be at most 64 characters, "
                            "not start with a dot, and not contain '..'")
    workspace = _workspace(db, conv_id, body.repository)
    repository = workspace["repository"]
    sha = _commit(repository, body.ref_or_sha)
    mirror = mirror_store(repository, conv_id)
    if mirror is None:
        raise HTTPException(409, "this task has no Git refs mirror for the selected repository")
    ref = f"{SHARED_PREFIX}{body.name}"
    previous = _read_ref(mirror, ref)
    if previous and previous != sha and not body.replace:
        raise HTTPException(409, f"{ref} already names a different commit; pass replace=true to move it")
    if previous != sha:
        _write_mirror_text(mirror, ref, sha + "\n")
    example = f"git merge {ref}"
    await message_task(runtime, actor, conv_id, MessageTaskIn(
        text=f"Shared ref {ref} at {sha}. Example: {example}"))
    return ShareRefOut(sha=sha, ref=ref, example=example, repository=repository)
