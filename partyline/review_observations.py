"""Persistence for first-class, immutable structured review decisions."""

from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import UTC, datetime


class PresentationNotFound(Exception):
    """The named presentation is absent from this conversation."""


class DecisionAlreadyExists(Exception):
    """One human already made the immutable decision for this presentation."""


class ConversationArchived(Exception):
    """A decision cannot be created while its line is archived."""


class ReviewDecisionStore:
    def __init__(self, db):
        self.db = db

    def _presentation_exists(self, conv_id: str, message_id: int) -> bool:
        row = self.db.conn.execute(
            "SELECT 1 FROM messages WHERE conv_id=? AND id=?", (conv_id, message_id)
        ).fetchone()
        return row is not None

    def create(self, conv_id: str, presentation_message_id: int, user_id: int, decision: str):
        message_id = presentation_message_id
        source_id = str(uuid.uuid4())
        with self.db.lock:
            conversation = self.db.conn.execute(
                "SELECT archived_at FROM conversations WHERE id=?", (conv_id,)
            ).fetchone()
            if conversation is None or not self._presentation_exists(conv_id, message_id):
                raise PresentationNotFound
            if conversation["archived_at"] is not None:
                raise ConversationArchived
            created_at = time.time()
            try:
                self.db.conn.execute(
                    "INSERT INTO review_decisions "
                    "(id, conv_id, presentation_message_id, sender_user_id, decision, created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (source_id, conv_id, message_id, user_id, decision, created_at),
                )
                self.db.conn.commit()
            except sqlite3.IntegrityError as exc:
                self.db.conn.rollback()
                raise DecisionAlreadyExists from exc
        return self._row(source_id, conv_id, message_id, user_id, decision, created_at)

    def list(self, conv_id: str, presentation_message_id: int) -> list[dict]:
        message_id = presentation_message_id
        with self.db.lock:
            if not self._presentation_exists(conv_id, message_id):
                raise PresentationNotFound
            rows = self.db.conn.execute(
                "SELECT * FROM review_decisions WHERE conv_id=? AND presentation_message_id=? "
                "ORDER BY created_at, id",
                (conv_id, message_id),
            ).fetchall()
        return [self._row(**dict(row)) for row in rows]

    @staticmethod
    def _row(id, conv_id, presentation_message_id, sender_user_id, decision, created_at):
        return {
            "conversation_id": conv_id,
            "presentation_message_id": str(presentation_message_id),
            "evidence_kind": "decision",
            "evidence_ref": f"decision:{id}",
            "sender_id": f"partyline-user-{sender_user_id}",
            "decision": decision,
            "observed_at": datetime.fromtimestamp(created_at, UTC),
        }
