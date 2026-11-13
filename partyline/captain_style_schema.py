"""Retire the manager-tree captain style: every line is an orchestrator line."""

# Retire the old root-only style constraint and update the persistent column default.
# The schema rewrite is idempotent; RESET reloads it in this connection as well.
MIGRATIONS = [
    "DROP TRIGGER IF EXISTS orchestrator_root_insert",
    "DROP TRIGGER IF EXISTS orchestrator_root_update",
    "UPDATE conversations SET captain_mode='orchestrator' WHERE captain_mode!='orchestrator'",
    "PRAGMA writable_schema=ON",
    "UPDATE sqlite_schema SET sql=replace(sql, \"DEFAULT 'manager_tree'\", "
    "\"DEFAULT 'orchestrator'\") WHERE type='table' AND name='conversations'",
    "PRAGMA writable_schema=RESET",
    # Reserve the historic names so the old CREATE IF NOT EXISTS entries do not
    # briefly restore their root-only constraint on every subsequent startup.
    "CREATE TRIGGER IF NOT EXISTS orchestrator_root_insert BEFORE INSERT ON conversations "
    "WHEN 0 BEGIN SELECT 1; END",
    "CREATE TRIGGER IF NOT EXISTS orchestrator_root_update BEFORE UPDATE ON conversations "
    "WHEN 0 BEGIN SELECT 1; END",
]
