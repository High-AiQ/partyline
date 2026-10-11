"""Deterministic pre-review checks and the post-accept tree sync (finding 2.6).

The two worst defects of the 3d-game day were invisible to every model: a
merged cue table referencing 72 files that were never in git (built only in
the line's worktree, under a gitignored ``out/``), and a fast-forward that
moved a branch without updating the checked-out worktree, shipping stale
exports. Both are checkable without judgment, so they run without a model:
``referenced_paths`` reads exactly the bytes of a commit and reports every
path-like JSON reference that the commit does not track, flagging the ones
the working disk hides behind ``.gitignore``; ``tree_sync_check`` reports —
never fixes — whether a worktree holding the accepted branch actually sits
at the accepted SHA with a clean status.
"""

from __future__ import annotations

import json
import os
import re

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .hierarchy_contracts import PrereviewIn, PrereviewOut
from .line_worktree import _git, line_cwd, rev
from .machine_scope import deny_unless
from .review_worktrees import ReviewError, subtree_repository

_SHA = re.compile(r"[0-9a-f]{4,64}")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
MAX_MISSING = 200
MAX_FILES = 500
KNOWN_CHECKS = ("referenced-paths",)


def _walk_strings(node) -> list[str]:
    """Every string value in a JSON document, however it is nested."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _walk_strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in _walk_strings(value)]
    return []


def _looks_like_path(value: str) -> bool:
    """A relative file path, not a URL, a scheme URI, or a plain word."""
    if not value or value.startswith("/"):
        return False
    if _SCHEME.match(value):
        return False
    return "/" in value or bool(_EXTENSION.search(value))


def _under(path: str, data_paths: list[str]) -> bool:
    for entry in data_paths:
        prefix = entry.strip().strip("/")
        if prefix and (path == prefix or path.startswith(prefix + "/")):
            return True
    return False


def referenced_paths(db, conv_id: str, sha: str, data_paths: list[str],
                     repository: str = "") -> dict:
    """Path-like JSON references in a commit that the commit does not track.

    Everything is read from the commit itself — ``ls-tree`` and ``show`` —
    so the answer is about exactly those bytes, never a worktree that may be
    ahead, behind, or carrying uncommitted scratch. A reference the commit
    does not track is missing; one the checkout's ignore rules hide is
    reported as ignored too, because that is the ``out/`` incident: real on
    disk, absent from every commit, gone on any other machine.
    """
    root = subtree_repository(db, conv_id, repository)
    name = (sha or "").strip().lower()
    if not _SHA.fullmatch(name):
        raise ReviewError(400, "pass the commit SHA (hex) to check")
    full = rev(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
    if full is None:
        raise ReviewError(400, f"no commit {name} in this repository")
    listed = _git("ls-tree", "-r", "--name-only", full, cwd=root)
    if listed.returncode != 0:
        raise ReviewError(409, "cannot read the commit's file tree")
    tracked = set(listed.stdout.splitlines())
    # The ignore rules that matter are the line's own checkout's: the out/
    # incident was a file the line's worktree held and its .gitignore hid.
    probe = line_cwd(db, conv_id) or root
    if not os.path.isdir(probe):
        probe = root
    blobs = sorted(path for path in tracked
                   if path.endswith(".json") and _under(path, data_paths))[:MAX_FILES]
    missing: list[dict] = []
    checked = 0
    for blob in blobs:
        shown = _git("show", f"{full}:{blob}", cwd=root)
        if shown.returncode != 0:
            continue
        try:
            payload = json.loads(shown.stdout)
        except ValueError:
            continue  # a malformed table is not this check's finding
        for value in _walk_strings(payload):
            if not _looks_like_path(value):
                continue
            checked += 1
            if value in tracked:
                continue
            ignored = _git("check-ignore", "-q", "--", value, cwd=probe).returncode == 0
            missing.append({"file": blob, "ref": value, "ignored": ignored})
            if len(missing) >= MAX_MISSING:
                return {"ok": False, "missing": missing, "checked": checked}
    return {"ok": not missing, "missing": missing, "checked": checked}


def tree_sync_check(root: str, branch: str, full: str) -> dict:
    """After an accept: does any worktree holding the branch actually hold it?

    Reporting only — a stale or dirty checkout is named in the accept
    response and the ☏ notice, and a person or captain decides what to do.
    """
    done = _git("worktree", "list", "--porcelain", cwd=root)
    if done.returncode != 0:
        return {"ok": False, "worktree": None, "detail": "cannot list worktrees"}
    wanted = f"refs/heads/{branch}"
    holder = None
    current: dict[str, str] = {}
    for line in done.stdout.splitlines():
        if line.startswith("worktree "):
            current = {"path": line[len("worktree "):].strip()}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch ") and line[len("branch "):].strip() == wanted:
            holder = dict(current)
    if holder is None:
        return {"ok": True, "worktree": None,
                "detail": f"no worktree holds {branch} checked out"}
    path = holder["path"]
    if holder.get("head") != full:
        return {"ok": False, "worktree": path,
                "detail": f"worktree HEAD is {(holder.get('head') or '?')[:12]}, "
                          f"the accepted SHA is {full[:12]}"}
    status = _git("status", "--short", cwd=path)
    if status.returncode != 0:
        return {"ok": False, "worktree": path, "detail": "git status failed"}
    changes = len([line for line in status.stdout.splitlines() if line.strip()])
    if changes:
        return {"ok": False, "worktree": path,
                "detail": f"{changes} uncommitted change(s) in the worktree"}
    return {"ok": True, "worktree": path,
            "detail": "worktree HEAD and status match the accepted branch"}


def register_prereview_route(app, runtime) -> None:
    @app.post("/api/conversations/{conv_id}/prereview", response_model=PrereviewOut)
    async def prereview(request: Request, conv_id: str, body: PrereviewIn):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        unknown = sorted(set(body.checks) - set(KNOWN_CHECKS))
        if unknown:
            raise HTTPException(422, f"unknown checks: {', '.join(unknown)}")
        try:
            done = referenced_paths(
                db, conv_id, body.sha, body.data_paths, body.repository)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        return PrereviewOut(**done)
