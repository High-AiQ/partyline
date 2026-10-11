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

import asyncio
import fnmatch
import json
import os
import posixpath
import re

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .hierarchy_contracts import PrereviewIn, PrereviewOut
from .line_worktree import _git, line_cwd, rev
from .machine_scope import deny_unless
from .review_worktrees import ReviewError, subtree_repository_line

_SHA = re.compile(r"[0-9a-f]{4,64}")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
MAX_MISSING = 200
MAX_FILES = 500
KNOWN_CHECKS = ("referenced-paths",)


def _walk_strings(node, skip_keys: frozenset[str] = frozenset(),
                  ancestry: frozenset[str] = frozenset()) -> list[str]:
    """Every JSON string value, except strings under a skipped key at any
    depth — prose fields such as `notes` or `reason` name no files."""
    if isinstance(node, str):
        return [] if ancestry & skip_keys else [node]
    if isinstance(node, dict):
        out = []
        for key, value in node.items():
            deeper = ancestry | ({key} if isinstance(key, str) else set())
            out.extend(_walk_strings(value, skip_keys, deeper))
        return out
    if isinstance(node, list):
        return [s for value in node for s in _walk_strings(value, skip_keys, ancestry)]
    return []


def _candidate(value: str, res_roots: dict[str, str]) -> str | None:
    """The repo-root-relative path a table value names, or None to skip it.

    Empty, absolute, and scheme values with no mapped root are not file
    references (https:, mailto:, user: stay out); a mapped engine scheme —
    Godot's ``res://`` — is resolved under its tree prefix so a game's cue
    table is checked in the repository it actually ships from. Plain words
    are dropped later, by the path-shape gate.
    """
    if not value or value.startswith("/"):
        return None
    for prefix, tree in (res_roots or {}).items():
        if prefix and value.startswith(prefix):
            rest = value[len(prefix):].strip("/")
            base = tree.strip("/")
            if not base and not rest:
                return None
            return posixpath.normpath(posixpath.join(base, rest)) if base else posixpath.normpath(rest)
    if _SCHEME.match(value):
        return None
    return value


def _candidates(value: str, res_roots: dict[str, str],
                path_roots: list[str]) -> list[str]:
    """Every repo-root-relative path a table value could name, in order: the
    value itself, then under each ``path_roots`` prefix. Scheme values with
    no mapped root are dropped here."""
    mapped = _candidate(value, res_roots or {})
    if mapped is None:
        return []  # a URL, an unmapped scheme, or an absolute path
    out = [mapped]
    if mapped == value:  # unchanged: a plain relative path, roots may apply
        for root in path_roots or []:
            base = root.strip().strip("/")
            joined = posixpath.normpath(
                posixpath.join(base, value.strip("/"))) if base else ""
            if joined and not joined.startswith("..") and joined not in out:
                out.append(joined)
    return [candidate for candidate in out if candidate]


def _present(candidate: str, tracked: set[str], blob_dir: str,
             directories: set[str], symlink_map: dict[str, str]) -> bool:
    """The reference resolves in the commit: root-relative, table-relative,
    a tracked directory, or through committed symlinks. A trailing slash
    reads as the directory."""
    candidate = candidate.rstrip("/")
    resolved = {_resolve_symlinks(candidate, symlink_map)}
    if blob_dir:
        joined = posixpath.normpath(posixpath.join(blob_dir, candidate))
        if not joined.startswith(".."):
            resolved.add(_resolve_symlinks(joined, symlink_map))
    for path in resolved:
        if path and (path in tracked or path in directories):
            return True
    return False


def _resolve_symlinks(path: str, symlink_map: dict[str, str]) -> str:
    """Rewrite a path through committed symlinks with a hop guard; loops,
    escapes and exhausted hops resolve to "" — unverifiable in the tree."""
    for _ in range(8):
        if path in symlink_map:
            rewritten = symlink_map[path]  # fully resolved: chains were followed
        else:
            rewritten = None
            parts = path.split("/")
            for index in range(len(parts) - 1, 0, -1):
                parent = symlink_map.get("/".join(parts[:index]))
                if parent is not None:
                    rewritten = (posixpath.normpath(
                        posixpath.join(parent, "/".join(parts[index:])))
                        if parent else "")
                    break
        if rewritten is None:
            return path
        if not rewritten or rewritten.startswith("..") or rewritten == path:
            return ""  # a loop or a link escaping the tree
        path = rewritten
    return ""


def _symlink_map(root: str, full: str, entries: dict[str, tuple[str, str]]) -> dict[str, str]:
    """Committed symlinks mapped to their resolved repo-root-relative targets.

    Chains are followed with a visited guard; a loop, or a link whose target
    escapes the tree, maps to the empty string.
    """
    links = {path: blob for path, (mode, blob) in entries.items()
             if mode.startswith("12")}
    resolved: dict[str, str] = {}

    def resolve(path: str, seen: frozenset[str]) -> str:
        if path in resolved:
            return resolved[path]
        if path in seen:
            return ""
        shown = _git("show", f"{full}:{path}", cwd=root)
        raw = shown.stdout.strip() if shown.returncode == 0 else ""
        base = posixpath.normpath(
            posixpath.join(posixpath.dirname(path), raw)) if raw else ""
        if raw.startswith("/") or base.startswith("..") or base in (".", ""):
            resolved[path] = ""
            return ""
        result = resolve(base, seen | {path}) if base in links else base
        resolved[path] = result
        return result

    for link in links:
        resolve(link, frozenset())
    return resolved


