"""Bounded, credential-free diagnostics for retirement operations."""

import re
import subprocess


_URL_USERINFO = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^\s/@]+@")
_AUTHORIZATION = re.compile(r"(?i)(authorization\s*:\s*)(?:\S+\s+)?\S+")
_SECRET_FIELD = re.compile(
    r"(?i)(\b(?:access_token|api[_-]?key|credential|password|passwd|secret|token)\s*[:=]\s*)\S+")
_QUERY_SECRET = re.compile(r"(?i)([?&](?:access_token|key|password|secret|token)=)[^&\s]+")


def safe_text(value) -> str:
    """Keep actionable process text while removing common credential spellings."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = " ".join(str(value or "").split())
    for pattern, replacement in (
            (_URL_USERINFO, r"\1[redacted]@"), (_AUTHORIZATION, r"\1[redacted]"),
            (_QUERY_SECRET, r"\1[redacted]"), (_SECRET_FIELD, r"\1[redacted]")):
        text = pattern.sub(replacement, text)
    return text[:600]


def operation_reason(exc: BaseException) -> str:
    """An OS/process reason, or only a type when arbitrary text cannot be trusted."""
    if isinstance(exc, subprocess.SubprocessError):
        return safe_text(getattr(exc, "stderr", None)) or type(exc).__name__
    if isinstance(exc, OSError):
        return safe_text(exc.strerror or str(exc)) or type(exc).__name__
    return type(exc).__name__


def git_reason(done=None, exc=None) -> str:
    """Git's trimmed stderr or safe launch error, without echoing credentials."""
    detail = "cannot inspect retirement Git state"
    if exc is not None:
        return f"{detail}: {operation_reason(exc)}"
    return detail + (f": {text}" if (text := safe_text(getattr(done, "stderr", None))) else "")
