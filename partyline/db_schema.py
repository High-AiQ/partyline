"""The SQLite schema and its append-only migration history.

Split from `db.py` so schema changes land here as idempotent ``MIGRATIONS``
entries without growing the query module past its line cap. Never edit an
already-applied entry; append a new one.
"""

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

MIGRATIONS = [
    # cli_session: optional process session id, for adapters that support resume
    "ALTER TABLE attachments ADD COLUMN cli_session TEXT",
    # topic: free-text line topic, relayed to agents in briefings and digests
    "ALTER TABLE conversations ADD COLUMN topic TEXT NOT NULL DEFAULT ''",
    # archived_at: when a line was archived, NULL while it is live. Archiving
    # hides a line and stops its processes; the history stays until a purge.
    "ALTER TABLE conversations ADD COLUMN archived_at REAL",
    # A deliberately singleton restart intent. It is saved before shutdown and
    # only consumed after the requesting line accepts reattachment on startup.
    """CREATE TABLE IF NOT EXISTS restart_plan(
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        conversation_id TEXT NOT NULL,
        token TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'offer',
        claim_owner TEXT,
        claim_until REAL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        attachment_ids TEXT NOT NULL,
        debrief TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
    # A plan token binds a browser's accept click to the exact offer it saw.
    # Pre-token plans were never offered by a server route, so discard them.
    "ALTER TABLE restart_plan ADD COLUMN token TEXT",
    "DELETE FROM restart_plan WHERE token IS NULL",
    # Cockpit plans are trusted, hands-off recovery; ordinary UI plans remain
    # manual offers. Existing plans must keep the safe manual behaviour.
    "ALTER TABLE restart_plan ADD COLUMN mode TEXT NOT NULL DEFAULT 'offer'",
    # A lease prevents two server lifespans from resuming the same automatic
    # plan. Nullable values mean no owner currently holds the plan.
    "ALTER TABLE restart_plan ADD COLUMN claim_owner TEXT",
    "ALTER TABLE restart_plan ADD COLUMN claim_until REAL",
    # A failed continuation may be retried once, but never replayed forever.
    "ALTER TABLE restart_plan ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0",
    # A retiring server can finish adapter shutdown after its replacement has
    # already resumed the same attachment. Lifecycle writes are conditional on
    # this per-activation owner so the old generation cannot clobber the new.
    "ALTER TABLE attachments ADD COLUMN runtime_owner TEXT",
    # Human accounts. Handles share the mention namespace with attachment
    # names, so uniqueness is enforced case-insensitively, matching how
    # mentions are routed. Emails are stored lowercased.
    """CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        handle TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(lower(email))",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_handle ON users(lower(handle))",
    # One JWT signing secret per instance, generated on first run. Two
    # instances (cockpit and workbench) have separate databases, so they get
    # distinct secrets for free; there is deliberately no env fallback.
    """CREATE TABLE IF NOT EXISTS auth_secret(
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        secret TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
    # api_token: the per-attachment machine credential, minted once and stable
    # across activations and resumes, injected as PARTYLINE_TOKEN.
    "ALTER TABLE attachments ADD COLUMN api_token TEXT",
    # report_token: the plan's failure-report capability. The restart watchdog
    # runs outside any attachment or user session, so it authenticates its one
    # allowed act — posting a failure notice to the planned line — with a
    # credential minted for exactly that, the same shape as the hooks token.
    "ALTER TABLE restart_plan ADD COLUMN report_token TEXT",
    # Digests a CLI proved it skipped have already advanced last_seen. Keep
    # their exact message ids until a later real turn boundary can replay them.
    """CREATE TABLE IF NOT EXISTS queued_delivery_messages(
        attachment_id TEXT NOT NULL,
        message_id INTEGER NOT NULL,
        PRIMARY KEY (attachment_id, message_id)
    )""",
    # A human may nominate one receipt-capable process per line to hear every
    # non-system message. The partial unique index is the structural guard
    # against two leads waking each other forever.
    "ALTER TABLE attachments ADD COLUMN follow INTEGER NOT NULL DEFAULT 0",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_attachments_follow_lead "
    "ON attachments(conv_id) WHERE follow=1",
    # Transcript speech recovered by a resume may be posted long after its
    # position in the vendor file. Tie that exact chat message to the record
    # fingerprint so a later resume does not mistake delivery order for
    # transcript order and relay it again.
    """CREATE TABLE IF NOT EXISTS transcript_delivery_records(
        attachment_id TEXT NOT NULL,
        message_id INTEGER NOT NULL,
        fingerprint BLOB NOT NULL,
        PRIMARY KEY (attachment_id, message_id)
    )""",
    # Retire the line-follower feature. The index must go first because SQLite
    # refuses to drop a column referenced by an index.
    "DROP INDEX IF EXISTS idx_attachments_follow_lead",
    "ALTER TABLE attachments DROP COLUMN follow",
]
