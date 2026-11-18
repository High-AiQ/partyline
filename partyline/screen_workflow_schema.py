"""Idempotent migrations for project approvals and line-scoped workflow audits."""

WORKFLOW_MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS screen_workflow_approvals(
        project TEXT NOT NULL,
        checkout TEXT NOT NULL,
        path TEXT NOT NULL,
        revision TEXT NOT NULL,
        stamp TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        approved_at REAL NOT NULL,
        PRIMARY KEY(project,checkout,path))""",
    """CREATE TABLE IF NOT EXISTS screen_workflow_runs(
        id TEXT PRIMARY KEY,
        conv_id TEXT NOT NULL,
        attachment_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        actor_user_id INTEGER,
        owner_id INTEGER NOT NULL,
        client_key_hash TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        project TEXT NOT NULL,
        path TEXT NOT NULL,
        workflow TEXT NOT NULL,
        revision TEXT NOT NULL,
        grant_id TEXT NOT NULL,
        started_at REAL NOT NULL,
        finished_at REAL,
        state TEXT NOT NULL,
        total_steps INTEGER NOT NULL,
        verified_steps INTEGER NOT NULL DEFAULT 0,
        current_step TEXT,
        outcome TEXT,
        UNIQUE(attachment_id,client_key_hash))""",
    """CREATE TABLE IF NOT EXISTS screen_workflow_events(
        id INTEGER PRIMARY KEY,
        run_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        step TEXT,
        source TEXT,
        event TEXT NOT NULL,
        request_id TEXT,
        actor_user_id INTEGER,
        outcome TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_screen_workflow_events_run ON screen_workflow_events(run_id,id)",
    "CREATE INDEX IF NOT EXISTS idx_screen_workflow_runs_line ON screen_workflow_runs(conv_id)",
    """CREATE TRIGGER IF NOT EXISTS delete_screen_workflow_runs AFTER DELETE ON conversations
        BEGIN DELETE FROM screen_workflow_runs WHERE conv_id=OLD.id; END""",
    """CREATE TRIGGER IF NOT EXISTS delete_screen_workflow_events AFTER DELETE ON screen_workflow_runs
        BEGIN DELETE FROM screen_workflow_events WHERE run_id=OLD.id; END""",
]


WORKFLOW_RESUME_MIGRATIONS = [
    "ALTER TABLE screen_workflow_runs ADD COLUMN plan_hash TEXT",
    "ALTER TABLE screen_workflow_runs ADD COLUMN window_hash TEXT",
    "ALTER TABLE screen_workflow_runs ADD COLUMN input_pending INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE screen_workflow_events ADD COLUMN step_index INTEGER",
    "ALTER TABLE screen_workflow_runs ADD COLUMN resume_attachment_id TEXT",
    "ALTER TABLE screen_workflow_events ADD COLUMN actor_attachment_id TEXT",
]
