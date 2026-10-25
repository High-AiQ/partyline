"""Principal-bound retirement plans, with bounded evidence and explicit limits."""

import hashlib
import hmac
import json

from fastapi import HTTPException

from .auth_tokens import signing_secret
from .attachment_tmp import guarded_path, line_tmp_ids
from .hierarchy import descendants, lead_attachment, parent_id_of
from .machine_scope import deny_unless, is_human
from .retirement_git import DISPLAY, MAX_BYTES, MAX_FILES, MAX_IGNORED_BYTES, MAX_IGNORED_FILES, inspect_git
from .retirement_auxiliary import inspect_auxiliary

MAX_LINES = 50


def force_authorized(db, principal, target):
    deny_unless(db, principal, target, "archive")
    if is_human(principal):
        return
    home = db.get_conversation(principal.conv_id)
    lead = lead_attachment(db, principal.conv_id)
    if (not home or home.get("archived_at") or parent_id_of(home) or not lead
            or lead["id"] != principal.attachment_id
            or lead["status"] not in ("starting", "running")
            or target == principal.conv_id or target not in descendants(db, principal.conv_id)):
        raise HTTPException(403, "forced retirement requires the tree's root captain")


def identity(principal):
    return {"kind": principal.kind, "name": principal.name, "user_id": principal.user_id,
            "attachment_id": principal.attachment_id, "conv_id": principal.conv_id}


def plan(db, principal, target, include_children, presence=None, recovery_prefix=None):
    deny_unless(db, principal, target, "archive")
    ids = [target]
    if include_children:
        ids += descendants(db, target, include_archived=False)
    if len(ids) > MAX_LINES:
        raise HTTPException(409, f"retirement exceeds {MAX_LINES} line limit; retire smaller subtrees")
    lines, totals = [], [0, 0, 0, 0]
    for line_id in reversed(ids):
        conv = db.get_conversation(line_id)
        if conv is None or conv.get("archived_at"):
            raise HTTPException(409, "retirement target is missing or already archived")
        attachments = [{key: att.get(key) for key in
                        ("id", "name", "status", "runtime_owner", "turn_open")}
                       for att in db.list_attachments(line_id)]
        for att in attachments:
            att["working"] = bool(presence and presence.is_working(att["id"]))
        children = descendants(db, line_id, include_archived=False)
        if len(children) > MAX_LINES or len(attachments) > DISPLAY:
            raise HTTPException(409, "retirement exceeds child/process preview limit")
        auxiliary, clean_auxiliary, history = inspect_auxiliary(db, line_id, recovery_prefix)
        state = inspect_git(db, conv)
        if state:
            amounts = (len(state["files"]), state["bytes"],
                       len(state["ignored_files"]), state["ignored_bytes"])
            totals = [total + amount for total, amount in zip(totals, amounts, strict=True)]
            if any(total > limit for total, limit in zip(
                    totals, (MAX_FILES, MAX_BYTES, MAX_IGNORED_FILES, MAX_IGNORED_BYTES), strict=True)):
                raise HTTPException(
                    409, "retirement subtree exceeds file or byte limit; use smaller subtrees")
        lines.append({"id": line_id, "parent_id": parent_id_of(conv), "name": conv["name"],
                      "goal": conv.get("goal", ""), "children": children,
                      "attachments": attachments, "git": state,
                      "temporary_directories": [str(guarded_path(att_id))
                                                for att_id in line_tmp_ids(db, [line_id])],
                      "auxiliary_worktrees_preserved": auxiliary,
                      "auxiliary_worktrees_pruned": clean_auxiliary,
                      "auxiliary_worktrees": history,
                      "uploads_preserved": db._exec(
                          "SELECT count(*) FROM images WHERE conv_id=?", (line_id,)).fetchone()[0]})
    return {"principal": identity(principal), "target": target,
            "include_children": include_children, "lines": lines}


def required_flags(evidence):
    """Every flag a forced retirement of this plan needs, named in the preview.

    A captain reads them once here instead of learning one per refused call.
    """
    flags = {"force_discard"}
    for line in evidence["lines"]:
        if line["goal"]:
            flags.add("clear_goal")
        if line["children"]:
            flags.add("include_children")
        if any(att["status"] in ("starting", "running") for att in line["attachments"]):
            flags.add("stop_processes")
    return sorted(flags)


def token(db, evidence):
    raw = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(signing_secret(db).encode(), raw, hashlib.sha256).hexdigest()


def preview(db, principal, target, include_children, presence=None):
    evidence = plan(db, principal, target, include_children, presence)
    allowed = True
    try:
        force_authorized(db, principal, target)
    except HTTPException:
        allowed = False
    lines = []
    for line in evidence["lines"]:
        row = {**line}
        state = row["git"]
        if state:
            row["git"] = {key: value for key, value in state.items()
                          if key not in ("files", "index", "index_path", "ignored_files")}
            for key in ("tracked", "untracked", "ignored"):
                row["git"][key] = {"count": len(state[key]), "paths": state[key][:DISPLAY],
                                    "truncated": len(state[key]) > DISPLAY}
        lines.append(row)
    return {"target": target, "include_children": include_children,
            "force_allowed": allowed, "preview_token": token(db, evidence), "lines": lines,
            "required_flags": required_flags(evidence),
            "implications": "force_discard captures both the index and tracked/untracked working files "
            "in separate recovery refs and anchors each clean auxiliary HEAD before removal; "
            "ignored files are lost. Uploads/messages and dirty auxiliary worktrees are retained; "
            "clean auxiliary worktrees and line temporary directories are removed. "
            "Preserve deliverables and verify handoff before retiring. Large files use metadata "
            "fingerprints; external concurrent filesystem writes are not locked."}
