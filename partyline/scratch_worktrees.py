"""Scratch worktrees: throwaway writable checkouts for integration builds.

A review checkout is for adversarial reads, but verifying an integration —
build the levels with a candidate toolkit, run the walks — needs to write
`generated/` and `out/` inside a checkout at the reviewed SHA. A scratch
worktree is that home: detached, at ``<repo>/.scratch/<full sha>``, excluded
from git status, recorded on the calling line, pruned when the line retires
— never on accept, and never confused with a review. It reuses the review
machinery's shape and helpers rather than copying it, and the fence binds
recorded scratch checkouts writable so a line's own process needs no
write-set request.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .line_worktree import _exclude, _git, rev
from .machine_scope import deny_unless
from .review_worktrees import (
    ReviewError,
    _SHA_DIR,
    _pinned_at,
    _registered,
    _SHA,
    subtree_repository,
)
from .system_notice import post_system_notice

logger = logging.getLogger(__name__)

SCRATCH_DIR = ".scratch"
_MERGED_NAME = re.compile(r"[0-9a-f]{40}-onto-[0-9a-f]{40}")


class ScratchWorktreeIn(BaseModel):
    sha: str = Field(min_length=4, max_length=64)
    repository: str = Field(default="", max_length=4096)
    # 5.5: a trial merge — the checkout starts at this ref as the host sees
    # it, then the candidate SHA is merged in. Conflicts abort the merge and
    # answer 409 with the conflicting paths; nothing is left half-merged.
    merge_onto: str = Field(default="", max_length=256)


class ScratchMerge(BaseModel):
    onto: str
    result: str = ""
    conflicts: list[str] = Field(default_factory=list)


class ScratchWorktreeOut(BaseModel):
    conv_id: str
    sha: str
    path: str
    created_at: float
    merge: ScratchMerge | None = None


MERGE_IDENTITY = ("-c", "user.name=partyline", "-c", "user.email=partyline@lan")


def create_scratch_worktree(db, conv_id: str, sha: str, repository: str = "",
                            merge_onto: str = "") -> dict:
    """Check a SHA out at ``<repo>/.scratch/<sha>`` and record it on the line.

    The repository is the line's own or one of its subtree's, the same rule a
    review worktree obeys. Creating the same SHA twice hands back the same
    checkout. With ``merge_onto`` the checkout starts at that ref as the host
    sees it and the candidate is merged in with ``--no-ff`` under a fixed
    partyline identity — the integration check in one call — and the row is
    keyed ``<sha>-onto-<onto sha>``, so it cannot collide with a plain
    checkout at the same SHA; pruning and sweeping recognise it by the same
    key. Conflicts abort the merge and answer 409 with the conflicting paths;
    nothing is left half-merged. Nothing prunes on accept.
    """
    conv = db.get_conversation(conv_id)
    if conv is None:
        raise ReviewError(404, "line not found")
    root = subtree_repository(db, conv_id, repository)
    name = (sha or "").strip().lower()
    if not _SHA.fullmatch(name):
        raise ReviewError(400, "pass the commit SHA (hex) to check out")
    full = rev(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
    if full is None:
        raise ReviewError(400, f"no commit {name} in this repository")
    onto_name = (merge_onto or "").strip()
    onto_sha = ""
    if onto_name:
        # A ref-shaped value is the only thing allowed near rev-parse: a flag
        # (leading "-") or a malformed name is refused, not guessed around.
        if onto_name.startswith("-") or not _SHA.fullmatch(onto_name):
            if _git("check-ref-format", "--allow-onelevel",
                    onto_name, cwd=root).returncode != 0:
                raise ReviewError(
                    422, f"merge_onto is not a valid ref or SHA: {onto_name}")
        onto_sha = rev(root, "rev-parse", "--verify", "--quiet",
                       f"{onto_name}^{{commit}}")
        if onto_sha is None:
            raise ReviewError(400, f"no ref {onto_name} in this repository")
    key = f"{full}-onto-{onto_sha}" if onto_sha else full
    path = os.path.realpath(os.path.join(root, SCRATCH_DIR, key))
    existing = db._exec(
        "SELECT created_at FROM scratch_worktrees WHERE conv_id=? AND sha=?",
        (conv_id, key)).fetchone()
    if existing and os.path.isdir(path) and _registered(root, path):
        merge = _merge_info(path, onto_sha) if onto_sha else None
        return {"conv_id": conv_id, "sha": key, "path": path,
                "created_at": existing["created_at"], "merge": merge}
    os.makedirs(os.path.join(root, SCRATCH_DIR), exist_ok=True)
    _exclude(root, SCRATCH_DIR)
    if os.path.isdir(path) and not _registered(root, path):
        # A directory git does not know is not a checkout — replace it, never
        # adopt it; under .scratch it is partyline's.
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.isdir(path) and not _pinned_at(root, path, full):
        if not remove_scratch_path(path):
            raise ReviewError(
                409, f"a stale scratch checkout occupies {path} and git will not release it")
    if not os.path.isdir(path):
        _git("worktree", "prune", cwd=root)
        base = onto_sha or full
        done = _git("worktree", "add", "--detach", path, base, cwd=root)
        if done.returncode != 0:
            detail = (done.stderr or "").strip().splitlines()
            raise ReviewError(
                409, f"cannot create the scratch worktree: {detail[-1] if detail else 'git failed'}"
            )
    merge = None
    if onto_sha:
        merged = _git(*MERGE_IDENTITY, "merge", "--no-ff", "--no-edit",
                      full, cwd=path)
        if merged.returncode != 0:
            conflicts = sorted(_git("diff", "--name-only", "--diff-filter=U",
                                    cwd=path).stdout.splitlines())
            _git("merge", "--abort", cwd=path)
            raise ReviewError(409, {"merge": {"onto": onto_sha,
                                              "conflicts": conflicts}})
        merge = {"onto": onto_sha, "result": rev(path, "rev-parse", "HEAD") or "",
                 "conflicts": []}
    created_at = time.time()
    db._exec(
        "INSERT INTO scratch_worktrees(conv_id,sha,path,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(conv_id,sha) DO UPDATE SET path=excluded.path, "
        "created_at=excluded.created_at",
        (conv_id, key, path, created_at),
    )
    return {"conv_id": conv_id, "sha": key, "path": path, "created_at": created_at,
            "merge": merge}


def _merge_info(path: str, onto_sha: str) -> dict:
    return {"onto": onto_sha, "result": rev(path, "rev-parse", "HEAD") or "",
            "conflicts": []}


def list_scratch_worktrees(db, conv_id: str) -> list[dict]:
    return [
        dict(row) for row in db._exec(
            "SELECT conv_id, sha, path, created_at FROM scratch_worktrees "
            "WHERE conv_id=? ORDER BY created_at", (conv_id,),
        ).fetchall()
    ]


def remove_scratch_path(path: str) -> bool:
    """Delete one scratch checkout directory; False only if rmtree also failed.

    A scratch checkout holds build output, nothing owed to anyone, so removal
    never gives up: git first, then the directory itself — a hand-made or
    half-created tree under ``.scratch`` is still partyline's to delete.
    """
    if not os.path.isdir(path):
        return True  # already gone by hand; only the record is stale
    marker = f"/{SCRATCH_DIR}/"
    root = path.split(marker, 1)[0] if marker in path else None
    if root and os.path.isdir(root):
        done = _git("worktree", "remove", "--force", "--force", path, cwd=root)
        if done.returncode == 0:
            return True
        logger.warning("scratch worktree prune: git refused %s; removing the tree", path)
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.isdir(path)


def drop_scratch_worktree(db, conv_id: str, sha: str) -> dict | None:
    """Drop one of the line's scratch checkouts early; None when it has none."""
    rows = db._exec(
        "SELECT sha, path FROM scratch_worktrees WHERE conv_id=?", (conv_id,)).fetchall()
    name = (sha or "").strip().lower()
    matches = [row for row in rows if row["sha"] == name or row["sha"].startswith(name)]
    if len(matches) != 1:
        return None
    row = matches[0]
    if not remove_scratch_path(row["path"]):
        raise ReviewError(409, "git refused to release the scratch checkout; try again")
    db._exec("DELETE FROM scratch_worktrees WHERE conv_id=? AND sha=?",
             (conv_id, row["sha"]))
    return {"sha": row["sha"], "path": row["path"]}


