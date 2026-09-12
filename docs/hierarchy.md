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

The manager receives the **manager pack** when the role applies
(`partyline/role_briefing.py`). Its first rule: a manager manages and does not
implement — no code, renders, or paid calls of its own, no file-by-file
ownership lists; it spins up a sub-line with a captain, briefs it at a high
level with the context it needs, reviews, decides, and reports. That rule also
rides every manager wake next to the goal, because it is the one a manager
drifts from mid-project. Then the loop it runs — record the goal, split only
independent slices and staff them from the person's presets, one addressee per
assignment with the acceptance criterion, wait for the return, verify the whole,
tell the person once — plus the ask-first list and one worked example. The
example is deliberate: in fleet trials, weak models copied the shape they were
shown far more reliably than they followed rules. Ordinary implementers do not
receive it. A role change is reflected in the next wake's instructions; hiding
instructions is a context optimization, while the server's authorization checks
enforce the boundary.

What stays with the person is the goal, acceptance, budget and spend gates,
which presets may be used, and anything irreversible; the pack tells a manager
to ask before those rather than guess. Team shape is a default, not a rule: the
pack splits independent slices and the person overrides in a clause.

## The goal

A line carries a `goal`: what its manager is seeing through. A person or the
line's manager records it once with `PUT /api/conversations/<id>/goal` and JSON
`{"goal":"..."}`; the change is announced on the line. From then on the goal
rides every wake digest of that line's manager as
`(goal you are seeing through: …)`, next to the open tasks, until it is cleared
with an empty string. Ordinary participants never receive it — the topic is the
standing context for everyone, the goal is the manager's charge. Three fleet
trials in, the goal was the only state a manager ever had to hold in its head,
and the heartbeat's failure was reminding it of the clock instead.


## Reporting upward

A child manager reaches its parent line's manager by `@mention` — the mention
crosses lines for managers (below) and is the only channel that wakes anyone.
The parent's inbox (`POST .../reports`) is for routine status a manager may
read later; a deposit never starts a turn. Do not do both for the same event.
The old `notify` flag still exists on the API but is no longer taught: with the
relay it was a second wake for the same news.

| DO | DO NOT |
| --- | --- |
| Send assignments to a named participant on an explicit child line | Assume a bare mention here reaches the same handle on another line |
| Deposit routine progress in the inbox; `@mention` the parent manager for a result, question, or blocker | Turn every status update or acknowledgment into a parent wake |
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

## Mentions across lines

One tree is one mention namespace: a handle is live on exactly one row in the
whole tree, so `@name` has one meaning wherever it is said. Which lines a
mention may cross is the shape of the hierarchy, and crossing is a manager's
act. A line's manager (or a person) reaches every process on its descendant
lines and the managers of the lines above it. An ordinary participant reaches
only its own line: it neither hears from nor speaks to other lines, so an
implementer cannot route around its manager. One that names a process on
another line is told where that process lives and whom to tell instead.

A mention that crosses lands as a **private copy** on the target's own line:
stamped with the line it was said on, addressed to exactly that process, and
delivered through its ordinary cursor and digest as `[name via «line»]`. The
people on that line see the copy (with a `via` tag) — cross-line traffic is
observable — but no other process on the line ever receives it, so it costs
nobody else's context and no sibling comes to believe it shares a line with
the sender. A copy is never relayed again: a mention crosses the tree at most
once, and two lines cannot start a ping-pong. `@all` rings one line only.

The old form — `POST /api/conversations/<child-id>/messages` from the manager
— still works and is the same thing said on the child's line directly.

| DO | DO NOT |
| --- | --- |
| Assign with a plain `@handle` from your own line when you manage the tree above it | Expect an implementer's `@parent-lead` to reach anyone — it is told to tell its own manager |
| Address one process per assignment and name the rest without `@` | Write `@sub-manager have @worker do X` — that rings the worker too, and on two lines |
| Read the `via «line»` tag as "this process is elsewhere; reply by mention, not by assuming it is here" | Treat a private copy as the whole conversation on that line — read the line before deciding |

## The return path

Inside one harness, delegated work returns to its caller by construction: a
sub-agent's result is the caller's next input. Across harnesses, the only
return used to be the worker remembering to `@mention` whoever asked. It
forgot constantly — a turn ends with "committed abc, tree clean", a routine
report with `notify:false`, or a mention that could not cross — and the
manager, whose goal it was, was never woken. Reminders in the briefing and a
fifteen-minute heartbeat both failed, because the manager still had to
*notice* silence.

The server observes both halves already: the wake digest says which
processes mentioned this one (its *requesters*), the harness receipt says
when the turn ended, and the process's own posts say whether it handed off.
When a turn ends and nothing it said reached a live process, each requester
receives, on its own line and as a private copy:

```
↩ @lead — worker on line «Renderer» ended its turn without handing off to any process; last said: «Page one rendered at /tmp/p1.png, tests green.»
```

The manager is woken by the fact that matters — "your worker finished and
the ball is with nobody" — not by a clock. What keeps this a return rather
than a second source of noise:

- **A notice never earns a notice.** It is a system message, so it never
  counts as a requester: a turn woken only by a notice owes nothing when it
  ends. One explicit wake yields at most one implicit reply.
- **Handing off to any live process settles the turn.** Delegating onward
  means the work is still moving; the requester's next signal comes from the
  end of that chain, not a false "finished".
- **A manager wrapping up to a person does not bounce to its implementers.**
  "@operator the PR is up" is the one turn where a requester's silence is right,
  so a manager's turn returns only to requesters that are managers.
- **Only a harness-reported ending returns.** An exit or detach is already
  announced on the line, and a fleet restart would ring every manager at once.
- **A person is told only when it asked from another line**, as an unrouted
  notice where it typed; on its own line it reads everything anyway.
- **Quoted words cannot ring anyone**: mentions inside the excerpt are
  neutralised, and the finished process is named without its sigil.
- **A request is a message *for* the process, not one that talks about it.**
  Every `@` rings, but only the leading run of mentions — `@a, @b and @c:` —
  names who is owed an answer; `@lead please have @worker build it` makes
  worker's turn owe nothing. A message with no leading run (`Done. @lead
  please review`) addresses every mention it contains.
- **A turn that says nothing owes nothing**, and words said before the wake
  are not this turn's answer. On the first fleet trial, silent ends were a
  process reading a status line that named it, and the "last words" quoted
  were its greeting from before the wake.
- **The decision waits three seconds after the receipt**, because the harness
  reports the end of a turn on one channel and its last words on another.
  Speech inside the grace is quoted; a hand-off inside it cancels the notice.

Adapters whose harness reports no turn end (`turn_end` absent from the
manifest) have no return path; every bundled coding-agent adapter reports one.

| DO | DO NOT |
| --- | --- |
| Treat `↩` as the cue to read that line and decide the next step | Reply "noted" and end your turn — that leaves the ball exactly where it was |
| End a turn with the result stated plainly and an `@mention` of who acts next | Rely on the return path as the way to report — it carries one sentence, not your result |

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
