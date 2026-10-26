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

from . import reports
from .git_fence import mirror_store
from .hierarchy import lead_attachment
from .line_worktree import rev
from .mention_relay import live_manager, post_private
from .task_workspaces import workspaces

# 7-40 hex characters, not letter-prefixed: git hashes are bare hex, and a
# style token like B007 must not be read as a claimed commit.
TOKEN = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
# Words that name another kind of hash or version when they come just before a
# token: a model revision, a weights checksum, a file digest.
OTHER_KIND = re.compile(
    r"\b(?:revision|rev|HF|hugging face|weights|model|checkpoint|sha256|md5|"
    r"checksum|digest|hash of a file|blob|etag|tag)\b", re.IGNORECASE)
SENTENCE_END = re.compile(r"[.!?;\n]")
WINDOW = 30  # characters before a token that may name its kind


def _named_other(text: str, start: int) -> bool:
    """Whether the words just before the token, in its sentence, name another hash."""
    before = text[max(0, start - WINDOW):start]
    return OTHER_KIND.search(SENTENCE_END.split(before)[-1]) is not None


def _in_url_or_path(text: str, start: int, end: int) -> bool:
    """Whether the whitespace-delimited word around the token has a slash in it."""
    word = re.search(r"\S*$", text[:start]).group() + re.match(r"\S*", text[end:]).group()
    return "/" in word


def suspected(text: str) -> list[str]:
    """Bare hex tokens that may be a commit hash, in order, unique.

    A token is skipped when another kind of hash is named just before it, or
    when it sits inside a URL or path.
    """
    text = text or ""
    found = []
    for match in TOKEN.finditer(text):
        token = match.group()
        if token in found or _named_other(text, match.start()):
            continue
        if _in_url_or_path(text, match.start(), match.end()):
            continue
        found.append(token)
    return found


def places(db, conv_id: str) -> list[str]:
    """The task's worktrees and the clones they are cut from, both objects."""
    spaces = workspaces(db, conv_id)
    return list(dict.fromkeys([item["path"] for item in spaces]
                              + [item["repository"] for item in spaces]))


def stores(db, conv_id: str) -> list[str]:
    """The line's fence mirror of each task repository's Git directory, where one exists."""
    repos = dict.fromkeys(item["repository"] for item in workspaces(db, conv_id))
    return [mirror for repo in repos if (mirror := mirror_store(repo, conv_id))]


def _commit(name: str, found: list[str], mirrors: list[str]) -> bool:
    # `cat-file -t` prints the type on success; `-e` prints nothing, which rev() reads as failure.
    return (any(rev(where, "cat-file", "-t", name) == "commit" for where in found)
            or any(rev(mirror, f"--git-dir={mirror}", "cat-file", "-t", name) == "commit"
                   for mirror in mirrors))


def quoted(db, conv_id: str, *texts: str) -> list[str]:
    """The commits actually missing from the task's worktrees, clones and mirrors."""
    names = suspected(" ".join(text for text in texts if text))
    found = places(db, conv_id)
    mirrors = stores(db, conv_id)
    return [name for name in names if found and not _commit(name, found, mirrors)]


def flagged(db, row) -> list[str]:
    """Missing SHAs to print with a terminal report: the hand-off's, then the round's."""
    texts = [row.get("what"), row.get("findings"), row.get("previous_findings")]
    return quoted(db, row["conv_id"], *(text for text in texts if text))


ELLIPSIS = ' …'
TRUNCATED = ' …[truncated; full text via tasks]'


def clip(text: str, budget: int, mark: str = ELLIPSIS) -> str:
    """The longest prefix of *text* within *budget*, cut at a word boundary.

    A cut is never silent — the visible *mark* says so — and never lands
    inside a word: the whole word the cut opened is given up, which is what
    kept a report from ending like ``…before shippin``.
    """
    text = text or ''
    if len(text) <= budget:
        return text
    if budget <= len(mark):
        return mark[:max(0, budget)]
    cut = text[:budget - len(mark)]
    if re.search(r'\S$', cut) and re.match(r'\S', text[len(cut)]):
        cut = re.sub(r'\S*$', '', cut)
    return cut.rstrip() + mark


def report_text(db, row) -> str:
    """The captain's report body, within reports.MAX_BODY without a blind cut.

    The header and any unverified-SHA warning are kept whole, and the warning
    sits before the findings so it is never the part lost. ``what`` and then
    ``location`` are shortened first, visibly, to make room; findings that
    still cannot fit are cut at a word boundary behind an explicit marker.
    If the fixed parts alone overflow the cap — many repositories in the
    header, many unverified SHAs in the warning — the whole body is clipped
    behind that marker rather than stored over the cap and refused.
    """
    status = "stalled" if row["stall_stage"] == 3 else row["status"]
    repos = row["repositories"]
    where = (' ' + '; '.join(f"{item['repository']} {item['sha']}" for item in repos)
             if len(repos) > 1 else '')
    head = (f"Task {row['conv_id']}: {status}; round {row['round']}; "
            f"SHA {row['sha']}{where}; review {row['review_worktree']}; ")
    missing = flagged(db, row)
    warning = ('⚠ unverified SHAs (not a commit in this task\'s worktrees or their clones): '
               + ', '.join(missing)) if missing else ''
    what, location, findings = row['what'] or '', row['location'] or '', row['findings'] or ''
    # Everything except the three flexible fields: the head, the ' — ', and
    # the newlines that separate the parts, one of them only when warned.
    room = reports.MAX_BODY - len(head) - len(warning) - 4 - (1 if warning else 0)
    if len(what) + len(location) + len(findings) > room:
        # The findings matter most: give up `what` first, then `location`.
        what = clip(what, room - len(location) - len(findings))
        location = clip(location, room - len(what) - len(findings))
        findings = clip(findings, room - len(what) - len(location), TRUNCATED)
    parts = [f"{head}{what} — {location}"]
    if warning:
        parts.append(warning)
    parts.append(findings)
    result = '\n'.join(parts)
    if len(result) > reports.MAX_BODY:
        # The fixed parts alone overflowed and the flexible fields are spent:
        # the whole body still gives way, visibly, rather than being refused.
        return clip(result, reports.MAX_BODY, TRUNCATED)
    return result


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
