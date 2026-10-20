"""Append-only orchestrator mode and durable task review state."""

MIGRATIONS = [
    "ALTER TABLE conversations ADD COLUMN captain_mode TEXT NOT NULL DEFAULT 'manager_tree'",
    "ALTER TABLE conversations ADD COLUMN default_review_policy TEXT NOT NULL DEFAULT 'captain'",
    """CREATE TABLE IF NOT EXISTS task_reviews(
        conv_id TEXT PRIMARY KEY REFERENCES conversations(id),
        root_id TEXT NOT NULL REFERENCES conversations(id),
        implementer_id TEXT NOT NULL UNIQUE,
        implementer_preset TEXT NOT NULL,
        policy TEXT NOT NULL,
        reviewer_id TEXT UNIQUE,
        status TEXT NOT NULL DEFAULT 'implementing'
            CHECK(status IN ('implementing','in_review','approved','done')),
        round INTEGER NOT NULL DEFAULT 0,
        sha TEXT,
        review_worktree TEXT,
        what TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT '',
        findings TEXT NOT NULL DEFAULT '',
        report_id INTEGER,
        merged INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    )""",
    """CREATE TRIGGER IF NOT EXISTS orchestrator_root_insert BEFORE INSERT ON conversations
        WHEN NEW.captain_mode NOT IN ('manager_tree','orchestrator')
          OR (NEW.captain_mode='orchestrator' AND NEW.parent_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'orchestrator mode requires a root line'); END""",
    """CREATE TRIGGER IF NOT EXISTS orchestrator_root_update BEFORE UPDATE ON conversations
        WHEN NEW.captain_mode NOT IN ('manager_tree','orchestrator')
          OR (NEW.captain_mode='orchestrator' AND NEW.parent_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'orchestrator mode requires a root line'); END""",
    """CREATE TRIGGER IF NOT EXISTS task_attachment_insert BEFORE INSERT ON attachments
        WHEN EXISTS(SELECT 1 FROM task_reviews t WHERE t.conv_id=NEW.conv_id
            AND NEW.id!=t.implementer_id AND NEW.id IS NOT t.reviewer_id)
        BEGIN SELECT RAISE(ABORT, 'task lines have exactly one implementer'); END""",
    """CREATE TRIGGER IF NOT EXISTS task_attachment_update BEFORE UPDATE OF conv_id,id,is_lead
        ON attachments WHEN EXISTS(SELECT 1 FROM task_reviews t WHERE t.conv_id=NEW.conv_id
            AND (NEW.is_lead!=0 OR (NEW.id!=t.implementer_id AND NEW.id IS NOT t.reviewer_id)))
        BEGIN SELECT RAISE(ABORT, 'task attachment identity is server-owned'); END""",
    """CREATE TRIGGER IF NOT EXISTS task_parent_update BEFORE UPDATE OF parent_id ON conversations
        WHEN EXISTS(SELECT 1 FROM task_reviews t WHERE t.conv_id=NEW.id AND t.root_id IS NOT NEW.parent_id)
        BEGIN SELECT RAISE(ABORT, 'task parent is immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS delete_task_reviews AFTER DELETE ON conversations
        BEGIN DELETE FROM task_reviews WHERE conv_id=OLD.id OR root_id=OLD.id; END""",
]

# Preserve the original constrained column as migration history. A one-time copy
# widens the public status constraint without rebuilding a table referenced by
# staffing triggers. The marker prevents a restart from restoring stale state.
MIGRATIONS += [
    "ALTER TABLE task_reviews RENAME COLUMN status TO initial_status",
    "ALTER TABLE task_reviews ADD COLUMN status TEXT NOT NULL DEFAULT 'implementing' "
    "CHECK(status IN ('implementing','in_review','approved','done','blocked'))",
    "CREATE TABLE IF NOT EXISTS orchestrator_state_migrations(name TEXT PRIMARY KEY)",
    "UPDATE task_reviews SET status=initial_status WHERE NOT EXISTS "
    "(SELECT 1 FROM orchestrator_state_migrations WHERE name='blocked-status')",
    "INSERT OR IGNORE INTO orchestrator_state_migrations VALUES('blocked-status')",
    "ALTER TABLE task_reviews ADD COLUMN stall_stage INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE task_reviews ADD COLUMN stall_notice_id INTEGER",
    "ALTER TABLE task_reviews ADD COLUMN reviewer_restarts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE task_reviews ADD COLUMN repositories TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE task_reviews ADD COLUMN blocked_at REAL",
    "ALTER TABLE task_reviews ADD COLUMN settled_at REAL",
    "ALTER TABLE task_reviews ADD COLUMN reopen_noticed INTEGER NOT NULL DEFAULT 0",
    "UPDATE task_reviews SET settled_at=CAST(strftime('%s','now') AS REAL) "
    "WHERE status IN ('approved','done') AND settled_at IS NULL",
    # Task processes are named impl-<tag>/review-<tag>; the preset they run is recorded apart
    # from the handle so cards and staffing still show it.
    "ALTER TABLE task_reviews ADD COLUMN tag TEXT",
    "ALTER TABLE attachments ADD COLUMN preset TEXT",
]
