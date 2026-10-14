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
from .docs_catalog import (
    CATEGORIES,
    REMINDER_DEFAULT,
    REMINDER_SETTING,
    TOPICS,
)

BODY_LIMIT = 8000
DOCS_ROOT = Path(__file__).resolve().parent.parent


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
            try:
                text = _doc_text(topic["doc"])
            except OSError:
                raise HTTPException(
                    410, f"the section behind {topic['doc']}#{topic['heading']} is gone; "
                         "the docs moved — tell the partyline maintainers") from None
            body = slice_section(text, topic["heading"], topic["doc"])
            if body is None:
                raise HTTPException(
                    410, f"the section behind {topic['doc']}#{topic['heading']} is gone; "
                         "the docs moved — tell the partyline maintainers")
            return {"title": topic["title"], "source": f"{topic['doc']}#{topic['heading']}",
                    "body": body}
    return None


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
            "WHERE conv_id=? AND id>? AND bridge_id IS NULL", (conv_id, last_seen_id or 0)).fetchone()
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
