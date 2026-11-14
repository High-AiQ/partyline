"""Tool and sub-operation labels for usage records: names only, never argument values."""

from functools import lru_cache
import re

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
PARTYLINE_PREFIXES = ("mcp__partyline__", "partyline_")
DOORS = ("extras", "captain")


@lru_cache(maxsize=1)
def vocabulary() -> tuple[frozenset, frozenset]:
    """The fixed sub-operation names and the screen element actions a label may carry."""
    from .mcp import catalog, tools_captain, tools_control, tools_tasks
    ops = (catalog.EXTRAS_OPS | catalog.SCREEN | set(tools_captain.OPERATIONS)
           | set(tools_tasks.OPERATIONS))
    return frozenset(ops), frozenset(tools_control.ELEMENT_ACTION_PROPERTIES["action"]["enum"])


def _word(value, allowed) -> str:
    return value if isinstance(value, str) and value in allowed else ""


def sub_op(name: str, args) -> str:
    """The door operation, or the screen action for ``screen_element_action``; "" when none.

    The same rule the MCP result telemetry uses, so the two tables join on (tool, sub-op): an
    operation outside the vocabulary is discarded, never kept.
    """
    args = args if isinstance(args, dict) else {}
    ops, actions = vocabulary()
    op = _word(args.get("op"), ops) if name in DOORS else ""
    inner = args.get("args") if name in DOORS else args
    action = inner.get("action") if isinstance(inner, dict) else None
    if (op or name) == "screen_element_action":
        return _word(action, actions) or op
    return op


def tool_label(name, args=None) -> str | None:
    """`tool` or `tool:sub_op`. Foreign tools keep a safe name; anything odd becomes `unknown`."""
    if not isinstance(name, str) or not name:
        return None
    ours = False
    for prefix in PARTYLINE_PREFIXES:
        if name.startswith(prefix):
            name, ours = name[len(prefix):], True
            break
    if not SAFE_NAME.match(name):
        return "unknown"
    sub = sub_op(name, args) if (ours or name in DOORS or name == "screen_element_action") else ""
    return f"{name}:{sub}" if sub else name
