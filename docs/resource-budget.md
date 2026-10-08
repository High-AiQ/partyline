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
line or an ancestor line. People read both copies on those lines. The warning
does not stop the process or change its cap.

The cap is the per-process kernel kill threshold; exceeding it can OOM-kill
that process scope. Partyline records an incident with reason `oom`, posts a
notice, and leaves the process stopped. On Linux (cgroup scope) and Windows
(Job Object), the cap is kernel-enforced; on macOS, `RLIMIT_AS` is best-effort
address-space limiting and does not guarantee resident-memory use. A person or
captain can change an attachment's cap for its next activation with
`PUT /api/attachments/{id}/memory`; a process cannot grant itself more. The
ceiling is `min(8 GiB, 3/4 of host RAM)`. A process or captain asks for more with
`POST /api/attachments/{id}/memory-requests`; approval restarts the process with
the new cap.

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

The top bar shows fleet-wide process usage. Its popover includes reserved memory
and the sum of per-process caps,
the line with the most live processes, and a blocked-admission notice when the
fleet is at or above a limit. Over-limit usage stays visible as real numbers
and turns the indicator red. The root captain briefing includes a capacity
line. The authenticated `/api/resources` endpoint is readable by machines as
well as people.

The UI refreshes its resource snapshot on attachment, removal, and line-live
wire events. `LineLiveEvent` is broadcast to every open socket, so a browser on
one line also sees changes on another; refreshes are debounced by 300 ms.

## Enforcement and limits

| Control | Status |
| --- | --- |
| Process-count admission across all lines | Enforced by Partyline on Linux, macOS, and Windows |
| Sum of declared memory reservations against host RAM minus reserve | Enforced by Partyline admission on Linux, macOS, and Windows |
| Per-process memory cap | Linux cgroup scope and Windows Job Object are kernel enforced; macOS `RLIMIT_AS` is best-effort address-space limiting and does not guarantee resident-memory use |
| Process overview RSS | Advisory visibility only; best effort across supported platforms |
| Early memory warning | Advisory; one server sampler checks live process trees every five seconds and warns at the people-configured threshold (default 80%), re-arming below 65% and rate-limiting each process to one notice per ten minutes |
| Resource snapshots and captain briefing | Advisory visibility; they describe current reservations and do not reserve a slot |

Linux warning samples prefer the process scope's cgroup-v2 `memory.current` and
`memory.peak`. On macOS and Windows, Partyline sums RSS across the observed process
tree from a process listing. These readings are estimates: child creation and exit
can race a sample, RSS may count shared pages more than once, and inaccessible or
short-lived children may be missed. Warnings never stop a process or change its cap.

The global accounting is portable and follows declared reservations. In particular,
macOS admission is still enforced even though its per-process kernel limit is
best-effort. A running process can use more resident memory than its cap on
platforms whose kernel limit does not enforce resident memory.

## Requesting a larger cap

A process, its captain, or a person can file `POST /api/attachments/{id}/memory-requests`
with `requested_limit` and a reason. A captain can approve within the configurable
captain ceiling (default twice the process cap, bounded by the host ceiling); a
person decides above it. Approval stores the new cap and replaces the activation
through the normal resume path. The old admission lease is released first and the
replacement is grandfathered through admission. A process cannot approve the
request for its own cap. Only one memory request can be pending on a line at a
time; further requests receive HTTP 409 until it is approved or declined. The
warning threshold and captain ceiling are people-only settings in the resource
budget dialog.
