# Fleet resource budget

Partyline admits process starts across the whole instance, including child lines.
It reserves each starting or running attachment's configured memory reservation and
admits new processes only when both the process count and sum of reservations fit the
current settings. The per-process memory cap remains separate. Restart-plan
members that were live at restart are grandfathered and continue to count. This
is reservation accounting, not a claim that
reported RSS equals actual memory or a hard aggregate kernel limit.

## Defaults and settings

People edit the instance settings in **Settings → resource budget**. Unset values
are computed from host resources at runtime and returned by `GET /api/resources`
and `GET /api/settings/resources`:

- Maximum live processes is `max(4, min(32, CPU count × 2))`. The count is
  capped at 32; memory admission remains an independent limit.
- Memory reserve is `max(2 GiB, 10% of host RAM)`, capped when necessary so at
  least one default reservation fits.
- Default process memory cap is `min(4 GiB, max(2 GiB, host RAM / 8))`, capped
  by the existing per-process ceiling on smaller hosts. An attachment's
  explicit memory limit overrides it.
- Default memory reservation is `min(process cap, 1 GiB)`. It is the amount
  counted for admission; each process still receives its full configured cap.
- Memory budget is host RAM minus reserve.

The table uses generic nominal host sizes and representative amounts of RAM
reported to the operating system. With the default 1 GiB reservation, it shows
the approximate memory admission ceiling. The process setting and CPU default
can lower the effective count further.

| Host RAM | Default cap | Default reserve | Memory budget | Processes allowed by memory |
| --- | ---: | ---: | ---: | ---: |
| 8 GB (7 GiB detected) | 2 GiB | 2 GiB | 5 GiB | 5 |
| 16 GB (15 GiB detected) | 2 GiB | 2 GiB | 13 GiB | 13 |
| 32 GB (30 GiB detected) | 3.75 GiB | 3 GiB | 27 GiB | 27 |
| 64 GB (60 GiB detected) | 4 GiB | 6 GiB | 54 GiB | 54 |
| 128 GB (120 GiB detected) | 4 GiB | 12 GiB | 108 GiB | 108 |

Settings accept 4–32 processes, a reserve from zero through 90% of RAM, a
default cap from 256 MiB through the existing per-process ceiling, and a
reservation from 256 MiB through the default cap. A saved change must leave at
least one reservation inside the memory budget. The per-process cap ceiling is
at most 8 GiB and 75% of host RAM. Existing attachment memory settings remain
available through the per-attachment memory endpoint. An unset cap is resolved
from the global default and saved on the attachment at admission, so later
edits to the cap do not change a live process. People can change the saved cap
while it is stopped. The advisory early-warning sampler privately tells a live
process when it approaches its cap — save work, find what is growing, or request
more with a reason — and sends a private copy to the nearest live captain on its
line or an ancestor line. People read both copies on those lines. Going over
the cap is told once more, even inside the ten-minute cooldown. The warning
does not stop the process or change its cap.

On Linux the cap is a soft budget, not a cliff: the sampler warns at the warning
percentage and again once usage passes the cap, but nothing slows or stops the
process there. The scope's only kernel limit is `MemoryMax` at an emergency
backstop above the cap — 1.5× the cap or the cap plus 1 GiB, whichever is
larger, within 3/4 of host RAM — that exists so one runaway cannot take the host
down. A saved budget restored onto a smaller host can be at or above this
backstop. Linux warnings, re-arming and the second notice use the smaller of
budget and backstop, while usage displays and memory requests retain the saved
budget. Both private warning copies explain when the host clamps the backstop.
`MemoryHigh` throttling was tried and rejected: with swap disabled the
kernel cannot reclaim a CLI's anonymous memory, so a process past `MemoryHigh`
crawls instead of saving its work. Fast growth can still reach the backstop
before anyone acts. Crossing it OOM-kills that process scope; Partyline records an incident with reason `oom`, posts a notice, and
leaves the process stopped. Admission still counts reservations, not backstops,
so the backstops together may exceed RAM. On Windows (Job Object) the cap is a
hard limit; on macOS, `RLIMIT_AS` is best-effort
address-space limiting and does not guarantee resident-memory use. A person or
captain can change an attachment's cap for its next activation with
`PUT /api/attachments/{id}/memory`; a process cannot grant itself more. The
ceiling is `min(8 GiB, 3/4 of host RAM)`. A process or captain asks for more with
`POST /api/attachments/{id}/memory-requests`; approval restarts the process with
the new cap.

