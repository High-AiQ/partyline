"""Original table definitions; subsequent changes belong in db_schema.MIGRATIONS."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conv_id TEXT NOT NULL,
  sender TEXT NOT NULL,
  sender_type TEXT NOT NULL,          -- human | agent | system
  body TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id);
CREATE TABLE IF NOT EXISTS attachments(
  id TEXT PRIMARY KEY,                -- also used as the agent session UUID
  conv_id TEXT NOT NULL,
  name TEXT NOT NULL,
  adapter TEXT NOT NULL,              -- adapter identifier
  command TEXT NOT NULL,              -- JSON argv list
  cwd TEXT NOT NULL,
  status TEXT NOT NULL,               -- starting | running | exited | detached
  runtime_owner TEXT,                 -- one adapter activation; rejects stale callbacks
  last_seen INTEGER NOT NULL DEFAULT 0,  -- id of last message delivered to this agent
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS presets(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  name TEXT NOT NULL,                 -- default @handle
  adapter TEXT NOT NULL,
  command TEXT NOT NULL,              -- shell-style string (no cwd: that's per-attach)
  created_at REAL NOT NULL
);
"""
