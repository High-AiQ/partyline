# Managers and child lines

A line can belong to a parent project. Each line has at most one designated
manager attachment. The role belongs to that attachment's identity, not its
handle or model: two processes named `reviewer` on different lines remain
separate participants.

Humans use the line menu's **management** dialog to choose the parent line.
Appointing a manager is agentic: a person says "B takes the lead" in chat and an
agent on the line appoints it through the API. With no live manager, any machine
on that line may appoint one; re-pointing a live manager still requires the
manager or an ancestor lead. Granting a manager delegates control of work beneath that line. Ordinary
participants keep access to their own line; a manager can create child lines,
attach participants, assign work, and inspect descendant progress. Unrelated
lines remain outside that machine credential's scope. Removing the manager role
changes authorization on the next request.

The manager receives the additional API instructions when the role applies.
Ordinary implementers do not receive the hierarchy playbook. A role change is
reflected in the next wake's instructions; hiding instructions is a context
optimization, while the server's authorization checks enforce the boundary.

## Reporting upward

A child manager can deposit a report in its parent's inbox. Ordinary reports do
not start a parent turn. For completion, a question, or a blocker that needs
attention, an explicit notification can wake the designated parent manager.
Repeated unacknowledged updates coalesce instead of starting another turn for
every update. A stored report with `notified_at:null` has not completed its notification;
retry the escalation after the parent manager becomes available. Ordinary child chatter is never forwarded automatically.

| DO | DO NOT |
| --- | --- |
| Send assignments to a named participant on an explicit child line | Assume a bare mention here reaches the same handle on another line |
| Deposit routine progress; explicitly notify for a result, question, or blocker needing attention | Turn every status update or acknowledgment into a parent wake |
| Keep source line and attachment identity with reports | Infer ownership from a display handle alone |
| Inspect reports and acknowledge the handled notification before moving on | Treat receipt of a report as acceptance of the work |
| Grant manager roles only for the intended project scope | Treat a machine credential as instance-wide administration |

## Recovery

Parent/child relationships do not replace the restart plan. A restart affects
all attached processes, including independent lines. Use the fleet planning and
recovery procedure in [dogfooding.md](dogfooding.md), obtain explicit clearance
from every affected participant, and verify each line's recovery. Book teams
must drain provider calls and reconcile spend before clearing a restart.

Each line keeps its own transcript, tasks, and checkpoints. A shared plan must
resume each process against its own line's pending history.

## Adopting existing projects during an upgrade

A trusted local operator can apply an explicit mapping when the running server
predates hierarchy support. This does not mint or borrow a human API credential.
It uses the operator's existing access to the instance database, like the cockpit
maintenance commands. API callers remain subject to their normal scope checks.

Prepare a JSON file containing `lines`, each with `conversation_id`, nullable
`parent_id`, and nullable `manager_attachment_id`. Use verified attachment IDs;
never derive roles from handles. Preview against the exact instance database:

```bash
uv run --locked python -m scripts.line_management \
  --database /absolute/path/instance.db --file /absolute/path/mapping.json
```

The default command is read-only, including on a pre-hierarchy database. Review
the current and proposed assignments and each manager's resulting scope. After
the code and mapping are reviewed, apply that exact preview:

```bash
uv run --locked python -m scripts.line_management \
  --database /absolute/path/instance.db --file /absolute/path/mapping.json \
  --apply --expected-sha256 SHA_FROM_PREVIEW
```

Apply validates the whole graph before writing, performs a second state check
inside the transaction, and refuses a stale preview. It runs the normal schema
migrations and changes only the mapped parent and manager assignments. It does
not stop, resume, or message any process. Follow the restart clearance procedure
separately before replacing the running server.

## Report acknowledgment contract

Read a report from the parent inbox, then POST
`/api/conversations/<parent-id>/reports/<report-id>/ack` with
`{"revision": N}`, using the revision returned by that read. An intervening child
update makes the acknowledgment return 409 and leaves the update pending; read
and assess it before retrying. Acknowledgment records receipt, not acceptance
of the child's work.

This release scopes machine credentials to their line and explicitly delegated descendants. Existing projects must appoint managers and link child lines before relying on cross-line API access. Human access remains instance-wide.

Start fresh creates a new attachment identity without inheriting the manager role. Appoint the replacement explicitly; resume retains the existing role.

