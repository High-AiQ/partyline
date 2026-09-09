"""Adopt existing lines through an explicit, reviewed local operator mapping."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from pydantic import BaseModel, ConfigDict, Field


class LineAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1)
    parent_id: str | None
    manager_attachment_id: str | None


class Setup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[LineAssignment] = Field(min_length=1, max_length=1000)


def inspect_mapping(connection: sqlite3.Connection, setup: Setup) -> dict:
    """Validate the complete proposed graph before any role or parent write."""
    connection.row_factory = sqlite3.Row
    lines = {row["id"]: dict(row) for row in connection.execute("SELECT * FROM conversations")}
    columns = {row[1] for row in connection.execute("PRAGMA table_info(attachments)")}
    fields = "id,conv_id,name" + (",is_lead" if "is_lead" in columns else "")
    attachments = {row["id"]: dict(row) for row in connection.execute(f"SELECT {fields} FROM attachments")}
    requested = [line.conversation_id for line in setup.lines]
    if len(requested) != len(set(requested)):
        raise ValueError("a line may appear only once in the mapping")
    parents = {ident: row.get("parent_id") for ident, row in lines.items()}
    changes = []
    for assignment in setup.lines:
        ident, parent, manager = (assignment.conversation_id, assignment.parent_id,
                                  assignment.manager_attachment_id)
        current = lines.get(ident)
        if current is None or current.get("archived_at"):
            raise ValueError(f"line {ident} is missing or archived")
        if parent is not None and (parent not in lines or lines[parent].get("archived_at")):
            raise ValueError(f"parent {parent} is missing or archived")
        if manager is not None and (manager not in attachments or attachments[manager]["conv_id"] != ident):
            raise ValueError(f"manager {manager} is not attached to line {ident}")
        managers = [att["id"] for att in attachments.values()
                    if att["conv_id"] == ident and att.get("is_lead")]
        if len(managers) > 1:
            raise ValueError(f"line {ident} already has conflicting manager assignments")
        changes.append({
            "conversation_id": ident, "name": current["name"],
            "old_parent_id": current.get("parent_id"), "parent_id": parent,
            "old_manager_attachment_id": managers[0] if managers else None,
            "manager_attachment_id": manager,
            "manager_name": attachments[manager]["name"] if manager else None,
        })
        parents[ident] = parent
    for ident in parents:
        seen = set()
        current = ident
        while current is not None:
            if current in seen:
                raise ValueError("the proposed parent graph contains a cycle")
            seen.add(current)
            if current not in parents:
                raise ValueError("the parent graph contains a missing line")
            current = parents[current]
    for change in changes:
        scope = []
        for ident in parents:
            current = ident
            while current is not None:
                if current == change["conversation_id"]:
                    scope.append({"id": ident, "name": lines[ident]["name"]})
                    break
                current = parents[current]
        change["managed_lines"] = sorted(scope, key=lambda row: row["id"])
    payload = {"changes": sorted(changes, key=lambda row: row["conversation_id"])}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {**payload, "sha256": digest}


def preview(database: Path, setup: Setup) -> dict:
    # Read-only means no migrations, no accidentally created database, no credentials read.
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return inspect_mapping(connection, setup)
    finally:
        connection.close()


def apply(database: Path, setup: Setup, expected_sha256: str) -> dict:
    reviewed = preview(database, setup)
    if reviewed["sha256"] != expected_sha256:
        raise ValueError("mapping changed since review; preview it again before applying")
    from partyline.db import Db

    db = Db(database)
    try:
        # Serialize against runtime ownership changes and recheck within the write transaction.
        with db._runtime_serialized(), db.lock, db.conn:
            db.conn.execute("BEGIN IMMEDIATE")
            current = inspect_mapping(db.conn, setup)
            if current["sha256"] != expected_sha256:
                raise ValueError("mapping changed during apply; no role or parent changes were made")
            for assignment in setup.lines:
                db.conn.execute("UPDATE conversations SET parent_id=? WHERE id=?",
                                (assignment.parent_id, assignment.conversation_id))
                db.conn.execute("UPDATE attachments SET is_lead=0 WHERE conv_id=?",
                                (assignment.conversation_id,))
                if assignment.manager_attachment_id is not None:
                    db.conn.execute("UPDATE attachments SET is_lead=1 WHERE id=?",
                                    (assignment.manager_attachment_id,))
        return current
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="exact local instance database")
    parser.add_argument("--file", type=Path, required=True, help="explicit JSON parent/manager mapping")
    parser.add_argument("--apply", action="store_true", help="apply the reviewed mapping atomically")
    parser.add_argument("--expected-sha256", help="digest from the reviewed preview; required with --apply")
    args = parser.parse_args(argv)
    if args.apply and not args.expected_sha256:
        parser.error("--apply requires --expected-sha256 from a reviewed preview")
    try:
        setup = Setup.model_validate_json(args.file.read_text())
        result = (apply(args.database, setup, args.expected_sha256) if args.apply
                  else preview(args.database, setup))
        print(json.dumps({"applied": args.apply, **result}, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"line management refused: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
