"""The post-accept tree sync: does any worktree holding the branch hold it?

Reporting only — split out of `prereview.py` so the scan keeps its line
budget; both checks are finding 2.6.
"""

from __future__ import annotations

from .line_worktree import _git


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


