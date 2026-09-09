"""Read-only inspection of the live restart plan, split from `cockpit.py`.

Deliberately not over HTTP: the cases these checks exist to catch are a server
that never restarted, and a plan that does not cover everything the restart is
about to kill. Asking that server about either would be asking the wrong
process about its own replacement.

``mode=ro`` is load-bearing throughout — constructing :class:`partyline.db.Db`
would apply migrations and commit from commands advertised as preflights.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    """One thing that is wrong, and what to do about it."""

    problem: str
    fix: str


@dataclass(frozen=True)
class PendingPlanInspection:
    plan: Mapping[str, object] | None
    findings: list[Finding]


@dataclass(frozen=True)
class LiveAttachment:
    """A process the restart will stop, named the way an operator reads it."""

    attachment_id: str
    handle: str
    line: str
    adapter: str = ""


def resolve_database(database: Path | None) -> Path:
    return database or Path(
        os.environ.get("PARTYLINE_DB", os.path.expanduser("~/.partyline.db"))
    )


def _connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def inspect_pending_plan(database: Path | None = None) -> PendingPlanInspection:
    """Read the persisted plan without migrating or writing the live database."""
    database = resolve_database(database)
    if not database.is_file():
        return PendingPlanInspection(None, [])
    try:
        connection = _connect(database)
        try:
            if not _has_table(connection, "restart_plan"):
                return PendingPlanInspection(None, [])
            # A plan written by a pre-auth server has no report_token column;
            # select it only when it exists so the preflight stays readable.
            names = {info[1] for info in connection.execute(
                "PRAGMA table_info(restart_plan)")}
            fields = "conversation_id, token, mode, attempt_count, created_at"
            # Both columns are optional only for plans written by an older
            # server; select each one only where the table actually has it so
            # the preflight never migrates what it came to read.
            for optional in ("report_token", "attachment_ids"):
                if optional in names:
                    fields += f", {optional}"
            row = connection.execute(
                f"SELECT {fields} FROM restart_plan WHERE singleton=1"
            ).fetchone()
            return PendingPlanInspection(dict(row) if row else None, [])
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return PendingPlanInspection(None, [Finding(
            f"the live restart plan cannot be inspected read-only: {exc}",
            f"inspect {database} with sqlite3 before trusting restart state",
        )])


def planned_attachment_ids(plan: Mapping[str, object] | None) -> set[str] | None:
    """The ids a plan will recover, or ``None`` when the plan cannot say.

    ``None`` is not an empty plan. A plan persisted by a server older than the
    ``attachment_ids`` column simply does not record its coverage, and treating
    unknown coverage as "covers nothing" would be a guess in the direction the
    caller least wants guessed.
    """
    if not plan:
        return set()
    raw = plan.get("attachment_ids")
    if raw is None:
        return None
    if not isinstance(raw, str):
        return set()
    try:
        parsed = json.loads(raw)
    except ValueError:
        return set()
    return {str(item) for item in parsed} if isinstance(parsed, list) else set()


def live_attachments(database: Path | None = None) -> list[LiveAttachment]:
    """Every process a restart would stop, with the line it belongs to."""
    database = resolve_database(database)
    if not database.is_file():
        return []
    connection = _connect(database)
    try:
        if not _has_table(connection, "attachments"):
            return []
        rows = connection.execute(
            "SELECT a.id AS id, a.name AS name, a.adapter AS adapter, c.name AS line"
            " FROM attachments a LEFT JOIN conversations c ON c.id = a.conv_id"
            " WHERE a.status IN ('starting','running')"
            " ORDER BY c.name COLLATE NOCASE, a.created_at"
        ).fetchall()
        return [
            LiveAttachment(
                row["id"], row["name"], row["line"] or "an archived line", row["adapter"]
            )
            for row in rows
        ]
    finally:
        connection.close()


def database_for_environment(
    env: Mapping[str, str], cwd: Path | None = None
) -> Path:
    """The database the outgoing server was actually using.

    Read from that server's own environment snapshot rather than the trigger's:
    a transient systemd unit inherits neither ``PARTYLINE_DB`` nor the
    interactive user's ``HOME``, and guessing either would check coverage
    against the wrong instance. ``PARTYLINE_DB`` may be relative, in which case
    it means relative to the server's working directory, not the trigger's — an
    unresolvable relative path stays relative and is refused downstream as
    missing, which is the safe direction.
    """
    if configured := env.get("PARTYLINE_DB"):
        path = Path(configured)
        return path if path.is_absolute() or cwd is None else cwd / path
    return Path(env.get("HOME") or os.path.expanduser("~")) / ".partyline.db"


def coverage_refusal(database: Path) -> str | None:
    """Why this database's plan would orphan a process, or ``None`` if it would not.

    Arming checks coverage, but the trigger fires up to 90 seconds later, and a
    process attached inside that window is in no plan at all. The check
    therefore has to run again with the signal about to be sent, not only when
    the timer was scheduled.

    Every way of *not knowing* is a refusal. A database that is missing, has no
    schema, or has lost its plan is not an instance with nothing to lose — it is
    the wrong path, or an instance something else has already changed, and the
    one question being asked here is whether SIGTERM is about to strand a
    process. Refusing costs one postponed restart; assuming costs whichever
    processes were live.
    """
    if not database.is_absolute():
        # Refused before any filesystem read. A relative path here means
        # resolution against the server's own directory failed, and the
        # trigger's directory is not a fallback: a same-named database sitting
        # there would answer for the wrong instance and, if it happened to be
        # fully covered, would let the restart through.
        return (
            f"the instance database path {database} is relative and the outgoing "
            "server's working directory could not be resolved"
        )
    if not database.is_file():
        return f"the instance database is missing at {database}"
    try:
        connection = _connect(database)
        try:
            absent = [
                table for table in ("restart_plan", "attachments")
                if not _has_table(connection, table)
            ]
        finally:
            connection.close()
        if absent:
            return f"{database} has no {' or '.join(absent)} table"
        inspection = inspect_pending_plan(database)
        if inspection.findings:
            return "; ".join(finding.problem for finding in inspection.findings)
        if inspection.plan is None:
            return f"the restart plan is no longer recorded in {database}"
        findings = unaccounted_findings(inspection.plan, live_attachments(database))
    except sqlite3.Error as exc:
        return f"coverage could not be re-read from {database}: {exc}"
    return findings[0].problem if findings else None


def unaccounted_findings(
    plan: Mapping[str, object] | None,
    live: list[LiveAttachment],
) -> list[Finding]:
    """Refuse to arm while a live process would be stopped and never resumed.

    A restart stops every attached process, but recovery only resumes what the
    plan names. Anything else comes back detached and silent, and the only
    symptom is a line that has stopped answering — the same shape of failure
    that let two broken triggers go unnoticed for hours.

    A process whose adapter cannot resume can never appear in a plan, so it is
    reported here too. That is not a false positive: it genuinely cannot be
    recovered, and stopping it has to be a decision somebody makes on purpose.
    The fix text has to say so, because re-planning is the obvious next move and
    it will not clear such a process however many times it is tried.
    """
    planned = planned_attachment_ids(plan)
    if planned is None:
        return [Finding(
            "the persisted restart plan does not record which processes it covers",
            "re-plan with `scripts.cockpit plan LINE --all --debrief ...`; this plan "
            "predates coverage tracking and cannot be checked",
        )]
    orphans = [attachment for attachment in live if attachment.attachment_id not in planned]
    if not orphans:
        return []
    listed = ", ".join(
        f"@{orphan.handle} on {orphan.line!r}"
        + (f" ({orphan.adapter})" if orphan.adapter else "")
        for orphan in orphans
    )
    return [Finding(
        f"{len(orphans)} live process(es) would be stopped without recovery: {listed}",
        "re-plan with `scripts.cockpit plan LINE --all --debrief ...` to cover every "
        "line. A process still listed after that cannot be resumed by its adapter and "
        "will not come back: stop it explicitly with the close control, or accept "
        "losing it, before arming",
    )]
