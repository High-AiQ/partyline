"""Clean ordinary retirement debris while retaining explicitly dirty auxiliary work."""

import os

from fastapi import HTTPException

from .nested_repositories import nested_repositories
from .retirement_git import DISPLAY, git
from .review_worktrees import remove_review_path
from .scratch_worktrees import remove_scratch_path

TABLES = ("review_worktrees", "scratch_worktrees")


def inspect_auxiliary(db, conv_id, recovery_prefix=None):
    preserved, pruned, history = {}, {}, {}
    for table in TABLES:
        rows = db._exec(f"SELECT path FROM {table} WHERE conv_id=? ORDER BY path", (conv_id,)).fetchall()
        if len(rows) > DISPLAY:
            raise HTTPException(409, "retirement exceeds auxiliary worktree limit")
        preserved[table], pruned[table], history[table] = [], [], []
        for row in rows:
            path = row["path"]
            dirty = os.path.isdir(path) and (
                bool(git(path, "status", "--porcelain").strip()) or bool(nested_repositories(path)))
            (preserved if dirty else pruned)[table].append(path)
            head = git(path, "rev-parse", "HEAD").strip() if os.path.isdir(path) else None
            refs = (git(path, "for-each-ref", "--format=%(refname)", "--contains", head).splitlines()
                    if head else [])
            refs = [ref for ref in refs if not recovery_prefix or not ref.startswith(recovery_prefix)]
            history[table].append({"path": path, "head": head, "unique": bool(head and not refs)})
    return preserved, pruned, history


def auxiliary_heads(history):
    """Compare content identity after our own recovery/ref removals change reachability."""
    return {table: [(entry["path"], entry["head"]) for entry in entries]
            for table, entries in history.items()}


def recover_auxiliary(line, audit_path):
    """Anchor every clean auxiliary HEAD before any checkout can be removed."""
    refs = {}
    for table, entries in line["auxiliary_worktrees"].items():
        for n, entry in enumerate(entries):
            head, path = entry["head"], entry["path"]
            if not head or path not in line["auxiliary_worktrees_pruned"][table]:
                continue
            if git(path, "rev-parse", "HEAD").strip() != head:
                raise HTTPException(409, "auxiliary HEAD changed; refresh retirement preview")
            ref = f"refs/partyline/discarded/{audit_path}/aux/{table}/{n}"
            git(path, "update-ref", ref, head, "0" * len(head))
            refs[ref] = head
    return refs


def clear_preserved(db, conv_id):
    """Purge and repeated retirement release every exemption owned by this line."""
    for table in TABLES:
        db._exec(f"DELETE FROM retirement_preserved_paths WHERE path IN "
                 f"(SELECT path FROM {table} WHERE conv_id=?)", (conv_id,))


def cleanup_auxiliary(db, line, audit_id):
    preserved, pruned, history = inspect_auxiliary(db, line["id"], f"refs/partyline/discarded/{audit_id}/")
    if (preserved != line["auxiliary_worktrees_preserved"]
            or pruned != line["auxiliary_worktrees_pruned"]
            or auxiliary_heads(history) != auxiliary_heads(line["auxiliary_worktrees"])):
        raise HTTPException(409, "auxiliary worktree state changed; refresh retirement preview")
    clear_preserved(db, line["id"])
    for table, remove in zip(TABLES, (remove_review_path, remove_scratch_path), strict=True):
        for path in preserved[table]:
            db._exec("INSERT OR REPLACE INTO retirement_preserved_paths VALUES(?,?)", (path, audit_id))
        for path in pruned[table]:
            # Recheck immediately before removing a clean checkout. A newly
            # dirty checkout is retained even if it changed since preflight.
            if os.path.isdir(path) and git(path, "status", "--porcelain").strip():
                raise HTTPException(409, "auxiliary worktree became dirty; retained")
            expected = next(row["head"] for row in history[table] if row["path"] == path)
            if os.path.isdir(path) and git(path, "rev-parse", "HEAD").strip() != expected:
                raise HTTPException(409, "auxiliary HEAD changed; retained")
            if not remove(path):
                raise HTTPException(409, "auxiliary worktree cleanup failed; retained")
            db._exec(f"DELETE FROM {table} WHERE conv_id=? AND path=?", (line["id"], path))
    return [path for paths in preserved.values() for path in paths]
