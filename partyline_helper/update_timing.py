"""One-shot update budgets shared by the helper supervisor and the server's abandonment deadline."""
ACK, QUIESCE, READY, EXIT = 10, 10, 10, 3
PARENT_STOP = 30
INSTALL = 120
RECONNECT = 120
ABORT = 10
ROLLBACK_STOP, ROLLBACK_INSTALL, ROLLBACK_START = 30, 60, 30
SUPERVISOR_BUDGET = PARENT_STOP + INSTALL + RECONNECT + ABORT + (
    ROLLBACK_STOP + ROLLBACK_INSTALL + ROLLBACK_START)
# Include ack, quiesce, supervisor startup, and a connection budget after rollback starts the old helper.
SERVER_DEADLINE = ACK + QUIESCE + READY + SUPERVISOR_BUDGET + RECONNECT + 30
