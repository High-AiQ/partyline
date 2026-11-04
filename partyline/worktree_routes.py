"""Human management of preserved managed worktrees across known repositories."""

import os
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel

from .auth_guard import request_principal
from .git_fence import mirror_branch_ref
from .worktree_paths import branch_name
from .line_worktree import WORKTREES_DIR, _git, repo_root
from .system_notice import post_system_notice
from .worktree_cleanup import cleanup, preserve_tip, preserved_refs
from .task_workspaces import workspaces
from .worktree_lifecycle import _default_branch, _in_history, _workspace_merged, worktree_state
from .worktree_storage import kept_reason, latest_snapshot, repositories


class KeptWorktree(BaseModel):
    path: str
    repository: str
    size_bytes: int
    kept_reason: str
    line_id: str | None = None
    line_name: str | None = None
    owner: Literal["live", "archived", "none"]


class CleanupIn(BaseModel):
    path: str
    force: bool = False
    confirmation: str = ""


class CleanupOut(BaseModel):
    removed: bool
    kept_reason: str | None = None
    snapshot: str | None = None
    preserved_refs: list[str] = []


def known_worktrees(db):
    lines = db.list_conversations(archived=False) + db.list_conversations(archived=True)
    cwds = {row["cwd"] for row in lines if row.get("cwd")}
    cwds |= {row["cwd"] for row in db._exec(
        "SELECT DISTINCT cwd FROM attachments WHERE cwd IS NOT NULL AND cwd != ''").fetchall()}
    roots = {root for cwd in cwds if (root := repo_root(cwd))}
    roots |= {row["repository"] for row in db._exec("SELECT repository FROM task_workspaces").fetchall()}
    owners = {os.path.realpath(row["cwd"]): row for row in lines if row.get("cwd")}
    for row in db._exec("SELECT path, conv_id FROM task_workspaces").fetchall():
        if conv := db.get_conversation(row["conv_id"]):
            owners[os.path.realpath(row["path"])] = conv
    for root in sorted(roots):
        directory = Path(root) / WORKTREES_DIR
        paths = set(directory.iterdir()) if directory.is_dir() else set()
        listing = _git("worktree", "list", "--porcelain", "-z", cwd=root)
        if listing.returncode == 0:
            paths |= {Path(field.removeprefix("worktree "))
                      for field in listing.stdout.split("\0")
                      if field.startswith("worktree ") and
                      f"/{WORKTREES_DIR}/" in field.replace("\\", "/")}
        for path in sorted(paths):
            if path != Path(root) and path.is_dir() and not path.is_symlink():
                yield root, str(path), owners.get(os.path.realpath(path))


def merged_state(db, root, path, owner):
    if owner:
        item = next((item for item in workspaces(db, owner["id"]) if item["path"] == path), None)
        if item:
            return _workspace_merged(db, owner["id"], item)
    if owner and owner.get("cwd") == path:
        state = worktree_state(db, owner)
        return bool(state and state["merged"])
    base = _default_branch(root)
    return bool(base and _in_history(path, "HEAD", [base]))


def size_bytes(path):
    size = 0
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in [*dirs, *files]:
            try:
                entry = Path(directory) / name
                if entry.is_symlink() or entry.is_file():
                    size += entry.lstat().st_size
            except OSError:
                pass
    return size


def list_kept(db):
    result = []
    for root, path, owner in known_worktrees(db):
        nested = repositories(path)
        merged = merged_state(db, root, path, owner)
        status = _git("status", "--porcelain", cwd=path)
        reason = ("contains repositories " + ", ".join(nested) if nested else
                  "unmerged commits" if not merged else kept_reason(db, root, path) or
                  ("cannot inspect Git state" if status.returncode else
                   "uncommitted changes" if status.stdout.strip() else "awaiting cleanup"))
        result.append(KeptWorktree(
            path=path, repository=root, size_bytes=size_bytes(path), kept_reason=reason,
            line_id=owner["id"] if owner else None, line_name=owner["name"] if owner else None,
            owner=("archived" if owner.get("archived_at") else "live") if owner else "none"))
    return result


def human(request):
    if request_principal(request).kind != "user":
        raise HTTPException(403, "worktree management is human-only")


def register_worktree_routes(app, runtime):
    @app.get("/api/worktrees", response_model=list[KeptWorktree])
    def index(request: Request):
        human(request)
        return list_kept(runtime.db)

    @app.post("/api/worktrees/cleanup", response_model=CleanupOut)
    async def clean(request: Request, body: CleanupIn):
        import asyncio

        human(request)
        db = runtime.db
        candidate = next((item for item in known_worktrees(db) if item[1] == body.path), None)
        if candidate is None:
            raise HTTPException(404, "unknown managed worktree")
        root, path, owner = candidate
        if owner and not owner.get("archived_at"):
            raise HTTPException(409, "archive the owning line before cleaning its worktree")
        if body.force and body.confirmation != path:
            raise HTTPException(400, "confirm force removal by repeating the full path")
        if body.force and owner:
            from .task_teardown import preserve

            await asyncio.to_thread(preserve, db, owner["id"])
            mirror = mirror_branch_ref(path, owner["id"], branch_name(path))
            if mirror:
                try:
                    await asyncio.to_thread(preserve_tip, root, path, mirror)
                except (OSError, ValueError) as exc:
                    raise HTTPException(409, "cannot preserve line mirror tip") from exc
        previous = latest_snapshot(db, root, path)
        removed, reason = await asyncio.to_thread(
            cleanup, db, root, path, merged_state(db, root, path, owner), force=body.force)
        snapshot = latest_snapshot(db, root, path) if removed and not body.force else None
        snapshot = snapshot if snapshot != previous else None
        if owner and snapshot:
            await post_system_notice(runtime, owner["id"], f"☏ worktree changes saved to {snapshot}")
        return CleanupOut(removed=removed, kept_reason=reason, snapshot=snapshot,
                          preserved_refs=preserved_refs(root, path) if removed and body.force else [])
