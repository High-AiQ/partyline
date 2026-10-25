"""Reported SHAs must exist on the task's branches before they are believed.

A worker's blocked findings once claimed commit ``568b2db`` that never
existed — the files were only staged — and the report reached the captain
unchallenged. Every hex token a worker quotes in ``request_review``,
``blocked``, ``review_verdict`` or a stall escalation is checked with
``git cat-file -e`` in the task's worktrees, and a token that is no commit
is flagged, visibly, in the report the captain reads. The report is never
rejected: an ambiguous token (a colour code, a hash) may still name real
work, and the captain decides.
"""

from __future__ import annotations

import re

from .hierarchy import lead_attachment
from .line_worktree import rev
from .mention_relay import live_manager, post_private
from .task_workspaces import workspaces

# 7-40 hex characters, not letter-prefixed: git hashes are bare hex, and a
# style token like B007 must not be read as a claimed commit.
TOKEN = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")


def suspected(text: str) -> list[str]:
    """Bare hex tokens long enough to be a commit hash, in order, unique."""
    found = []
    for token in TOKEN.findall(text or ""):
        if token not in found:
            found.append(token)
    return found


def places(db, conv_id: str) -> list[str]:
    """The task's worktrees and the clones they are cut from, both objects."""
    spaces = workspaces(db, conv_id)
    return list(dict.fromkeys([item["path"] for item in spaces]
                              + [item["repository"] for item in spaces]))


def _commit(name: str, found: list[str]) -> bool:
    return any(rev(where, "cat-file", "-e", f"{name}^{{commit}}") for where in found)


def quoted(db, conv_id: str, *texts: str) -> list[str]:
    """The commits actually missing from the task's worktrees and their clones."""
    names = suspected(" ".join(text for text in texts if text))
    found = places(db, conv_id)
    return [name for name in names if found and not _commit(name, found)]


def flagged(db, row) -> list[str]:
    """Missing SHAs to print with a terminal report: the hand-off's, then the round's."""
    texts = [row.get("what"), row.get("findings"), row.get("previous_findings")]
    return quoted(db, row["conv_id"], *(text for text in texts if text))


def report_text(db, row) -> str:
    """The captain's report body, with unverified SHAs named after the findings."""
    status = "stalled" if row["stall_stage"] == 3 else row["status"]
    repos = row["repositories"]
    where = (' ' + '; '.join(f"{item['repository']} {item['sha']}" for item in repos)
             if len(repos) > 1 else '')
    text = (f"Task {row['conv_id']}: {status}; round {row['round']}; "
            f"SHA {row['sha']}{where}; review {row['review_worktree']}; "
            f"{row['what']} — {row['location']}\n{row['findings']}")
    missing = flagged(db, row)
    if missing:
        text += ("\n⚠ unverified SHAs (not a commit in this task's worktrees or their clones): "
                 + ", ".join(missing))
    return text[:2000]


async def flag(runtime, row, text) -> None:
    """One message to the root captain naming SHAs that do not exist.

    Raised after the structured attempt has been recorded, so the call itself
    succeeds: the flag is a finding for the captain, never a rejection.
    """
    missing = quoted(runtime.db, row["conv_id"], text)
    if not missing:
        return
    captain = lead_attachment(runtime.db, row["root_id"])
    if captain and live_manager(runtime, row["root_id"]) is None:
        return  # no process could be woken; the report still carries the flag
    await post_private(
        runtime, row["root_id"], "system", "system",
        f"⚠ task {row['conv_id']} reported SHAs that are not commits in its worktrees: "
        + ", ".join(missing),
        audience=captain["id"] if captain else None,
        source=(row["implementer_id"], row["conv_id"]))