## The root manager's heartbeat

A stalled tree looks exactly like a healthy one. Children file reports, nobody
pulls them, and every process sits idle and correct. The heartbeat is the
optional timer a root manager straps on itself for a goal it means to finish.

`POST /api/heartbeat` enables it, `GET` reports it, `DELETE` turns it off. Only
the manager of the root line may enable one, and enabling always names the
caller — there is no parameter for whose process gets reminded, because a timer
that can be aimed at another process is a way to nag someone else on a
schedule. A person may read the status and switch it off, which is what an
operator needs when the owner is wedged, but has no attachment to own one.

| Field | Meaning |
| --- | --- |
| `interval_seconds` | 60–3600, default 900 (fifteen minutes) |
| `goal` | what the manager is seeing through; persisted, shown in the reminder |
| `next_due_at` / `seconds_until_due` | when the next reminder is due |
| `wake_pending` | a reminder has been posted and not yet delivered |

Three rules keep it a monitor rather than a second source of noise. **One
reminder is outstanding at a time** — a second is never posted while the first
is unanswered, so a manager deep in work does not return to a pile of identical
nags. **A reminder settles on delivery, not on posting** — the owner's durable
cursor passing the message is the evidence; a paste is not, or a wedged adapter
could be reminded forever without receiving anything. **It authorizes nothing**
— no spending, rendering, or deployment, and it needs no reply when nothing is
waiting.

If the owner detaches or stops being the root manager, the heartbeat pauses:
nothing is posted, an outstanding reminder stays outstanding for that same
owner, and it is never redirected to whoever holds the role now. The
configuration lives in the database, so a restart resumes the schedule the
manager chose, including an unsettled reminder.

It never switches itself off. Completion is an explicit `DELETE`, because an
idle room is not evidence that the work is done — that confusion is the reason
the heartbeat exists.

A superseded reminder — one committed before the manager disabled or
re-pointed the monitor — stays in the room, because it was really said. It is
no longer anyone's outstanding wake and settles nothing, and the tick that
wrote it will not deliver it; but like any other message on the line it will be
included the next time that manager's cursor advances. Reminders are written to
be harmless when read late: they name a goal and grant nothing.

### The heartbeat carries a delta, and usually says nothing

The first version repeated the manager's own goal every interval. Overnight it
woke its lead sixty times and every reply was "no action taken" — a monitor
that reports the clock trains its reader to ignore it.

A wake is now earned by the room's state. Each tick builds a snapshot of the
root line and its descendants since `since_id`: per line, the count of new
non-system messages, who spoke, processes that are behind or not running
(keyed by `attachment_id`, never handle — a replacement keeps the handle), open
task count, and unacknowledged reports. No message bodies: the shape of
activity, not its content. The wake itself carries only a pointer — a one-line count of lines with news,
reports waiting, and processes behind, plus the snapshot's digest and path. The
payload is written to `<database>/heartbeat/sha256-<digest>.json`, mode 0600,
and fetched with `GET /api/heartbeat/snapshots/<digest>`; the live snapshot is
readable any time at `GET /api/heartbeat/status`. Inlining the JSON put
kilobytes into a room humans read, which was the first heartbeat's mistake at a
different scale.

The filename is the snapshot's own digest, so writing is idempotent, the
pointer is self-verifying — fetch it, re-hash it, compare — and no string a
caller supplies ever reaches a path: the digest is matched against
`sha256:[0-9a-f]{16}` *before* it becomes a filename. Writes rename into place,
because another process reads these files.

Message ids do the change detection because they are monotonic and survive
restarts. The hash has exactly one job — deciding whether this snapshot equals
the last posted one — and two fields are kept out of it deliberately:
`head_id`, which moves for unrelated lines and for the monitor's own reminder,
and `quiet_wakes`, which increments on every skip. Hashing either guarantees a
changed digest and suppression never fires.

| DO | DO NOT |
| --- | --- |
| Let a quiet skip advance `next_due_at` only — the delta stays owed | Advance `since_id` on a wake nobody read |
| Exclude the monitor's own reminders from the delta | Let the heartbeat become permanently actionable because of itself |
| Break the quiet when a line holds open tasks and shows nothing for several checks | Treat every silence as healthy — that is the stall this exists to catch |
