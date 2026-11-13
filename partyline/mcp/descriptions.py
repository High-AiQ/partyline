"""One-line tool descriptions and schemas without the noise a model never reads.

`tools/list` is paid for on every turn. The full text of a tool (its long description and
every property note) stays in the module that serves it and is returned by
`guide(topic=<tool>)`; the listing carries a line.
"""

from __future__ import annotations

LINE = 150
PROPERTY = 90

# Hand-written lines for tools whose first sentence is not enough to choose them by.
SHORT = {
    "create_task": "START new work: create a task line with an implementer and a reviewer "
                   "(mode=express: no reviewer). Retrying the same name recovers it.",
    "set_task_goal": "CHANGE the direction of an existing active task (conv_id = task line id).",
    "reopen_task": "CONTINUE an approved or done task with a new goal (conv_id = task line id).",
    "attach_worker": "Staff an implementer (or staffing_role=captain, or successor=true on your own line).",
    "retire_child": "Retire a child line; guarded by default. Run retirement_preview first.",
    "retirement_preview": "Preview what retiring a line would discard; returns the preview_token.",
    "process_overview": "Live processes and workspace tips per line; the mirror tip holds commits.",
    "get_media": "Download a media variant of a file on your line or above it to a new local path.",
    "read_messages": "Read a bounded page of messages (or around an id); `resume` says where to continue.",
    "tasks": "The board of live tasks; conv_id gives one in full, include_retired=true adds retired ones.",
    "render_check": "Ask which renders need a closer look (needs consent).",
    "acquire_resource": "Take an advisory lease before a job needing a declared resource; release when done.",
    "review_verdict": "Give the verdict on the requested review: approve or changes, with findings.",
    "request_review": "Hand a full task to review: sha, what, where. Refused on an express task.",
    "blocked": "Tell the root captain you are blocked, with the reason.",
    "env_gap": "Report a review test environment gap to the root captain.",
    "waiting": "Tell the server a long command is running, so you are not called stalled.",
    "resume_work": "Say you resumed work after being blocked, with a note.",
    "deliver": "END an express task: report what and where as text; there is no SHA or review.",
}


# Bounds the server checks again on every call and names in its refusal: not worth a line each.
NOISE = frozenset({"title", "default", "examples", "minLength", "additionalProperties", "pattern"})


def _sentence(text: str, limit: int) -> str:
    text = " ".join(text.split())
    for stop in (". ",):
        cut = text.find(stop)
        if 0 < cut < limit:
            return text[:cut + 1]
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def one_line(name: str, description: str) -> str:
    return SHORT.get(name) or _sentence(description, LINE)


def slim_schema(schema):
    """The schema minus titles and defaults, with each property note cut to its first sentence."""
    if isinstance(schema, list):
        return [slim_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key in NOISE:
            continue
        if key == "properties" and isinstance(value, dict):
            result[key] = {prop: slim_schema(rule) for prop, rule in value.items()}
        elif key == "description" and isinstance(value, str):
            result[key] = _sentence(value, PROPERTY)
        else:
            result[key] = slim_schema(value)
    return result
