"""Route element actions to a window granted to the calling process's line, one at a time per window."""
from typing import Annotated, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth_guard import request_principal
from .capability_versions import WINDOW_PRESS_VERSION
from .machine_scope import deny_unless
from .screen_grants import resolve_window
from .screen_tree import OUT_BYTES
from .screen_tree_answer import size
from .screen_timing import timed, phase


ACTIONS = Literal["click", "invoke", "toggle", "set_value", "press", "select", "add_to_selection",
                  "remove_from_selection", "expand", "collapse", "scroll", "set_scroll_percent",
                  "scroll_into_view", "set_range_value", "window_close", "window_minimize", "window_maximize",
                  "window_restore", "window_move", "window_resize", "set_files", "reload", "dialog"]
# Parameters each action takes; "set_scroll_percent" needs at least one of its two.
PARAMS = {"dialog": ("accept", "prompt_text"), "set_files": ("files", "paths"), "press": ("key",),
          "select": ("value",), "set_value": ("value",),
          "scroll": ("direction", "amount"),
          "set_scroll_percent": ("horizontal_percent", "vertical_percent"),
          "set_range_value": ("number",), "window_move": ("x", "y"), "window_resize": ("width", "height")}
ALL_PARAMS = tuple(name for names in PARAMS.values() for name in names)


class Then(BaseModel):
    """What to read from a fresh snapshot taken right after the action; nothing set means what changed."""
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, min_length=1, max_length=200)
    value: str | None = Field(default=None, min_length=1, max_length=200)
    control_type: str | None = Field(default=None, min_length=1, max_length=40)
    root: str | None = Field(default=None, min_length=1, max_length=128)
    id: str | None = Field(default=None, min_length=1, max_length=128)
    text: bool = False
    context: int = Field(default=1, ge=0, le=5)
    depth: int = Field(default=1, ge=1, le=3)
    snapshot: bool = False  # a thumb picture of the window afterwards; alone, it replaces the tree read

    def reads(self):
        """True when a tree read is wanted: a query, or nothing else asked for."""
        return self.explicit() or not self.snapshot

    def explicit(self):
        return any(getattr(self, key) for key in ("query", "value", "control_type", "root", "id", "text"))


class ElementAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element_id: str | None = Field(default=None, min_length=1, max_length=128)
    mark: int | None = Field(default=None, ge=1, strict=True)
    action: ACTIONS
    force: bool = False
    window: str | None = Field(default=None, min_length=1, max_length=500)
    files: list[Annotated[str, Field(min_length=1, max_length=128)]] | None = Field(
        default=None, min_length=1, max_length=10)
    paths: list[Annotated[str, Field(min_length=1, max_length=32767)]] | None = Field(
        default=None, min_length=1, max_length=10)
    value: str | None = Field(default=None, max_length=500)
    accept: bool | None = Field(default=None, strict=True)
    prompt_text: str | None = Field(default=None, max_length=500)
    key: Literal["enter", "tab", "escape"] | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    amount: Literal["small", "large"] | None = None
    horizontal_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    vertical_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    number: float | None = Field(default=None, allow_inf_nan=False)
    x: int | None = Field(default=None, ge=-32768, le=32767)
    y: int | None = Field(default=None, ge=-32768, le=32767)
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    then: Then | None = None

    @model_validator(mode="after")
    def target(self):
        if (self.element_id is None) == (self.mark is None):
            raise ValueError("give exactly one of element_id or mark")
        if self.action == "click" and self.mark is None:
            raise ValueError("click requires a look mark")
        return self

    def parameters(self):
        """Reject missing or foreign parameters, so the helper only sees what the action takes."""
        if self.action in ("reload", "dialog") and self.element_id != "page":
            raise ValueError(f'{self.action} requires element_id="page"')
        if self.force and self.action not in ("invoke", "toggle", "select", "expand"):
            raise ValueError("force is supported only for invoke, toggle, select and expand")
        given = {name for name in ALL_PARAMS if getattr(self, name) is not None}
        wanted = set(PARAMS.get(self.action, ()))
        if self.action == "dialog":
            wanted = {"accept"} | (given & {"prompt_text"})
        if self.action == "set_files":
            if not 1 <= len(self.files or []) + len(self.paths or []) <= 10:
                raise ValueError("set_files requires 1–10 files and/or paths total")
            wanted = given & wanted
        if self.action == "select":
            wanted = given & wanted
        if self.action == "set_scroll_percent":
            if not given & wanted:
                raise ValueError("set_scroll_percent requires horizontal_percent and/or vertical_percent")
            wanted = given & wanted
        if missing := sorted(wanted - given):
            raise ValueError(f"{self.action} requires {', '.join(missing)}")
        if extra := sorted(given - wanted):
            raise ValueError(f"{self.action} does not take {', '.join(extra)}")
        excluded = {"window", "then", "mark"} | ({"force"} if not self.force else set())
        return self.model_dump(exclude_none=True, exclude=excluded)


STALE = ("unknown element id: not in the current snapshot (the page changed or it was never read); "
         "find it again, or pass then to see the page after a click")
REFRESH_FAILED = "could not refresh the window; read it again before acting"
TARGET_CHANGING = ("target keeps changing; read it again when it settles, or use "
                   "screen_window_snapshot + screen_window_click")


DIFF = ("diff", "removed", "lines", "more", "next_offset", "note", "partial", "changed", "update_helper",
        "error", "elements_unavailable", "page_dialog", "dialog_hint")


def diffed(reply):
    """A default `then` answers with what changed only: the counts, the changed elements, what went away."""
    shown = {key: reply[key] for key in DIFF if key in reply}
    if reply.get("change_event_since_snapshot"):
        shown["change_event_since_snapshot"] = True
    return shown


