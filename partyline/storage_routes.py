"""Storage usage and clearing of regenerable data; people only, measured on request."""

from __future__ import annotations

import asyncio
import os
import shutil

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import attachment_tmp, storage_survey as survey
from .auth_guard import request_principal
from .line_worktree import _git
from .review_worktrees import remove_review_path
from .scratch_worktrees import remove_scratch_path
from .system_notice import post_system_notice

CLEARABLE = {"sessions": survey.session_candidates, "tmp": survey.tmp_candidates,
             "review": survey.review_candidates, "scratch": survey.scratch_candidates}


CLEARABLE_LABELS = {"sessions": "CLI session homes", "tmp": "temporary files",
                    "review": "review checkouts", "scratch": "scratch worktrees"}


class ClearIn(BaseModel):
    conv_id: str | None = Field(default=None, max_length=200)


def _human(request: Request):
    principal = request_principal(request)
    if principal.kind != "user":
        raise HTTPException(403, "only people can inspect or clear storage")
    return principal


def _describe(category: survey.Category, budget: survey.Budget) -> dict:
    entries = [*category.candidates, *(item["path"] for item in category.skipped)]
    sizes = {path: budget.size(path) for path in entries}
    other = sum(budget.size(path, frozenset(entries)) for path in category.paths if os.path.lexists(path))
    clear = category.candidates
    return {"key": category.key, "label": category.label, "paths": category.paths,
            "bytes": sum(sizes.values()) + other, "clearable": category.clearable,
            "clearable_bytes": sum(sizes[path] for path in clear), "clearable_count": len(clear),
            "candidates": clear[:5], "approximate": budget.approximate}


def _fixed(db, media_root) -> list[survey.Category]:
    files = [db.path, f"{db.path}-wal", f"{db.path}-shm"]
    return [survey.fixed_category("media", "Media", [media_root()]),
            survey.fixed_category("database", "Database", [p for p in files if os.path.exists(p)])]


def survey_all(db, media_root) -> list[dict]:
    categories = [build(db) for build in CLEARABLE.values()] + _fixed(db, media_root)
    budget, result = survey.Budget(), []
    for position, category in enumerate(categories):
        result.append(_describe(category, budget.slice(len(categories) - position)))
    return result


def _remove(db, key: str, path: str) -> int | None:
    """Remove one candidate; the bytes freed, or None when it could not be removed."""
    if key == "tmp":
        return attachment_tmp.reap_tmp_dir(os.path.basename(path))
    if os.path.islink(path) or not os.path.isdir(path):
        return None
    size = survey.Budget().size(path)
    if key == "sessions":
        shutil.rmtree(path, ignore_errors=True)
    else:
        remove = remove_review_path if key == "review" else remove_scratch_path
        if not remove(path):
            return None
        marker = f"/.{'review' if key == 'review' else 'scratch'}/"
        _git("worktree", "prune", cwd=path.split(marker, 1)[0])
        table = "review_worktrees" if key == "review" else "scratch_worktrees"
        db._exec(f"DELETE FROM {table} WHERE path=?", (path,))
    return None if os.path.exists(path) else size


def clear(db, key: str) -> dict:
    category = CLEARABLE[key](db)  # candidates are re-checked now, not trusted from a listing
    removed, freed = [], 0
    skipped = list(category.skipped)
    for path in category.candidates:
        done = _remove(db, key, path)
        if done is None:
            skipped.append({"path": path, "reason": "it could not be removed"})
        else:
            removed.append(path)
            freed += done
    return {"removed": removed, "freed_bytes": freed, "skipped": skipped}


def _root_line(db, conv_id: str | None) -> str | None:
    current = db.get_conversation(conv_id) if conv_id else None
    while current and current.get("parent_id"):
        current = db.get_conversation(current["parent_id"])
    if current:
        return current["id"]
    roots = [conv for conv in db.list_conversations() if not conv.get("parent_id")]
    return roots[0]["id"] if roots else None


def human_bytes(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1000
    return f"{count} B"


def storage_router(runtime, media_root) -> APIRouter:
    router = APIRouter()
    db = runtime.db

    @router.get("/api/storage")
    async def usage(request: Request):
        _human(request)
        return await asyncio.to_thread(survey_all, db, media_root)

    @router.post("/api/storage/{key}/clear")
    async def clear_category(request: Request, key: str, body: ClearIn | None = None):
        principal = _human(request)
        if key not in CLEARABLE:
            raise HTTPException(404, "that category cannot be cleared")
        result = await asyncio.to_thread(clear, db, key)
        line = _root_line(db, body.conv_id if body else None)
        if line and result["removed"]:
            await post_system_notice(
                runtime, line, f"storage cleared by @{principal.name}: "
                f"{CLEARABLE_LABELS[key]}, {human_bytes(result['freed_bytes'])}")
        return result

    return router

