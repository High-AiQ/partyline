"""The protect-list: what a fenced process must never write, computed fresh
from the database at spawn time.

Every managed repository — every non-archived line's repository root,
whether that line sits at the root of its own checkout or in a child
worktree — is protected by default; everything else on the host is
writable. A repository not yet known to partyline (no line has a ``cwd``
inside it) is therefore writable — a documented consequence of computing
the set this way, not a hidden gap.

The one exemption: a line whose own ``cwd`` *is* a repository's root (the
root captain, attached directly in the person's checkout) keeps that
checkout writable, exactly as before the fence was inverted — the person
put the process there. A child line's ``cwd`` is a worktree, not the
root, so it gets no such exemption and the shared repository — including
every sibling worktree — stays protected; the fence then carves back only
that line's own worktree tree.
"""

from __future__ import annotations

import os

from . import db_sidecars
from .line_worktree import repo_root


def protected_repo_roots(db) -> list[str]:
    """The canonical root of every non-archived line's repository.

    Lines that share a repository — a root checkout and its child
    worktrees — collapse to one entry; a line working outside any git
    repository contributes nothing.
    """
    roots: set[str] = set()
    for conv in db.list_conversations(archived=False):
        cwds = [conv.get("cwd")]
        cwds.extend(attachment.get("cwd") for attachment in db.list_attachments(conv["id"]))
        for cwd in cwds:
            if not cwd:
                continue
            root = repo_root(cwd)
            if root:
                roots.add(os.path.realpath(root))
    return sorted(roots)


def database_paths(db) -> list[str]:
    """The database file and the sidecars a fenced process must never write."""
    return db_sidecars.ensure(db)


def own_repo_root(cwd: str) -> str | None:
    """This attachment's own repository root, when its ``cwd`` *is* that
    root — the exemption described above. ``None`` for a child line's
    worktree, or a cwd outside any repository, so the caller's protected
    set is left untouched.
    """
    root = repo_root(cwd)
    if root and os.path.realpath(root) == os.path.realpath(cwd or ""):
        return os.path.realpath(root)
    return None
