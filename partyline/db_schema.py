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
    # Parent/child lines and a human-appointed lead per line. Machines are
    # scoped to their home line plus descendants of a live lead row.
    "ALTER TABLE conversations ADD COLUMN parent_id TEXT",
    "ALTER TABLE attachments ADD COLUMN is_lead INTEGER NOT NULL DEFAULT 0",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_attachments_one_lead "
    "ON attachments(conv_id) WHERE is_lead=1",
    "ALTER TABLE messages ADD COLUMN source_attachment_id TEXT",
    "ALTER TABLE messages ADD COLUMN source_conv_id TEXT",
    # audience_attachment_id: set on a cross-line relay copy or a return-path
    # notice, which exists for exactly one process on its line. Humans read
    # every message on a line; other processes never see a copy that is not
    # theirs, so cross-line traffic costs no one else's context.
    "ALTER TABLE messages ADD COLUMN audience_attachment_id TEXT",
    # goal: what the line's manager is seeing through; rides the manager's digest.
    "ALTER TABLE conversations ADD COLUMN goal TEXT NOT NULL DEFAULT ''",
    # cwd: where a line works; a child line is born in its own git worktree.
    "ALTER TABLE conversations ADD COLUMN cwd TEXT",
    # Child-to-parent reports. Created here rather than on first use: running
    # `executescript` per request issued an implicit COMMIT on the shared
    # connection and invalidated cursors another thread was still reading,
    # which surfaced as `InterfaceError: bad parameter or other API misuse`
    # under concurrent posts.
    """CREATE TABLE IF NOT EXISTS line_reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_conv_id TEXT NOT NULL,
        child_conv_id TEXT NOT NULL,
        author TEXT NOT NULL,
        author_attachment_id TEXT,
        body TEXT NOT NULL,
        notify INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 1,
        notified_at REAL,
        acknowledged_at REAL,
        created_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_line_reports_parent "
    "ON line_reports(parent_conv_id, id)",
    # One unacknowledged notify per child: a later escalation coalesces into
    # that row rather than stacking a second wake.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_line_reports_one_pending_notify "
    "ON line_reports(parent_conv_id, child_conv_id) "
    "WHERE notify=1 AND acknowledged_at IS NULL",
    # For a database that already ran the pre-migration bootstrap.
    "ALTER TABLE line_reports ADD COLUMN revision INTEGER NOT NULL DEFAULT 1",
    # `notified_at` separates "stored" from "the manager was actually told".
    # Without it, a notify with no lead appointed left a pending row that the
    # unique index then used to suppress every later wake, muting that child
    # for good.
    "ALTER TABLE line_reports ADD COLUMN notified_at REAL",
    # `notifying_at` is the in-flight claim on the one wake this row is owed.
    # Without it, concurrent escalations all read `notified_at IS NULL` while
    # the first wake was still being delivered, and each woke the manager.
    "ALTER TABLE line_reports ADD COLUMN notifying_at REAL",
    # Claims existed before hierarchy; normal startup now owns their schema too.
    """CREATE TABLE IF NOT EXISTS claims(
      id TEXT PRIMARY KEY, conv_id TEXT NOT NULL, owner TEXT NOT NULL,
      paths TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_claims_conv ON claims(conv_id, expires_at)",
    # One tree, one root manager, one monitor. The singleton check is what
    # makes "at most one pending wake" a property of the schema rather than of
    # whichever process happens to be ticking.
    """CREATE TABLE IF NOT EXISTS lead_heartbeat(
      singleton INTEGER PRIMARY KEY CHECK(singleton=1),
      conv_id TEXT NOT NULL,
      attachment_id TEXT NOT NULL,
      interval_seconds REAL NOT NULL,
      goal TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1,
      next_due_at REAL NOT NULL,
      pending_message_id INTEGER,
      generation INTEGER NOT NULL DEFAULT 1,
      created_at REAL NOT NULL
    )""",
    "ALTER TABLE lead_heartbeat ADD COLUMN generation INTEGER NOT NULL DEFAULT 1",
    # The delta the monitor reports, and what lets it stay quiet. `since_id` is
    # the message boundary already reported; `snapshot_hash` is the digest of
    # the last posted snapshot, so an identical one can be skipped rather than
    # spending the lead's turn on "nothing changed" — the failure that made the
    # first heartbeat useless overnight. `quiet_wakes` counts those skips and is
    # deliberately *not* part of the hash: a counter that changes every skip
    # would guarantee a changed digest and defeat the whole mechanism.
    "ALTER TABLE lead_heartbeat ADD COLUMN since_id INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE lead_heartbeat ADD COLUMN pending_since_id INTEGER",
    "ALTER TABLE lead_heartbeat ADD COLUMN snapshot_hash TEXT",
    "ALTER TABLE lead_heartbeat ADD COLUMN quiet_wakes INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE lead_heartbeat ADD COLUMN quiet_if_unchanged INTEGER NOT NULL DEFAULT 1",
    # The task board was created on first use by `tasks.py`. The heartbeat
    # snapshot reads it on every tick, including on an instance where nobody
    # has touched a task yet, so it belongs in the migration history like every
    # other table — and `docs/lessons.md` already records what running
    # `executescript` per request does to a shared connection.
    """CREATE TABLE IF NOT EXISTS tasks(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      conv_id TEXT NOT NULL,
      body TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done')),
      owner TEXT,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tasks_conv ON tasks(conv_id, status, id)",
    # Process traits on attach presets. Append-only; omitted writes use these
    # defaults so old clients stay compatible.
    "ALTER TABLE presets ADD COLUMN reads_images INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE presets ADD COLUMN can_manage INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE presets ADD COLUMN implements INTEGER NOT NULL DEFAULT 1",
]
