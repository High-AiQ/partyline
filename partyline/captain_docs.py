"""Curated partyline docs for captains, sliced from the repository's own docs.

The text lives once, in ``docs/*.md`` and ``README.md``; this module only
maps (category, topic) to a heading and slices that section at request time,
so the captain-facing copy can never drift from the docs. Greg asked for
shelves, not a dump: the index lists the categories, a captain requests a
category, then a topic. People and current captains read; workers and
ordinary participants are refused — the docs are for the process that has to
decide, not for every implementer's context budget.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request

from .auth_guard import request_principal

BODY_LIMIT = 8000
DOCS_ROOT = Path(__file__).resolve().parent.parent


def _t(category: str, slug: str, title: str, summary: str, doc: str, heading: str) -> dict:
    return {"category": category, "slug": slug, "title": title, "summary": summary,
            "doc": doc, "heading": heading}


TOPICS = [
    # captaining — running lines and delegating
    _t("captaining", "depth", "Depth, worktrees, and where work goes",
       "How lines nest, the depth cap, and where a child's checkout lands.",
       "docs/hierarchy.md", "Depth, worktrees, and where work goes"),
    _t("captaining", "checkout", "The checkout a line works in",
       "One branch per line; the parent accepts the branch, nothing else counts.",
       "docs/hierarchy.md", "The checkout a line works in"),
    _t("captaining", "hand-off", "The hand-off contract",
       "Brief with acceptance, wait for the return, verify the whole.",
       "docs/hierarchy.md", "The hand-off contract"),
    _t("captaining", "accepted-sha", "The accepted SHA",
       "How accept lands work, the fenced mirror, allow_descendant and the tip read.",
       "docs/hierarchy.md", "The accepted SHA"),
    _t("captaining", "goal", "The goal",
       "The one-line purpose a manager sees through and every wake carries.",
       "docs/hierarchy.md", "The goal"),
    _t("captaining", "reporting-upward", "Reporting upward",
       "Reports ride to the manager; a report is a receipt, not acceptance.",
       "docs/hierarchy.md", "Reporting upward"),
    _t("captaining", "recovery", "Recovery",
       "What a reattached process hears, and what it must re-establish.",
       "docs/hierarchy.md", "Recovery"),
    _t("captaining", "one-process", "One process on a line",
       "Why a line carries exactly one live process per handle.",
       "docs/hierarchy.md", "One process on a line"),
    _t("captaining", "mentions", "Mentions across lines",
       "One tree, one mention namespace; who may cross a line and how.",
       "docs/hierarchy.md", "Mentions across lines"),
    _t("captaining", "return-path", "The return path",
       "How the server reaches a process whose turn it is not.",
       "docs/hierarchy.md", "The return path"),
    _t("captaining", "heartbeat", "The root manager's heartbeat",
       "The root captain's periodic sweep of the whole tree.",
       "docs/hierarchy.md", "The root manager's heartbeat"),
    # attachments — attaching and adapting processes
    _t("attachments", "adapters-manifest", "Adapter manifest",
       "What an adapter declares: command, capabilities, update handling.",
       "docs/adapters.md", "Manifest"),
    _t("attachments", "adapters-entrypoint", "Adapter entrypoint",
       "The process contract: arguments, environment, and the pty.",
       "docs/adapters.md", "Entrypoint"),
    _t("attachments", "testing-an-adapter", "Testing an adapter",
       "How to exercise an adapter without a live line.",
       "docs/adapters.md", "Testing an adapter"),
    _t("attachments", "machine-api-scope", "Machine API scope",
       "What a machine token may do, per capability and role.",
       "docs/security.md", "Machine API scope"),
    # review-and-accept — verifying and landing work
    _t("review-and-accept", "review-worktrees", "Review worktrees",
       "A managed checkout of the exact SHA, in any subtree repository.",
       "docs/hierarchy.md", "Review worktrees"),
    _t("review-and-accept", "prereview-and-tree-sync", "Pre-review checks and the tree sync",
       "Model-free referenced-path checks and the post-accept worktree report.",
       "docs/hierarchy.md", "Pre-review checks and the tree sync"),
    _t("review-and-accept", "report-acknowledgment", "Report acknowledgment contract",
       "When a report counts as seen, and what ack relieves.",
       "docs/hierarchy.md", "Report acknowledgment contract"),
    # fence-and-write-set — the write fence and scope grants
    _t("fence-and-write-set", "the-wrap", "The wrap",
       "What the write fence wraps and what the process still sees.",
       "docs/write-fence.md", "The wrap"),
    _t("fence-and-write-set", "protected-set", "The protected set and carve-outs",
       "The default write set, and the recorded grants that widen it.",
       "docs/write-fence.md", "The protected set and carve-outs"),
    _t("fence-and-write-set", "git-for-a-child-line", "Git for a child line",
       "Refs, mirrors, and why the branch ref moves only on accept.",
       "docs/write-fence.md", "Git for a child line"),
    _t("fence-and-write-set", "scope-expansion", "Scope expansion",
       "How a write-set request is filed, approved, and applied.",
       "docs/write-fence.md", "Scope expansion"),
    _t("fence-and-write-set", "memory-failures", "Memory failures and recovery",
       "What a cgroup kill looks like from inside the fence.",
       "docs/write-fence.md", "Memory failures and recovery"),
    # memory-and-resources — memory caps and host budget
    _t("memory-and-resources", "defaults", "Defaults and settings",
       "The memory settings, their defaults, and where they live.",
       "docs/resource-budget.md", "Defaults and settings"),
    _t("memory-and-resources", "enforcement", "Enforcement and limits",
       "Caps, reservations, and the host ceiling.",
       "docs/resource-budget.md", "Enforcement and limits"),
    _t("memory-and-resources", "larger-cap", "Requesting a larger cap",
       "The request path, the ceilings, and who may approve.",
       "docs/resource-budget.md", "Requesting a larger cap"),
    # restart — restarts and recovery
    _t("restart", "the-flow", "The restart flow",
       "Plan, approve, checkpoint, restart, resume.",
       "docs/restart.md", "The flow"),
    _t("restart", "who-may-do-what", "Who may do what",
       "Roles and authority across a restart.",
       "docs/restart.md", "Who may do what"),
    _t("restart", "mid-turn", "What happens to a process mid-turn",
       "Checkpointing work in flight instead of dropping it.",
       "docs/restart.md", "What happens to a process mid-turn"),
    _t("restart", "verifying", "Verifying afterward",
       "The checks that say the restart actually worked.",
       "docs/restart.md", "Verifying afterward"),
    # best-practices — working on partyline itself
    _t("best-practices", "layout", "Repository layout",
       "Where partyline's code, docs, and tests live.",
       "docs/agent-rules.md", "Layout"),
    _t("best-practices", "gates", "Gates",
       "Every gate a commit must pass, and how to run each.",
       "docs/agent-rules.md", "Gates — all must pass before every commit"),
    _t("best-practices", "inside-partyline", "Working on partyline from inside partyline",
       "Restarting the copy you are running inside, and other traps.",
       "docs/agent-rules.md", "Working on partyline from inside partyline"),
    # lessons — hard-won incident lessons
    _t("lessons", "self-learning", "The self-learning protocol",
       "How incidents become lessons and lessons become gates.",
       "docs/lessons.md", "The self-learning protocol"),
    _t("lessons", "startup-lock", "Startup dialogs and the ownership lock",
       "A startup dialog must not hold the instance's ownership lock.",
       "docs/lessons.md", "A startup dialog must not hold the instance's ownership lock"),
    _t("lessons", "resume-backlog", "Resume backlog is not a room-history replay",
       "What a resumed process should and should not be sent.",
       "docs/lessons.md", "Resume backlog is not a room-history replay"),
]

CATEGORIES = [
    ("captaining", "Captaining", "Running lines: delegation, hand-offs, mentions, recovery."),
    ("attachments", "Attachments", "Attaching processes and writing or testing adapters."),
    ("review-and-accept", "Review and accept",
     "Verifying returned work and landing it on the line's branch."),
    ("fence-and-write-set", "Fence and write-set",
     "The write fence, protected paths, and widening scope."),
    ("memory-and-resources", "Memory and resources",
     "Process memory caps and the host budget."),
    ("restart", "Restart", "Planned restarts, mid-turn checkpointing, verification."),
    ("best-practices", "Best practices", "Working on partyline itself: layout and gates."),
    ("lessons", "Lessons", "Incident lessons the code now encodes."),
]


def may_read_docs(principal) -> bool:
    """People read the docs; so do processes currently captaining a line."""
    if principal.kind == "user":
        return True
    return principal.kind == "machine" and principal.is_lead


def _doc_text(doc: str) -> str:
    return (DOCS_ROOT / doc).read_text(encoding="utf-8", errors="replace")


def slice_section(text: str, heading: str, doc: str, limit: int = BODY_LIMIT) -> str | None:
    """The body under one heading, fenced-code aware, capped with a pointer.

    Returns None when the heading is gone — the map has drifted from the
    docs, and the test that walks the whole map will say so.
    """
    lines = text.splitlines()
    start = level = None
    fenced = False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            fenced = not fenced
        elif not fenced and line.strip().startswith("#"):
            if line.strip().lstrip("#").strip() == heading:
                start, level = index, len(line.strip()) - len(line.strip().lstrip("#"))
                break
    if start is None:
        return None
    end = len(lines)
    fenced = False
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith("```"):
            fenced = not fenced
        elif not fenced and lines[index].strip().startswith("#"):
            if len(lines[index].strip()) - len(lines[index].strip().lstrip("#")) <= level:
                end = index
                break
    body = "\n".join(lines[start + 1:end]).strip()
    if len(body) > limit:
        body = body[:limit].rstrip() + f"\n\n… (truncated — read `{doc}` under “{heading}”)"
    return body


def category_index() -> list[dict]:
    slugs_by_category: dict[str, list[str]] = {}
    for topic in TOPICS:
        slugs_by_category.setdefault(topic["category"], []).append(topic["slug"])
    return [{"slug": slug, "title": title, "summary": summary,
             "topics": slugs_by_category.get(slug, [])}
            for slug, title, summary in CATEGORIES]


def category_topics(category: str) -> list[dict] | None:
    if category not in {slug for slug, _title, _summary in CATEGORIES}:
        return None
    return [{"slug": topic["slug"], "title": topic["title"], "summary": topic["summary"]}
            for topic in TOPICS if topic["category"] == category]


def topic_body(category: str, slug: str) -> dict | None:
    for topic in TOPICS:
        if topic["category"] == category and topic["slug"] == slug:
            body = slice_section(_doc_text(topic["doc"]), topic["heading"], topic["doc"])
            if body is None:
                raise HTTPException(
                    410, f"the section behind {topic['doc']}#{topic['heading']} is gone; "
                         "the docs moved — tell the partyline maintainers")
            return {"title": topic["title"], "source": f"{topic['doc']}#{topic['heading']}",
                    "body": body}
    return None


REMINDER_SETTING = "docs_reminder_every_messages"
REMINDER_DEFAULT = 40


def reminder_line(db, conv_id: str, last_seen_id: int | None) -> tuple[str, int]:
    """The docs pointer once N line messages have passed since the last one.

    Returns ``(line, top message id)``. A fresh binding (``last_seen_id``
    None) measures from now without riding, so a captain sees the pointer
    roughly every N messages, never on every wake. A minimal db — the rider
    tests' fake — has nothing to count and never rides.
    """
    slugs = " · ".join(slug for slug, _title, _summary in CATEGORIES)
    line = f"(partyline docs: GET /api/docs — {slugs})"
    try:
        row = db._exec(
            "SELECT COALESCE(MAX(id), 0) AS top, COUNT(*) AS fresh FROM messages "
            "WHERE conv_id=? AND id>?", (conv_id, last_seen_id or 0)).fetchone()
        if last_seen_id is None:
            return "", row["top"]
        every = int(db.get_setting(REMINDER_SETTING) or REMINDER_DEFAULT)
    except (AttributeError, ValueError):
        return "", 0
    if row["fresh"] < max(1, every):
        return "", last_seen_id  # the anchor stays: N counts since the last ride
    return line, row["top"]


def register_docs_route(app, runtime) -> None:
    def deny_workers(request: Request) -> None:
        principal = request_principal(request)
        if not may_read_docs(principal):
            raise HTTPException(
                403, "partyline docs are for people and current captains")

    @app.get("/api/docs")
    async def docs_index(request: Request):
        deny_workers(request)
        return category_index()

    @app.get("/api/docs/{category}")
    async def docs_category(request: Request, category: str):
        deny_workers(request)
        topics = category_topics(category)
        if topics is None:
            raise HTTPException(404, f"no docs category {category}")
        return topics

    @app.get("/api/docs/{category}/{topic}")
    async def docs_topic(request: Request, category: str, topic: str):
        deny_workers(request)
        body = topic_body(category, topic)
        if body is None:
            raise HTTPException(404, f"no docs topic {category}/{topic}")
        return body
