# Fleet resource budget

Partyline admits process starts across the whole instance, including child lines.
It reserves each starting or running attachment's configured memory lease and
admits new processes only when both the process count and sum of leases fit the
current settings. Restart-plan members that were live at restart are
grandfathered and continue to count. This is lease accounting, not a claim that
reported RSS equals actual memory or a hard aggregate kernel limit.

## Defaults and settings

People edit the instance settings in **Settings → resource budget**. Unset values
are computed from host resources at runtime and returned by `GET /api/resources`
and `GET /api/settings/resources`:

- Maximum live processes is `max(4, min(32, CPU count × 2))`. This server has no
  configured bounded worker pool that limits CLI starts, so 32 is the chosen
  safety ceiling; memory admission remains an independent limit.
- Memory reserve is `max(2 GiB, 10% of host RAM)`, capped when necessary so at
  least one default lease fits. On hosts too small to keep the full reserve and
  a 4 GiB lease, the reserve is reduced to host RAM minus 4 GiB.
- Default process lease is 4 GiB, capped by the existing per-process ceiling on
  smaller hosts. An attachment's explicit memory limit overrides it.
- Memory budget is host RAM minus reserve.

With the 4 GiB default lease, these host sizes have the following approximate
memory admission ceilings. The process setting and CPU default can lower the
effective count further; leases are accounted in whole processes.

| Host RAM | Default reserve | Memory budget | Processes allowed by memory |
| --- | ---: | ---: | ---: |
| 16 GiB | 2 GiB | 14 GiB | 3 |
| 32 GiB | 3.2 GiB | 28.8 GiB | 7 |
| 64 GiB | 6.4 GiB | 57.6 GiB | 14 |
| 128 GiB | 12.8 GiB | 115.2 GiB | 28 |

Settings accept 4–32 processes, a reserve from zero through 90% of RAM, and a
default lease from 256 MiB through the existing per-process ceiling. A saved
change must leave at least one default lease inside the memory budget. The
per-process ceiling is at most 8 GiB and 75% of host RAM. Existing attachment
memory settings remain available through the per-attachment memory endpoint.
An unset lease is resolved from the global default and saved on the attachment
at admission, so later edits to the global default do not change a live
process's reservation. People can change the saved lease while it is stopped.

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

The top bar shows fleet-wide process usage. Its popover includes leased memory,
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
| Sum of declared memory leases against host RAM minus reserve | Enforced by Partyline admission on Linux, macOS, and Windows |
| Per-process memory cap | Linux cgroup scope and Windows Job Object are kernel enforced; macOS `RLIMIT_AS` is best-effort address-space limiting and does not guarantee resident-memory use |
| Process overview RSS | Advisory visibility only; Linux `/proc` reading, absent on other platforms |
| Resource snapshots and captain briefing | Advisory visibility; they describe current reservations and do not reserve a slot |

The global accounting is portable and follows declared leases. In particular,
macOS admission is still enforced even though its per-process kernel limit is
best-effort. A running process can use more resident memory than its lease on
platforms whose kernel limit does not enforce resident memory.

## Follow-up: larger leases

The existing stopped-attachment memory endpoint can set a lease within its
ceiling. A future workflow should let a process request a larger lease with a
reason, have the root captain approve within the configured ceiling, and require
the person above that ceiling. This change does not add that approval workflow.
