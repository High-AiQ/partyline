"""A line asks for extra write scope; a person approves it in a banner.

The default write set is derived at spawn. When work needs a path outside it,
a process on the line — or a captain above — files a request; every open tab
on that line shows it, and a person approves or declines. Approval records
the grant, rings the requester, and resumes the line's live processes so the
widened bind applies without a service restart.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel

from .adapters import ADAPTER_METADATA
from .approval_bubble import bubble_approval
from .fence_protect import protected_repo_roots
from .hierarchy import ancestors
from .line_process_routes import detach_attachment, live_attachments
from .line_worktree import REVIEW_DIR, rev
from .resume_continuation import resume_with_backlog
from .reattach import adapter_can_resume
from .review_worktrees import ReviewError, subtree_repository

logger = logging.getLogger(__name__)


class WriteSetGrantRequest(BaseModel):
    id: str
    conversation_id: str
    path: str
    requester: str
    requester_attachment_id: str | None = None
    created_at: float


class PendingWriteSetGrant(BaseModel):
    request: WriteSetGrantRequest | None = None


def get_pending_request(db, conv_id: str) -> dict | None:
    row = db._exec(
        "SELECT * FROM conversation_write_grant_requests WHERE conv_id=?",
        (conv_id,),
    ).fetchone()
    return dict(row) if row else None


def _row_to_request(row: dict) -> WriteSetGrantRequest:
    return WriteSetGrantRequest(
        id=row["id"],
        conversation_id=row["conv_id"],
        path=row["path"],
        requester=row["requester"],
        requester_attachment_id=row["requester_attachment_id"],
        created_at=row["created_at"],
    )


def pending_model(db, conv_id: str) -> PendingWriteSetGrant:
    row = get_pending_request(db, conv_id)
    return PendingWriteSetGrant(request=_row_to_request(row) if row else None)


def machine_may_file(db, principal, conv_id: str) -> bool:
    return principal.conv_id == conv_id or (
        principal.is_lead and principal.conv_id in ancestors(db, conv_id)
    )


def validate_path(path: str) -> str:
    import os

    path = path.strip()
    if not path.startswith("/") or path == "/" or os.path.normpath(path) != path:
        raise HTTPException(
            400, "path must be an absolute, normalized file or directory path")
    return path


def validate_grantable(db, path: str) -> str:
    """The path a filing may grant: inside a protected repository, and bindable.

    Two refusals at filing time (2.18), because a grant the fence cannot use
    is worse than no grant: it either does nothing or kills the spawn. A path
    outside every protected root is already writable — the fence leaves the
    rest of the filesystem open — so say that rather than silently storing a
    grant that will be dropped at spawn. A path that exists but is not a
    regular file or directory (a socket, device or fifo) cannot be bound by
    bubblewrap at all: ``/var/run/docker.sock`` through its symlinked parent
    is exactly how an entire line's processes died before their CLIs started.
    """
    import os

    path = validate_path(path)
    resolved = os.path.realpath(path)
    roots = protected_repo_roots(db)
    if not any(
        resolved == root or resolved.startswith(root.rstrip(os.sep) + os.sep)
        for root in roots
    ):
        raise HTTPException(
            400, f"{path} is already writable outside the protected repositories "
                 "— no grant needed")
    if os.path.exists(resolved) and not (
            os.path.isfile(resolved) or os.path.isdir(resolved)):
        raise HTTPException(
            400, f"{path} is not a regular file or directory; only files and "
                 "directories can be granted")
    return path


def resolve_write_set_path(db, conv_id: str, body) -> str:
    """The path one write-set request grants: typed, or named by its review.

    ``{"repository": ..., "sha": ...}`` grants the review checkout at
    ``<repository>/.review/<full sha>`` — the path is derived, never typed,
    and the repository is resolved under the same subtree rule a review
    worktree obeys, so a line grants scope in the repositories it actually
    works in and no stranger's checkout (finding 2.2). The pair and a typed
    path are exclusive; so are half a pair and empty hands.
    """
    path = (body.path or "").strip()
    repository = (body.repository or "").strip()
    sha = (body.sha or "").strip()
    if path and (repository or sha):
        raise HTTPException(422, "name a path, or a repository and sha — not both")
    if not path:
        if not repository and not sha:
            raise HTTPException(422, "name the path to grant")
        if not (repository and sha):
            raise HTTPException(
                422, "a review worktree grant needs both the repository and the sha")
        try:
            root = subtree_repository(db, conv_id, repository)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        full = rev(root, "rev-parse", "--verify", "--quiet", f"{sha.lower()}^{{commit}}")
        if full is None:
            raise HTTPException(400, f"no commit {sha} in this repository")
        return os.path.realpath(os.path.join(root, REVIEW_DIR, full))
    return path


async def resume_line_attachments(runtime, conv_id: str, resume) -> tuple[list[str], list[str]]:
    """Detach and resume every live attachment on one line, best-effort."""
    live = live_attachments(runtime.db, conv_id, include_children=False)
    att_ids = [att["id"] for att in live]
    names = {att["id"]: att["name"] for att in live}
    resumed: list[str] = []
    failed: list[str] = []
    for att_id in att_ids:
        try:
            await detach_attachment(runtime, att_id)
        except Exception:
            logger.exception("write-set approval could not detach %s on %s", att_id, conv_id)
            failed.append(names[att_id])
            continue
        try:
            await resume_with_backlog(runtime, att_id, resume)
        except Exception:
            logger.exception("write-set approval could not resume %s on %s", att_id, conv_id)
            failed.append(names[att_id])
        else:
            resumed.append(att_id)
    return resumed, failed


def non_resumable_live_attachments(runtime, conv_id: str) -> list[dict]:
    return [
        att for att in live_attachments(runtime.db, conv_id, include_children=False)
        if not adapter_can_resume(ADAPTER_METADATA.get(att["adapter"], {}))
    ]


async def file_write_set_request(
    runtime, conv_id: str, path: str, principal, *, announce_fn,
) -> WriteSetGrantRequest:
    db = runtime.db
    if get_pending_request(db, conv_id) is not None:
        raise HTTPException(409, "a write-set request is already waiting for a person")
    if not machine_may_file(db, principal, conv_id):
        raise HTTPException(
            403, "only a person or a captain above this line may grant write scope")
    path = validate_grantable(db, path)
    request = WriteSetGrantRequest(
        id=uuid.uuid4().hex[:12],
        conversation_id=conv_id,
        path=path,
        requester=principal.name,
        requester_attachment_id=principal.attachment_id,
        created_at=time.time(),
    )
    with db.lock:
        db.conn.execute(
            "INSERT INTO conversation_write_grant_requests"
            "(conv_id,id,path,requester,requester_attachment_id,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (conv_id, request.id, path, request.requester,
             request.requester_attachment_id, request.created_at))
        db.conn.commit()
    await announce_fn(
        conv_id,
        f"☏ @{principal.name} asks a person to grant write-set scope for `{path}` — "
        "approve or decline from the banner",
        actor=principal,
    )
    await bubble_approval(
        runtime, conv_id, kind="write-set", requester=principal.name,
        detail=f"grant write scope for `{path}`",
        approve=f"POST /api/conversations/{conv_id}/write-set/request/{request.id}/approve",
        decline=f"POST /api/conversations/{conv_id}/write-set/request/{request.id}/deny",
        actor=principal,
    )
    return request
