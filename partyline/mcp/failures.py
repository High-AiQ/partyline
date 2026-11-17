"""What an MCP tool call says when the HTTP call under it failed.

A timeout or reset arrives after the server may already have acted, so it is
never reported as a bad argument. Only the exception's type is read, never its
text: that text can hold the credential or the caller's JSON.
"""

from __future__ import annotations

import http.client

from ..agent_client import classify_failure, failure_text

LOCAL_FAILURE = "invalid tool arguments or local file"
CREATE_TASK = ("create_task connection failed; the task may already exist. "
               "Retry create_task with the same name and assignment, or inspect tasks().")


def network_failure(exc: BaseException) -> str | None:
    """The failure kind when `exc` is a timeout or connection fault, else None."""
    if not isinstance(exc, (OSError, http.client.HTTPException)):
        return None
    kind = classify_failure(exc)
    return None if kind == "local" else kind


def tool_failure_message(exc: BaseException, name: str, args: dict, *, reached: bool) -> str | None:
    """The tool result text for a transport failure, or None when `exc` is not one.

    `reached` is False when the failure came before the tool ran (the
    capability read), so nothing can have been applied.
    """
    kind = network_failure(exc)
    if kind is None:
        return None
    if not reached:
        return ("Partyline could not be reached to check this attachment's capabilities "
                f"({failure_text(kind, changes_state=False)}); the tool did not run.")
    if name == "create_task" or (name == "captain" and args.get("op") == "create_task"):
        return CREATE_TASK
    method = getattr(exc, "partyline_method", None)
    return failure_text(kind, changes_state=method != "GET")