def action_token(elements, grant_id, ident):
    tree = elements.snapshots.get(grant_id)
    node = (tree.nodes.get(ident) or tree.nodes.get(tree.by_helper.get(ident))) if tree else None
    return node.cached.get("action_token") if node else None


async def after(hub, principal, grant, then, result):
    """A new snapshot taken at an event-counter boundary, answered like screen_elements and kept in budget."""
    options = {**then.model_dump(exclude_none=True, exclude={"snapshot"}),
               "refresh": True, "include_root": True}
    if not then.explicit():
        options["changes"] = True
    try:
        reply = await hub.elements.read(principal, None, grant["id"], options, OUT_BYTES - size(result) - 16)
    except HTTPException as exc:  # the share ended meanwhile: the action still happened
        return {"error": str(exc.detail)}
    return {key: item for key, item in reply.items() if key not in ("window", "snapshot_id")}


@timed
async def element_action(runtime, hub, conv_id: str, body: ElementAction, request: Request):
    principal = request_principal(request)
    deny_unless(runtime.db, principal, conv_id, "write")
    if body.then:
        deny_unless(runtime.db, principal, conv_id, "read")
    try:
        grant, device = resolve_window(hub, principal, body.window)
        message = body.parameters()
        if body.mark is not None:
            look, _, _ = hub.snapshots.looks.target(principal, grant, body.mark)
            message["look_generation"] = look["generation"]
        if body.action == "press" and device.get("press", 0) < WINDOW_PRESS_VERSION:
            raise ValueError("update the Partyline helper to use press")
        if body.action == "dialog" and device.get("chrome_dom", 0) < 5:
            raise ValueError("update the Partyline helper to use dialog")
        if body.action == "reload" and device.get("chrome_dom", 0) < 4:
            raise ValueError("update the Partyline helper to use reload")
        if body.action == "set_files" and device.get("chrome_dom", 0) < 2:
            raise ValueError("CDP file upload unavailable; update the helper or "
                             "use the Open dialog path instead")
        if body.action == "set_files":
            from .screen_file_input import resolve_files, audit_files
            if body.paths and device.get("chrome_dom", 0) < 3:
                raise ValueError("update the helper to use local paths")
            files, total = resolve_files(hub, principal, body.files or [])
            audit_files(hub, principal, grant, body.files or [], total)
        with phase("target_ms"):
            target = True
            if body.action not in ("reload", "dialog"):
                target, busy = await hub.elements.action_target(principal, grant, body.element_id)
        if target is None:
            if busy:
                return {"status": "failed", "reason": "target_changed", "error": TARGET_CHANGING}
            return {"status": "failed", "error": REFRESH_FAILED}
        token = action_token(hub.elements, grant["id"], body.element_id)
        async with hub.elements.locked(grant["id"]):  # processes on the line never interleave on a window
            if body.mark is not None:
                look, _, _ = hub.snapshots.looks.target(principal, grant, body.mark)
                if look["generation"] != message["look_generation"]:
                    raise HTTPException(409, "stale mark; take a fresh screen_window_look")
            known = True
            if body.action not in ("reload", "dialog"):
                message["element_id"], known = hub.elements.locked_target(grant["id"], body.element_id)
            if message["element_id"] is None:
                return {"status": "failed", "error": REFRESH_FAILED}
            if not known:
                tree = hub.elements.snapshots.get(grant["id"])
                return {"status": "failed", "error": getattr(tree, "recovery_hint", None) or STALE}
            if body.action not in ("reload", "dialog") and (message["element_id"] != target or
                    token != action_token(hub.elements, grant["id"], body.element_id)):
                return {"status": "failed", "reason": "target_changed", "error": TARGET_CHANGING}
            if token:
                message["action_token"] = token
            hub.window_grants.spend(grant)
            if body.action == "set_files":
                from .screen_file_input import ticket
                with ticket(hub, principal, grant, files, len(body.paths or [])) as key:
                    message["files"] = [{k: f[k] for k in ("id", "name", "bytes")} for f in files]
                    message["file_ticket"] = key
                    if body.paths:
                        from .screen_file_input import MAX_TOTAL
                        from .media_files import MAX_FILE_BYTES
                        message["file_limits"] = {"file": MAX_FILE_BYTES, "total": MAX_TOTAL}
                    response = await hub.elements.exchange(principal, grant, device, "window_element_action",
                        agent=principal.name, title=grant.get("title", ""),
                        process=grant.get("process", ""), **message)
            else:
                response = await hub.elements.exchange(principal, grant, device, "window_element_action",
                    agent=principal.name, title=grant.get("title", ""),
                    process=grant.get("process", ""), **message)
        result = {key: value for key, value in response.items() if key not in ("type", "request_id")}
        if result.get("status") in ("completed", "no_effect") and not result.get("grant_ended"):
            if body.then and body.then.reads():
                result["after"] = await after(hub, principal, grant, body.then, result)
                if result.get("source") == "cdp" and result.get("settle") == "quiet":
                    observed = result["after"].get("snapshot_event_counter")
                    if (observed != result.get("settled_event_counter")
                            or result["after"].get("change_event_since_snapshot")):
                        result["settle"] = "changing"
                if not body.then.explicit():
                    result["after"] = diffed(result["after"])
                if body.action == "set_files":  # what was uploaded is the answer, whatever the read was
                    result["after"]["files"] = result.pop("files", [])
                    result["after"]["file_count"] = result.pop("count", 0)
            tree = hub.elements.snapshots.get(grant["id"])
            hub.elements.action_completed(grant["id"], bool(body.then and body.then.reads() and tree))
        return result
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (TimeoutError, OSError, RuntimeError):
        return {"status": "unconfirmed", "note": "The helper did not confirm the action; "
                "it may have run. Do not retry automatically."}
