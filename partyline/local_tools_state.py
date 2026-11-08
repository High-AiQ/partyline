"""What the server keeps about a local tools session and the limits it enforces (memory only)."""

import asyncio
import os
from collections import deque
from dataclasses import dataclass, field

from . import local_tools_audit as audit
from .render_check import CHECK_MAX


@dataclass(frozen=True)
class ToolLimits:
    per_minute: int = 60
    per_session: int = 500
    max_code: int = audit.MAX_CODE
    render_checks: int = CHECK_MAX

    @classmethod
    def from_env(cls, env=os.environ) -> "ToolLimits":
        def read(name: str, default: int) -> int:
            raw = env.get(name, "").strip()
            if not raw:
                return default
            if not raw.isdigit() or int(raw) < 1:
                raise ValueError(f"{name} must be a positive integer, not {raw!r}")
            return int(raw)

        return cls(read("PARTYLINE_TOOLS_RATE", cls.per_minute),
                   read("PARTYLINE_TOOLS_SESSION_CALLS", cls.per_session),
                   render_checks=read("PARTYLINE_RENDER_CHECK_MAX", cls.render_checks))


@dataclass
class ToolSession:
    session_id: str
    conv_id: str
    device_id: str
    tool: str
    agent: str
    status: str = "pending"  # pending -> active -> revoked
    checker: bool = False    # the person ticked the render-check box and has not withdrawn it since
    scope_pending: bool = False
    reason: str = ""
    info: dict = field(default_factory=dict)
    times: deque = field(default_factory=deque)
    count: int = 0
    audit_count: int = 0
    media_bytes: int = 0
    renders: dict = field(default_factory=dict)  # render id -> checkable (checks were allowed)
    checks: int = 0                              # decision-model requests spent on this session
    flusher: asyncio.Task | None = None
