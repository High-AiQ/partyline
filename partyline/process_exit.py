"""Collect scope evidence outside the process tree that can be OOM-killed."""

import asyncio
import logging
import re
import signal as signals
import subprocess
import uuid

from .memory_contracts import ProcessExit
from .process_memory import parse_size

logger = logging.getLogger(__name__)
SCOPE = re.compile(r"partyline-process-[a-f0-9]{32}\.scope")


def exit_signal(code: int) -> str | None:
    """The signal name behind an exit: -N from a signal kill, 128+N from a shell or wrapper."""
    if code < 0:
        number = -code
    elif 128 < code < 128 + 65:
        number = code - 128
    else:
        return None
    try:
        return signals.Signals(number).name
    except ValueError:
        return f"signal {number}"


def signal_clause(evidence: ProcessExit) -> str:
    if evidence.signal is None:
        return ""
    return f", {evidence.signal} sent by {evidence.sent_by or 'external'}"


def new_scope() -> str:
    return f"partyline-process-{uuid.uuid4().hex}.scope"


def inspect_exit(scope: str | None, code: int, limit: str) -> ProcessExit:
    evidence = ProcessExit(code=code, limit_bytes=parse_size(limit), scope=scope,
                           reason="unverified" if code == 125 else "exit")
    if not scope or not SCOPE.fullmatch(scope):
        return evidence
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", scope, "--no-pager",
             "--property=Result,MemoryPeak,MemoryMax"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode:
            return evidence
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        evidence.result = fields.get("Result") or None
        # UINT64_MAX is systemd's 'not available', not a real measurement.
        for key, attr in (("MemoryPeak", "peak_bytes"), ("MemoryMax", "limit_bytes")):
            value = fields.get(key, "")
            if value.isdigit() and 0 < int(value) < 2**64 - 1:
                setattr(evidence, attr, int(value))
        if evidence.result == "oom-kill":
            evidence.reason = "oom"
    except (OSError, subprocess.SubprocessError):
        logger.warning("could not read memory evidence for %s", scope, exc_info=True)
    return evidence


def stop_scope(scope: str | None) -> None:
    """Ask systemd to drop a scope without waiting for it.

    A named scope cannot use ``--collect`` (that discards the failed result the
    OOM report reads), so nothing garbage-collects it if the manager misses the
    cgroup going empty: it stays active and empty for good. Stopping it is a
    no-op on a gone scope, keeps a failed scope's result, and kills only
    stragglers an exited process left behind.
    """
    if not scope or not SCOPE.fullmatch(scope):
        return
    try:
        subprocess.run(["systemctl", "--user", "stop", "--no-block", scope],
                       capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        logger.warning("could not stop scope %s", scope, exc_info=True)


def release_scope(scope: str | None) -> None:
    """Stop the scope and clear any failed result nobody needs any more."""
    if not scope or not SCOPE.fullmatch(scope):
        return
    stop_scope(scope)
    try:
        subprocess.run(["systemctl", "--user", "reset-failed", scope],
                       capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        logger.warning("could not release failed scope %s", scope, exc_info=True)


def exit_notice(name: str, evidence: ProcessExit) -> str:
    if evidence.startup and evidence.reason == "exit":
        tail = " | ".join((evidence.last_output or "").splitlines()[-3:])
        return (f"⚠ @{name} exited during startup (code {evidence.code}{signal_clause(evidence)})"
                + (f": {tail}" if tail else " with no output"))
    if evidence.reason == "oom":
        peak = (f", recorded peak {evidence.peak_bytes / 1024**2:.0f} MiB"
                if evidence.peak_bytes is not None else ", recorded peak not sampled")
        return (f"{name} stopped: confirmed out-of-memory kill in its process tree "
                f"(limit {evidence.limit_bytes / 1024**2:.0f} MiB{peak}; "
                f"exit code {evidence.code}{signal_clause(evidence)}).")
    if evidence.reason == "unverified":
        return f"{name} refused to start: its memory limit could not be verified"
    return f"{name} exited (code {evidence.code}{signal_clause(evidence)})"


async def report_exit(adapter, code: int) -> None:
    scope = getattr(adapter, "memory_scope", None)
    recorded = False
    # This activation's own stop request, bound by its stop(); never another activation's.
    intent = getattr(adapter, "_stop_intent", None)
    try:
        evidence = await asyncio.to_thread(inspect_exit, scope, code, adapter.memory_limit)
        evidence.signal = exit_signal(code)
        if evidence.signal:
            evidence.sent_by = f"partyline: {intent}" if intent else "external"
        if adapter._stopping:
            if evidence.signal:
                logger.info("%s exited from %s sent by %s", adapter.att["name"],
                            evidence.signal, evidence.sent_by)
            return
        # Only adapters that declare readiness (transcript ones) can tell a
        # startup death from an ordinary exit.
        if getattr(adapter, "_ready_result", True) is not True and adapter.pastes_claim():
            evidence.startup = True
            tail = getattr(adapter, "output_tail", None)
            # Output is relayed into a notice: a quoted @handle must not ring anyone.
            evidence.last_output = "\n".join(tail.lines(15)).replace("@", "＠") if tail else None
        await adapter.on_status("exited")
        callback = adapter.att.get("on_process_exit")
        if callback:
            await callback(evidence)
        else:
            await adapter.post("system", "system", exit_notice(adapter.att["name"], evidence))
        recorded = True
    except Exception:
        logger.exception("exit report failed; retaining scope evidence for %s", scope)
        raise
    finally:
        # A failed diagnostic must not erase evidence an operator can read later.
        if adapter._stopping or (recorded and (not scope or evidence.result is not None)):
            await asyncio.to_thread(release_scope, scope)
        else:
            # The failed result stays readable, but an active empty scope must not.
            await asyncio.to_thread(stop_scope, scope)
