#!/usr/bin/env bash
#
# Replace one exact partyline server generation with a freshly deployed one.
#
# This exists as a file rather than as shell inlined into a systemd unit, and
# that is the entire point. The previous attempt embedded this logic in
# `ExecStart=/bin/bash -c "..."`, which put the quoting through three layers —
# systemd, then bash, then awk. `awk '{print $22}'` collapsed into
# `{print \130014102}`: the shell had already eaten awk's field reference and
# replaced it with the start-tick argument. awk errored, the generation read
# came back empty, and the guard correctly refused to kill a process it could
# not identify. The safety check worked; its own input had been mangled.
#
# One layer of quoting, a file anyone can read, and a script that can be tested
# without arming anything.
#
#   restart_server.sh <old-pid> <old-start-tick> <server-binary> <log-file>
#
# Exit codes are distinct so a failure says which check refused, not merely
# that something went wrong:
#   20  the old process is already gone       21  it is a different generation
#   22  bad arguments                          23  it would not exit in time
set -euo pipefail

readonly EXIT_ALREADY_GONE=20
readonly EXIT_WRONG_GENERATION=21
readonly EXIT_BAD_ARGUMENTS=22
readonly EXIT_WOULD_NOT_EXIT=23
readonly WAIT_SECONDS=60

if [ "$#" -ne 4 ]; then
  echo "usage: $0 <old-pid> <old-start-tick> <server-binary> <log-file>" >&2
  exit "$EXIT_BAD_ARGUMENTS"
fi

old_pid=$1
old_start=$2
server=$3
logfile=$4

# Field 22 of /proc/<pid>/stat is the process start time in clock ticks. A pid
# alone is a name the kernel reuses; pid plus start time is a generation, and
# only a generation is safe to signal.
generation_of() {
  local pid=$1
  [ -r "/proc/$pid/stat" ] || return 1
  awk '{print $22}' "/proc/$pid/stat" 2>/dev/null
}

actual_start=$(generation_of "$old_pid") || {
  echo "old pid $old_pid disappeared before the restart" >&2
  exit "$EXIT_ALREADY_GONE"
}

if [ -z "$actual_start" ]; then
  # Distinct from a mismatch: an unreadable generation is a broken check, not
  # evidence about the process. Conflating the two is what cost ten hours.
  echo "could not read the generation of pid $old_pid" >&2
  exit "$EXIT_WRONG_GENERATION"
fi

if [ "$actual_start" != "$old_start" ]; then
  echo "pid $old_pid is generation $actual_start, expected $old_start" >&2
  exit "$EXIT_WRONG_GENERATION"
fi

kill "$old_pid"

# Wait for that exact generation to be gone. A free port is not an exited
# process, and the two differed by long enough to matter: an old server's
# teardown once overwrote a new server's attachment rows.
deadline=$((WAIT_SECONDS * 5))
while [ "$deadline" -gt 0 ]; do
  current=$(generation_of "$old_pid" || true)
  if [ -z "$current" ] || [ "$current" != "$old_start" ]; then
    break
  fi
  deadline=$((deadline - 1))
  sleep 0.2
done

if [ "$deadline" -le 0 ]; then
  echo "pid $old_pid did not exit within ${WAIT_SECONDS}s" >&2
  exit "$EXIT_WOULD_NOT_EXIT"
fi

echo "--- cockpit restarted $(date -Is) ---" >> "$logfile"
exec "$server" >> "$logfile" 2>&1