### Can the Linux backstop kill for page cache?

Partyline's Linux backstop is systemd `MemoryMax`, which becomes the scope's
cgroup-v2 `memory.max`; there is no separate Partyline supervisor that kills a
process when its sampled usage crosses a number. `OOMPolicy=stop` only decides
what systemd does after the kernel reports a cgroup OOM. Server and process scopes
also set `MemorySwapMax=0`.

`memory.max` charges file cache to the scope, but reaching it first makes the
kernel reclaim memory. Clean, unmapped file pages are normally dropped and
streaming a large file therefore should not cause an OOM kill merely because its
bytes passed through the page cache. The kernel OOM-kills only when reclaim cannot
keep usage below the limit. That can happen because anonymous memory, kernel
memory, or tmpfs/shared memory is genuinely too large, because dirty, mapped,
locked, or otherwise unreclaimable pages cannot be discarded quickly enough, or
because rapid allocation outpaces reclaim. With swap disabled, anonymous and
tmpfs pages cannot be swapped out either. An OOM kill while a process streamed
multi-GB weights is therefore not evidence that reclaimable cache alone caused
the kill; inspect the scope's `memory.stat`, `memory.events`, recorded peak, and
process RSS to identify the non-reclaimable residue and any reclaim failure. This
investigation does not change enforcement.

Admission counts `starting` as live. The check and row reservation share the
runtime ownership lock, so parallel starts cannot both take the same last slot.
The gate covers new attaches, fresh starts, and explicit resumes. Automatic
restart plans and accepted reattach offers restore every planned process that
was live at restart, even when the fleet exceeds configured limits. A refusal is
HTTP 409 and names the full limit. Refused
new starts create no attachment row; refused fresh starts preserve the old row;
refused resumes stay stopped. A confirmed exit or detach frees the reservation;
an unconfirmed live process continues to count.

On restart, stale pre-restart live rows in the saved plan are marked stopped
before reattachment begins. Every plan member that was live at restart is
grandfathered through admission, even when that takes current usage above a
configured process or memory limit. These processes still count against the
budget. New attaches, fresh starts, and explicit resumes of long-stopped
processes remain blocked until usage falls below the limit or a person raises
it; no planned live process is stopped by resource-budget admission.

## Visibility

