"""Map OpenCode message records to turn receipts."""

from partyline.adapters.receipts import BEGAN, ENDED


def boundary_event(role: str | None, finish: str | None) -> str | None:
    """The turn boundary one message row represents, if any.

    ``tool-calls`` means the loop continues with another step; anything else
    on a completed assistant message means the CLI is waiting for input again.
    """
    if role == "user":
        return BEGAN
    if role == "assistant" and finish != "tool-calls":
        return ENDED
    return None