def prune_scratch_worktrees(db, conv_id: str) -> int:
    """Drop every scratch checkout recorded for the line (retirement, purge)."""
    removed = 0
    for row in db._exec(
            "SELECT path FROM scratch_worktrees WHERE conv_id=?", (conv_id,)).fetchall():
        if remove_scratch_path(row["path"]):
            db._exec("DELETE FROM scratch_worktrees WHERE conv_id=? AND path=?",
                     (conv_id, row["path"]))
            removed += 1
    return removed


def sweep_scratch_worktrees(db, root: str) -> None:
    """Startup sweep for one repository's ``.scratch`` directory.

    Same contract as the review sweep: only full-SHA directories are
    partyline's, a checkout whose line is gone or archived is a leftover,
    and a record whose directory vanished is deleted.
    """
    directory = os.path.join(root, SCRATCH_DIR)
    if not os.path.isdir(directory):
        return
    rows = {row["path"]: row["conv_id"] for row in
            db._exec("SELECT path, conv_id FROM scratch_worktrees").fetchall()}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if db._exec("SELECT 1 FROM retirement_preserved_paths WHERE path=?", (path,)).fetchone():
            continue
        if not os.path.isdir(path):
            continue
        if not (_SHA_DIR.fullmatch(name) or _MERGED_NAME.fullmatch(name)):
            continue
        conv = db.get_conversation(rows[path]) if path in rows else None
        if conv is not None and not conv.get("archived_at"):
            continue  # a live line is still building here
        if remove_scratch_path(path):
            db._exec("DELETE FROM scratch_worktrees WHERE path=?", (path,))
            logger.info("scratch worktree sweep: removed %s", path)
    for path in rows:
        if not os.path.isdir(path):
            db._exec("DELETE FROM scratch_worktrees WHERE path=?", (path,))