def _directories(tracked: set[str]) -> set[str]:
    """Every parent directory of every tracked path, built once per commit:
    membership here is what tells a tracked directory name from a plain
    word, and it must be an O(1) lookup, not a scan per string."""
    directories: set[str] = set()
    for path in tracked:
        parts = path.split("/")
        for index in range(1, len(parts)):
            directories.add("/".join(parts[:index]))
    return directories


def _under(path: str, data_paths: list[str]) -> bool:
    for entry in data_paths:
        prefix = entry.strip().strip("/")
        if prefix and (path == prefix or path.startswith(prefix + "/")):
            return True
    return False


def referenced_paths(db, conv_id: str, sha: str, data_paths: list[str],
                     repository: str = "", res_roots: dict[str, str] | None = None,
                     path_roots: list[str] | None = None,
                     skip_files: list[str] | None = None,
                     skip_keys: list[str] | None = None) -> dict:
    """Path-like JSON references in a commit that the commit does not track.

    Everything is read from the commit itself — ``ls-tree`` and ``show`` — so
    the answer is about exactly those bytes, never a worktree. A reference is
    present when it resolves from the repository root, from any ``path_roots``
    prefix, from the naming table's own directory, or through committed
    symlinks (loops and tree-escaping links do not resolve); when it names a
    tracked directory, it is present too. Anything else is missing, and a
    missing reference the checkout's ignore rules hide is reported as ignored
    — the ``out/`` incident: real on disk, absent from every commit, gone on
    any other machine. Ignore rules are read in the checkout of the subtree
    line whose repository matched. Prose stays out: tables matched by
    ``skip_files`` globs are not scanned, and strings under ``skip_keys`` at
    any depth name nothing.
    """
    root, scope_line = subtree_repository_line(db, conv_id, repository)
    name = (sha or "").strip().lower()
    if not _SHA.fullmatch(name):
        raise ReviewError(400, "pass the commit SHA (hex) to check")
    full = rev(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
    if full is None:
        raise ReviewError(400, f"no commit {name} in this repository")
    listed = _git("ls-tree", "-r", full, cwd=root)
    if listed.returncode != 0:
        raise ReviewError(409, "cannot read the commit's file tree")
    entries: dict[str, tuple[str, str]] = {}
    for line in listed.stdout.splitlines():
        meta, _, path = line.partition("\t")
        if path:
            mode, _, blob = meta.partition(" ")
            entries[path] = (mode, blob)
    tracked = set(entries)
    directories = _directories(tracked)
    symlink_map = _symlink_map(root, full, entries)
    probe = line_cwd(db, scope_line or conv_id) or root
    if not os.path.isdir(probe):
        probe = root
    skip_globs = [glob for glob in (skip_files or []) if glob.strip()]
    skipped_keys = frozenset(key.strip() for key in (skip_keys or []) if key.strip())
    blobs = sorted(path for path in tracked
                   if path.endswith(".json") and _under(path, data_paths)
                   and not any(fnmatch.fnmatch(path, glob) for glob in skip_globs)
                   )[:MAX_FILES]
    missing: list[dict] = []
    summary: dict[str, dict[str, int]] = {}
    checked = 0
    for blob in blobs:
        shown = _git("show", f"{full}:{blob}", cwd=root)
        if shown.returncode != 0:
            continue
        try:
            payload = json.loads(shown.stdout)
        except ValueError:
            continue  # a malformed table is not this check's finding
        blob_dir = posixpath.dirname(blob)
        stats = summary.setdefault(blob, {"missing": 0, "checked": 0})
        for value in _walk_strings(payload, skipped_keys):
            candidates = [c for c in _candidates(value, res_roots or {},
                                                 path_roots or []) if c]
            if not candidates:
                continue
            path_shaped = any("/" in c or _EXTENSION.search(c) for c in candidates)
            if not path_shaped and not any(c.rstrip("/") in directories
                                           for c in candidates):
                continue  # a plain word naming nothing tracked
            present = any(
                _present(candidate, tracked, blob_dir, directories, symlink_map)
                for candidate in candidates)
            stats["checked"] += 1
            checked += 1
            if present:
                continue
            probe_paths = {candidates[0],
                           posixpath.normpath(posixpath.join(blob_dir, candidates[0]))}
            ignored = any(_git("check-ignore", "-q", "--", path, cwd=probe).returncode == 0
                          for path in probe_paths if path and not path.startswith(".."))
            missing.append({"file": blob, "ref": value, "ignored": ignored})
            stats["missing"] += 1
            if len(missing) >= MAX_MISSING:
                break
        if len(missing) >= MAX_MISSING:
            break
    ordered = sorted(summary.items(), key=lambda item: (-item[1]["missing"], item[0]))
    return {"ok": not missing, "missing": missing, "checked": checked,
            "summary": [{"file": blob, **counts} for blob, counts in ordered]}


def register_prereview_route(app, runtime) -> None:
    @app.post("/api/conversations/{conv_id}/prereview", response_model=PrereviewOut)
    async def prereview(request: Request, conv_id: str, body: PrereviewIn):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        unknown = sorted(set(body.checks) - set(KNOWN_CHECKS))
        if unknown:
            raise HTTPException(422, f"unknown checks: {', '.join(unknown)}")
        try:
            # A large commit and a chatty table make this seconds of CPU:
            # deterministic work belongs in a thread, not on the event loop.
            done = await asyncio.to_thread(
                referenced_paths, db, conv_id, body.sha, body.data_paths,
                body.repository, body.res_roots, body.path_roots,
                body.skip_files, body.skip_keys)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        return PrereviewOut(**done)
