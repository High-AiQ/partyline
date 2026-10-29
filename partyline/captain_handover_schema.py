"""Durable handover protocol migration entries."""

# Captain handovers survive server restarts. Accepted rows remain pending until
# both parties complete the separate confirmation protocol.
MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS captain_handovers(
        id TEXT PRIMARY KEY, conv_id TEXT NOT NULL, from_attachment_id TEXT NOT NULL,
        to_attachment_id TEXT NOT NULL, debrief TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('offered','accepted','completed','cancelled','expired')),
        offered_at REAL NOT NULL, accepted_at REAL, completed_at REAL, cancelled_at REAL,
        expired_at REAL, from_done INTEGER NOT NULL DEFAULT 0, to_done INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS captain_handovers_pending ON captain_handovers(conv_id) "
    "WHERE state IN ('offered','accepted')",
]

# Completion persists a detach intent and a deduplicated timeout notice.
MIGRATIONS += [
    "ALTER TABLE captain_handovers ADD COLUMN timeout_notified_at REAL",
    "ALTER TABLE captain_handovers ADD COLUMN detach_finished_at REAL",
]