def register_scratch_routes(app, runtime) -> None:
    @app.post(
        "/api/conversations/{conv_id}/scratch-worktrees",
        response_model=ScratchWorktreeOut, status_code=201,
    )
    async def create(request: Request, conv_id: str, body: ScratchWorktreeIn):
        db = runtime.db
        # Creation writes into the repository: a mutating act, not a read.
        deny_unless(db, request_principal(request), conv_id, "write")
        principal = request_principal(request)
        try:
            done = create_scratch_worktree(db, conv_id, body.sha, body.repository,
                                           body.merge_onto)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        await post_system_notice(
            runtime,
            conv_id,
            f"⚒ scratch worktree: {done['path']} — detached at {done['sha'][:12]}, writable "
            "for integration builds; partyline prunes it when the line retires",
            actor=principal,
        )
        return done

    @app.get(
        "/api/conversations/{conv_id}/scratch-worktrees",
        response_model=list[ScratchWorktreeOut],
    )
    def index(request: Request, conv_id: str):
        deny_unless(runtime.db, request_principal(request), conv_id, "read")
        return list_scratch_worktrees(runtime.db, conv_id)

    @app.delete("/api/conversations/{conv_id}/scratch-worktrees/{sha}")
    async def drop(request: Request, conv_id: str, sha: str):
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "write")
        try:
            dropped = drop_scratch_worktree(db, conv_id, sha)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        if dropped is None:
            raise HTTPException(404, "no scratch checkout matches that sha on this line")
        await post_system_notice(
            runtime, conv_id,
            f"⚒ scratch worktree dropped by @{principal.name}: {dropped['path']}",
            actor=principal,
        )
        return {"ok": True, "sha": dropped["sha"], "path": dropped["path"]}
