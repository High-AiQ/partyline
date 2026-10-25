"""WebSocket contracts for pending human approvals."""

from typing import Any, Literal

from pydantic import BaseModel


class ApprovalsChangedEvent(BaseModel):
    """A pending approval changed on this line or one of its descendants."""
    type: Literal["approvals_changed"] = "approvals_changed"


class RestartRequestEvent(BaseModel):
    """The pending restart request changed: filed, approved, or declined."""
    type: Literal["restart_request"] = "restart_request"
    request: Any = None


class WriteSetGrantRequestEvent(BaseModel):
    """The pending write-set grant request on a line changed."""
    type: Literal["write_set_grant_request"] = "write_set_grant_request"
    request: Any = None
