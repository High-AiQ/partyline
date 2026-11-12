"""Ordered feature migration groups appended after the original schema history."""

from .idempotency_schema import MIGRATIONS as IDEMPOTENCY
from .memory_schema import MIGRATIONS as MEMORY
from .compaction_schema import MIGRATIONS as COMPACTION
from .accept_history_schema import MIGRATIONS as ACCEPT_HISTORY
from .gates_schema import MIGRATIONS as GATES
from .notes_schema import MIGRATIONS as NOTES
from .scratch_schema import MIGRATIONS as SCRATCH
from .lease_schema import MIGRATIONS as LEASE
from .auto_compact_schema import MIGRATIONS as AUTO_COMPACT
from .docker_mode_schema import MIGRATIONS as DOCKER_MODE
from .bridge_schema import MIGRATIONS as BRIDGE
from .retirement_schema import MIGRATIONS as RETIREMENT
from .captain_handover_schema import MIGRATIONS as HANDOVER
from .local_tools_schema import MIGRATIONS as LOCAL_TOOLS_AUDIT
from .screen_audit_schema import MIGRATIONS as SCREEN_AUDIT
from .screen_schema import MIGRATIONS as SCREEN
from .screen_account_schema import MIGRATIONS as SCREEN_ACCOUNT
from .screen_grant_schema import MIGRATIONS as SCREEN_GRANTS
from .write_set_schema import MIGRATIONS as WRITE_SET
from .orchestrator_schema import MIGRATIONS as ORCHESTRATOR
from .asr_schema import MIGRATIONS as ASR
from .captain_idle_schema import MIGRATIONS as CAPTAIN_IDLE

MIGRATIONS = (MEMORY + IDEMPOTENCY + NOTES + COMPACTION + ACCEPT_HISTORY + SCRATCH + LEASE
                  + GATES + AUTO_COMPACT + DOCKER_MODE + BRIDGE + RETIREMENT + ORCHESTRATOR + HANDOVER)
MIGRATIONS += (["ALTER TABLE attachments ADD COLUMN is_successor INTEGER NOT NULL DEFAULT 0"] + SCREEN
                  + ASR + SCREEN_AUDIT + LOCAL_TOOLS_AUDIT + SCREEN_ACCOUNT)
MIGRATIONS += SCREEN_GRANTS + WRITE_SET + CAPTAIN_IDLE
