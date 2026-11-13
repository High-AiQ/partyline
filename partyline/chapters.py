"""New chapter: a fresh line that carries a long-lived line's standing state forward.

The old line keeps everything it had (messages, processes, task lines); the new line
copies its name base, topic, goal, line notes, captain style, parent and folder, and the two
are linked by ``chapter_of``. No process moves and nothing is deleted.
"""

from __future__ import annotations

import re
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .conversation_contracts import ConversationResponse
from .hierarchy import lead_attachment, parent_id_of
from .line_notes import read_notes, write_notes
from .line_worktree import line_cwd
from .preset_roles import attachment_preset

NAME_MAX = 120
_SUFFIX = re.compile(r"\s*·\s*ch\s+\d+\s*$")


class ChapterIn(BaseModel):
    name: str = Field(default="", max_length=NAME_MAX)


class CaptainPreset(BaseModel):
    """The preset the old line's captain runs, so the dialog can staff the same one."""

    name: str
    title: str = ""
    adapter: str
    command: str


class ChapterPreview(BaseModel):
    chapter: int
    name: str
    live_processes: int
    captain_preset: CaptainPreset | None = None
    continued_in: str | None = None


class ChapterResponse(BaseModel):
    conversation: ConversationResponse
    previous: ConversationResponse
    captain_preset: CaptainPreset | None = None


def next_name(conv: dict) -> str:
    """``<name> · ch N`` for the line that continues ``conv``, never stacking suffixes."""
    suffix = f" · ch {conv['chapter'] + 1}"
    base = _SUFFIX.sub("", conv["name"]).strip() or "untitled"
    return base[: NAME_MAX - len(suffix)] + suffix


def successor_of(db, conv_id: str) -> dict | None:
    row = db._exec("SELECT id,name FROM conversations WHERE chapter_of=? ORDER BY created_at LIMIT 1",
                   (conv_id,)).fetchone()
    return dict(row) if row else None


def captain_preset(db, conv_id: str) -> CaptainPreset | None:
    """The preset the line's captain was staffed from, when exactly one is identifiable."""
    lead = lead_attachment(db, conv_id)
    preset = attachment_preset(db, lead) if lead else None
    if preset is None:
        return None
    return CaptainPreset(name=preset["name"], title=preset.get("title") or "",
                         adapter=preset["adapter"], command=preset["command"])


def check_chapterable(db, conv: dict) -> None:
    from .orchestrator_store import task
    if task(db, conv["id"]):
        raise HTTPException(409, "task lines have no chapters; the task ends with its own verdict")
    if conv.get("archived_at"):
        raise HTTPException(409, "restore the line before starting a new chapter")
    if (later := successor_of(db, conv["id"])) is not None:
        raise HTTPException(409, f"this line already continues in «{later['name']}» ({later['id']})")


def preview(db, conv: dict) -> ChapterPreview:
    later = successor_of(db, conv["id"])
    return ChapterPreview(chapter=conv["chapter"] + 1, name=next_name(conv),
                          live_processes=conv["live_count"], captain_preset=captain_preset(db, conv["id"]),
                          continued_in=later["id"] if later else None)


def create_chapter(db, conv: dict, name: str) -> dict:
    """Insert the continuing line and copy the standing state; no await between check and insert."""
    check_chapterable(db, conv)
    new_id = str(uuid.uuid4())
    db._exec(
        "INSERT INTO conversations(id,name,created_at,parent_id,topic,goal,cwd,captain_mode,"
        "default_review_policy,chapter_of,chapter) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (new_id, name.strip() or next_name(conv), time.time(), parent_id_of(conv), conv["topic"],
         conv["goal"], line_cwd(db, conv["id"]), conv["captain_mode"], conv["default_review_policy"],
         conv["id"], conv["chapter"] + 1))
    scopes = ("line",) if parent_id_of(conv) else ("line", "tree")  # a root's tree notes start a new tree
    for scope in scopes:
        if notes := read_notes(db, conv["id"], scope)["notes"]:
            write_notes(db, new_id, scope, notes)
    return db.get_conversation(new_id)


def link(conv: dict) -> str:
    """A markdown link the web client opens in place (``#/c/<id>``)."""
    label = re.sub(r"([\\\[\]])", r"\\\1", conv["name"])
    return f"[{label}](#/c/{conv['id']})"