The top bar shows fleet-wide process usage and real host memory — used over
total, such as `41/64 GB`. Its popover shows the host bar (partyline's share
and everything else's, against total RAM), what is still available, partyline's
own use split into the server and the processes it runs (each process's whole
CLI tree), the lines whose families use the most memory, the admission
reservation, the line with the most live processes, and a blocked-admission
notice when the fleet is at or above a limit. The sum of per-process caps is
deliberately not shown: caps are ceilings, not usage, and their sum routinely
exceeds the RAM the host has. Over-limit usage stays visible as real numbers
and turns the indicator red. The root captain briefing includes a capacity
line. The authenticated `/api/resources` endpoint is readable by machines as
well as people, and serves the first load.

Open tabs do not poll. On each memory-sampler tick the server computes the
snapshot once and pushes it as a `resources` socket event — but only when
something moved (host, partyline or temp use by 64 MB or 0.5% of RAM, or the
live-process count, the process limit or the reserve changed), plus one
heartbeat every 60 s while quiet. With no tab open nothing is computed. A tab
loads once on mount and refreshes (debounced) on attachment and line-live
events; the pushed frame carries the same body as `GET /api/resources`.

The UI refreshes its resource snapshot on attachment, removal, and line-live
wire events. `LineLiveEvent` is broadcast to every open socket, so a browser on
one line also sees changes on another; refreshes are debounced by 300 ms, and
the snapshot is polled every five seconds while the tab is visible, because
real usage moves without any event. `/api/resources` carries the same numbers:
`host_used_bytes`, `host_available_bytes` (Linux `MemAvailable`, Windows
`GlobalMemoryStatusEx`, null elsewhere), `partyline_server_bytes` (the server's
cgroup `memory.current`, else its RSS), `partyline_processes_bytes` (the
sampler's latest reading per live process), `partyline_used_bytes`,
`other_used_bytes`, `top_lines` and `sampled_at`.

## Enforcement and limits

| Control | Status |
| --- | --- |
| Process-count admission across all lines | Enforced by Partyline on Linux, macOS, and Windows |
| Sum of declared memory reservations against host RAM minus reserve | Enforced by Partyline admission on Linux, macOS, and Windows |
| Real available memory minus reserve against the new process's reservation | Enforced by Partyline admission where the host reports available memory (Linux, Windows); the refusal names the real numbers |
| Per-process memory cap | Linux cgroup scope and Windows Job Object are kernel enforced; macOS `RLIMIT_AS` is best-effort address-space limiting and does not guarantee resident-memory use |
| Process overview RSS | Advisory visibility only; best effort across supported platforms |
| Early memory warning | Advisory; one server sampler checks live process trees every five seconds and warns at the people-configured threshold (default 80%), re-arming below 65% and rate-limiting each process to one notice per ten minutes; the notice names the five largest command groups under the process (for example `12× chrome`, with its summed RSS and the largest member's pid), so browser children are visible as one line |
| Resource snapshots and captain briefing | Advisory visibility; they describe current reservations and do not reserve a slot |

Linux warning samples prefer the process scope's cgroup-v2 `memory.current`,
`memory.peak`, and `memory.stat`. When `anon` and `file` are available, the
warning threshold, re-arming, cap comparison, and displayed percentage use the
at-risk working set: `max(anon, memory.current - (file - shmem))`. Since `file`
includes both active and inactive cache and includes `shmem`, this subtracts all
file-backed pages the kernel can drop while retaining anonymous, kernel, slab,
and shared memory. Recently read weights on `active_file` therefore do not cause
a warning merely by passing through page cache. Older kernels whose `memory.stat`
lacks `anon` or `file` retain the previous fallback, `memory.current -
inactive_file`.

The raw total remains visible as `raw_bytes`; additive `anon_bytes`,
`kernel_bytes`, and `file_bytes` fields carry the raw breakdown, with total file
cache (active plus inactive) rather than only its inactive portion. A warning
reports the raw total as anonymous plus kernel and file cache, and still names
the largest descendant command groups so a captain can distinguish real process
growth from cache.

On macOS and Windows, Partyline sums RSS across the observed process tree from a
process listing. These readings are estimates: child creation and exit can race a
sample, RSS may count shared pages more than once, and inaccessible or short-lived
children may be missed. Warnings never stop a process or change its cap.

The global accounting is portable and follows declared reservations. In particular,
macOS admission is still enforced even though its per-process kernel limit is
best-effort. A running process can use more resident memory than its cap on
platforms whose kernel limit does not enforce resident memory.

## Temp directories

Every attached process gets its own temp directory: at spawn, `TMPDIR`, `TMP`
and `TEMP` point at `<platform temp>/partyline/<instance>/<attachment id>`,
created with mode 0700. On Linux, when the platform temp directory is tmpfs
(RAM) and `/var/tmp` exists on a disk-backed filesystem, the base moves to
`/var/tmp` instead: tmpfs pages count against the process's memory budget
and the kernel cannot reclaim them, so a day of test runs could reach the
budget on files alone. The `PARTYLINE_TMP_BASE` pin still wins over
everything. Each level Partyline creates under that base (`partyline`, the
instance, the attachment) must be a real directory owned by the same user:
new ones are 0700, an existing one with group or other write is tightened to
0700, and a symlink or a foreign owner is refused with a clear error rather
than used (the base itself, `/var/tmp`, is never touched).

On the first start after the move, the old directories under
`<platform temp>/partyline/<instance>` are removed, since they were RAM. This
is skipped when the old and new roots are the same directory (a `/var/tmp`
that links to `/tmp`, compared by real path), and any directory a live process
of the same user still uses is kept: one that is a process's working directory,
or that a process names in `TMPDIR`, `TMP` or `TEMP` (read best-effort from
`/proc`), because background jobs outlive a restart. The `<instance>` segment is twelve hex of the database path —
several partyline instances share a host and a temp, and one instance's
reaper must never touch another's directories. The same id resumes into the
same directory, so a restart never loses it. Temp only — CLI state and
caches stay where the platform puts them. The directory sits inside the
fence's writable set on every backend: Linux's bubblewrap leaves everything
but the protected set writable, the macOS profile re-allows the temp
directories, and Windows scopes already used a per-attachment temp.

The directory is reaped only when the attachment ends: a person- or
captain-called close (`DELETE /api/attachments/<id>`), record removal, a line
archive, or a purge. The internal detaches — replace, restart, an approval
dropping a process — keep it. Every delete is guarded: the directory on disk
must be exactly `<base>/partyline/<id>`, so a symlink at either level is
refused, never followed out.

`POST /api/conversations/<root>/tmp/reap` — root captain or person only —
deletes leftover dirs in this instance's scope whose attachment row is gone
(crash leftovers) and reports the bytes freed. It never touches live,
detached or exited rows: all of them can resume; it never touches another
instance's scope, and never a name that is not an attachment id. Visibility
comes three ways: the captain rider carries a line like `(tmp: /var/tmp 13/104
GB · this line's processes 2.1 GB · top tmp: «line» 1.9 GB, …)` — the temp
mount's used and total bytes, the line's live processes' share, and the top
lines by temp use — `/api/resources` adds `tmp_total_bytes`,
`tmp_used_bytes` and `tmp_partyline_bytes`, and a memory warning whose
`memory.stat` shmem figure exceeds 256 MiB names the share and the largest
directory under that process's own temp dir when that dir is on tmpfs, and
otherwise says only that the shared memory comes from `/dev/shm`, `/tmp` or
in-memory files: deleting those files frees real memory, which a reclaim
cannot. The sentence is built once per warning actually sent, off the event
loop. One time-budgeted walk per few seconds
fills the mount totals and the per-id sizes together; riders and snapshots
read that cache, so a huge tree costs a partial answer, never a stalled
server. Before a warning fires, and only when the process's own temp directory is on
tmpfs (on disk they cost no memory), old `pytest-of-*/pytest-N` runs inside it
are reaped (older than 30 minutes, never
`pytest-current`), the sample is re-read, and only a still-over working set
is reported. Tests pin `PARTYLINE_TMP_BASE` to their sandbox and never
touch the real temp directories.

## Requesting a larger cap

A process, its captain, or a person can file `POST /api/attachments/{id}/memory-requests`
with `requested_limit` and a reason. A captain can approve within the configurable
captain ceiling (default twice the process cap, bounded by the host ceiling); a
person decides above it. Approve with `POST /api/memory-requests/{request_id}/approve`.
Approval stores the new cap and replaces the activation
through the normal resume path. The old admission lease is released first and the
replacement is grandfathered through admission. A process cannot approve the
request for its own cap. Only one memory request can be pending on a line at a
time; further requests receive HTTP 409 until it is approved or declined. The
warning threshold and captain ceiling are people-only settings in the resource
budget dialog.

## Task history retention

`auto_clean_task_history` is a global boolean preference, disabled by default.
Read or change it as a person with GET or PUT
`/api/settings/auto_clean_task_history`; PUT accepts `{"enabled": true}` or
`{"enabled": false}`. The Settings control belongs beside the resource budget.
Machine credentials cannot change it.

With retention enabled (the default), orchestrator task lines and review history
stay visible after shipping. Idle task processes detach once the approved/done SHA
is merged into the root checkout and the whole task worktree is clean and merged.
Only a person or the task's root captain may archive task lines.

Enabling auto-clean lets the server archive approved/done, merged task lines after
all processes are inactive, and remove their managed task, review and scratch
worktrees. The maintenance loop retries every 30 seconds and resumes after restart.
Unmerged, dirty, still-running or unverifiable work is retained. Archiving preserves
the transcript and structured task review record; permanent purge remains human-only.

Raw adapter attachments do not consume process slots or admission reservations by default. Set `counts_toward_total: true` when attaching a raw process through the API or MCP to include it; the flag cannot be changed on an existing attachment and has no UI control; other adapters always count and cannot set this option. Actual memory usage still includes every live process. The process overview lists all live processes and reports whether each counts.

## Resource lease probes

Before acquiring a named line resource, Partyline runs its configured probe off
the event loop, with a two-second timeout. Set `PARTYLINE_RESOURCE_PROBES` on
the server to a JSON object mapping resource names to command argument arrays,
for example `{"gpu":["nvidia-smi","-L"],"accelerator":["check-accelerator"]}`.
The default for `gpu` is `["nvidia-smi", "-L"]`; other names have no probe.
Set a name to `null` to disable its probe. Commands run directly without a shell.
A missing executable skips the probe. A nonzero exit, timeout, or empty stdout
refuses the acquisition with an instruction to check the resource and retry;
no new claim is queued. Queued claims are checked again before promotion and
remain queued until a later successful check. A probe is a point-in-time check,
not a guarantee that hardware remains healthy during a job.

Set `PARTYLINE_GPU_MAX_POWER_W` to a positive finite number of watts to also
check every GPU's configured power limit before acquiring or granting `gpu`.
Partyline runs `nvidia-smi --query-gpu=power.limit --format=csv,noheader,nounits`
read-only with the same timeout, even if the ordinary GPU probe is disabled.
An absent `nvidia-smi` skips this check; invalid settings, failed commands and
unparseable limits refuse acquisition. If any limit exceeds the maximum, a
person must lower it (for example with `nvidia-smi -pl`) and retry. Partyline
never changes hardware settings. Waiters remain queued until a healthy check.

After an unplanned stop, notices include persisted lease holders, resource names,
lines, and task notes before stale attachments are cleared. Queued claims are
not reported as held leases.

## Host kernel log

People and root captains can read recent kernel diagnostics through
`GET /api/host/kernel-log?boot=previous&lines=100`. `boot` accepts `previous`
(the default) or `current`; `lines` defaults to 100 and accepts 1–300. The
response is an array of redacted text lines, never stored by Partyline. The
server needs `journalctl` and permission to read the journal; add its service
user to `systemd-journal` when needed. Unavailable or timed-out journal access
returns 503. Redaction covers common credentials, MAC addresses and IP
addresses, but kernel messages may contain other sensitive information.

## Docker CLI container defaults

On Linux and macOS, each attached process receives a `docker` shim first on
PATH. For `docker run`, `docker create`, and their `docker container` forms,
when no `--memory` or `-m` is specified, it adds `--memory` and
`--memory-swap` equal to half the attachment's effective memory cap, with a
6 MiB floor (Docker's minimum). Set `PARTYLINE_DOCKER_MEMORY_FRACTION` on the
Partyline server to a number greater than zero and at most one to change the
fraction for newly started attachments. The shim resolves the real Docker CLI
from the remaining PATH, and fails clearly if none exists. Explicit memory
limits are left to the caller; other subcommands pass through unchanged.

This is a per-container default, not an aggregate limit: multiple containers
can exceed the attachment budget together, and an explicit memory or swap
option can override it. Docker containers are charged to the daemon, not the
attachment's scope. Absolute paths to Docker, changed PATHs, direct Docker socket
API calls and other clients bypass the shim. `docker compose` is passed through:
Compose creates containers through its own API calls, so compose services need
explicit memory limits in their configuration. Windows attachments do not get
the shim. This is a guardrail, not a security boundary.
