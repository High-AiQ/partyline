"""An explicit auto-compact threshold per preset (§2.13 defaults).

Split from `db_schema` the way the other feature schemas were: an append-only
idempotent entry. The unit is the CLI's own native one — tokens — because
that is what every documented knob takes: Claude Code's
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` is a plain token count and Codex's
`model_auto_compact_token_limit` is a token count. 0 means unset, so the
CLI's own tuned default applies, as it does today.
"""

MIGRATIONS = [
    # Cheap workers low, other workers mid, captains at the maximum: the
    # threshold lives on the preset, so the choice is visible and reviewable
    # rather than a per-install default nobody can see.
    "ALTER TABLE presets ADD COLUMN auto_compact_tokens INTEGER NOT NULL DEFAULT 0",
]
