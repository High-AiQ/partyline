"""How a docker grant is served: ``managed`` (the policy proxy) or ``unrestricted`` (raw relay)."""

MIGRATIONS = [
    "ALTER TABLE conversation_write_grants ADD COLUMN docker_mode TEXT NOT NULL DEFAULT 'managed'",
]
