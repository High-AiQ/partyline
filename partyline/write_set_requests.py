"""A line asks for extra write scope; a person (or a captain above) decides it.

The default write set is derived at spawn. When work needs a path outside it,
a process on the line — or a captain above — files a request; every open tab
on that line shows it, and a person approves or declines. Approval records
the grant, rings the requester, and resumes the line's live processes so the
widened bind applies without a service restart.
"""

from __future__ import annotations

import logging
import json
import os
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .adapters import ADAPTER_METADATA
from .approval_bubble import bubble_approval
from . import docker_relay, docker_workloads
from .hierarchy import ancestors
from .fence_protect import protected_repo_roots
from .write_set_routing import _covers, eligible_captain
from .line_process_routes import detach_attachment, live_attachments
from .line_worktree import REVIEW_DIR, rev
from .resume_continuation import resume_with_backlog
from .restart_capabilities import adapter_can_resume
from .review_worktrees import ReviewError, subtree_repository

logger = logging.getLogger(__name__)


class WriteSetGrantRequest(BaseModel):
    id: str
    conversation_id: str
    path: str
    paths: list[str] = Field(default_factory=list)
    human_only: bool = False
    decider_name: str = ""
    already_granted: list[str] = Field(default_factory=list)
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
    paths = json.loads(row.get("paths") or "[]") or [row["path"]]
    return WriteSetGrantRequest(
        id=row["id"],
        conversation_id=row["conv_id"],
        path=row["path"],
        paths=paths,
        human_only=bool(row.get("human_only", 0)),
        decider_name=row.get("decider_name", ""),
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

    Refuse unusable paths at filing time, because a grant the fence cannot use
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
    if docker_relay.is_docker_socket(path):
        return path  # docker access: relayed, not bound; only a person approves
    resolved = os.path.realpath(path)
    roots = protected_repo_roots(db)
    if not any(
        resolved == root or resolved.startswith(root.rstrip(os.sep) + os.sep)
        for root in roots
    ):
        raise HTTPException(
            400, f"{path} is already writable outside the protected repositories "
                 "— no grant needed")
    if not os.path.exists(resolved):
        ancestor = os.path.dirname(resolved)
        while not os.path.isdir(ancestor):
            ancestor = os.path.dirname(ancestor)
        raise HTTPException(
            400, f"{path}: path does not exist; request the nearest existing "
                 f"ancestor directory {ancestor} instead, or ask a person to "
                 "create the path first")
    if not (
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
            await detach_attachment(runtime, att_id, survivors=False, expire=False)
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


def grant_scope(runtime, conv_id: str, path: str) -> list[str]:
    """The lines a grant of ``path`` resumes: its own, or — for docker access —
    every line, since all of them must pick up the mount that hides the relays."""
    if not docker_relay.is_docker_socket(path):
        return [conv_id]
    return [conv_id, *(c["id"] for c in runtime.db.list_conversations() if c["id"] != conv_id)]


def non_resumable_live_attachments(runtime, conv_id: str, path: str | None = None) -> list[dict]:
    return [
        att for line in (grant_scope(runtime, conv_id, path) if path else [conv_id])
        for att in live_attachments(runtime.db, line, include_children=False)
        if not adapter_can_resume(ADAPTER_METADATA.get(att["adapter"], {}))
    ]


async def resume_granted_scope(runtime, conv_id: str, path: str, resume,
                               resumer=None) -> tuple[list[str], list[str]]:
    resumed: list[str] = []
    failed: list[str] = []
    for line in grant_scope(runtime, conv_id, path):
        done, broke = await (resumer or resume_line_attachments)(runtime, line, resume)
        resumed += done
        failed += broke
    return resumed, failed


async def file_write_set_request(
    runtime, conv_id: str, paths: list[str], principal, *, announce_fn,
) -> WriteSetGrantRequest:
    db = runtime.db
    paths = list(dict.fromkeys(validate_grantable(db, path) for path in paths))
    if not machine_may_file(db, principal, conv_id):
        named = ", ".join(f"`{path}`" for path in paths)
        raise HTTPException(
            403, f"none of these paths were filed: {named}; only a person or a captain above "
                 "this line may request write scope")
    grants = db._exec("SELECT path FROM conversation_write_grants WHERE conv_id=?", (conv_id,)).fetchall()
    already = [path for path in paths if any(_covers(row["path"], path) for row in grants)]
    paths = [path for path in paths if path not in already]
    if not paths:
        return WriteSetGrantRequest(
            id="", conversation_id=conv_id, path=already[0] if already else "",
            paths=already, requester=principal.name,
            requester_attachment_id=principal.attachment_id, created_at=time.time(),
        )
    pending = get_pending_request(db, conv_id)
    if pending:
        old_paths = json.loads(pending.get("paths") or "[]") or [pending["path"]]
        paths = list(dict.fromkeys([*old_paths, *paths]))
    decider = eligible_captain(db, conv_id, paths, principal.attachment_id)
    human_only = decider is None
    all_paths = paths
    request = WriteSetGrantRequest(
        id=uuid.uuid4().hex[:12],
        conversation_id=conv_id,
        path=paths[0],
        paths=paths,
        human_only=human_only,
        decider_name=decider["name"] if decider else "",
        already_granted=already,
        requester=principal.name,
        requester_attachment_id=principal.attachment_id,
        created_at=time.time(),
    )
    with db.lock:
        if pending:
            request.id = pending["id"]
            request.requester = pending["requester"]
            request.requester_attachment_id = pending["requester_attachment_id"]
            request.created_at = pending["created_at"]
            db.conn.execute(
                "UPDATE conversation_write_grant_requests SET path=?,paths=?,human_only=?,decider_name=? "
                "WHERE conv_id=?",
                (paths[0], json.dumps(paths), int(human_only), request.decider_name, conv_id))
        else:
            db.conn.execute(
                "INSERT INTO conversation_write_grant_requests"
                "(conv_id,id,path,requester,requester_attachment_id,created_at,paths,"
                "human_only,decider_name) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (conv_id, request.id, paths[0], request.requester,
                 request.requester_attachment_id, request.created_at, json.dumps(paths),
                 int(human_only), request.decider_name))
        db.conn.commit()
    has_docker = any(docker_relay.is_docker_socket(path) for path in paths)
    warning = f" — {docker_workloads.BUDGET_WARNING}" if has_docker else ""
    listed = ", ".join(f"`{path}`" for path in all_paths)
    decider_text = "a person decides" if human_only else f"@{request.decider_name} may decide"
    waiting = "waiting on a person" if human_only else "waiting for a write-set decision"
    await announce_fn(
        conv_id,
        f"☏ @{principal.name} asks to grant write-set scope for {listed}{warning} — "
        f"{decider_text}; {waiting}",
        actor=principal,
    )
    await bubble_approval(runtime, conv_id, kind="write-set", requester=principal.name,
        detail=f"grant write scope for {listed}{warning}",
        approve=f"POST /api/conversations/{conv_id}/write-set/request/{request.id}/approve",
        decline=f"POST /api/conversations/{conv_id}/write-set/request/{request.id}/deny",
        actor=principal, human_only=human_only,
        decider_name=request.decider_name)
    return request
