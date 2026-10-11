# Captains and child lines

In chat and in the web client the manager of a line is its **captain**; the API
and database keep the older name `lead` (`POST /lead`, `is_lead`). A person
appoints a captain in the line menu's management dialog, or an agent does it
through the API; either way the new captain is rung at once with the captain
pack, and once a line has a captain, only that captain, an ancestor captain, or
a person may appoint another — anyone else gets 403.

A line can belong to a parent project. Each line has at most one designated
manager attachment. The role belongs to that attachment's identity, not its
handle or model: two processes named `reviewer` on different lines remain
separate participants.

Humans use the line menu's **management** dialog to appoint the captain and to
choose the parent line. Appointment is deterministic and never inferred from
chat: a person, the line's captain, or an ancestor captain appoints through
`POST /lead`, and anyone else gets 403 — a line with no captain waits for a
person. Granting a captain delegates control of work beneath that line. Ordinary
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

Two more rules ride the pack. Before accepting handed-up work — a child line's
branch and report, or a same-line worker's commit — the captain ensures an
adversarial review at the exact SHA has been completed in a throwaway worktree:
the whole diff from its intended base, the gates run, hunting what the report
omits (`skills/adversarial-review/SKILL.md`). The captain may run that review or
delegate it, but must hold its findings; a bare delegate's "done" is not a
review. A report is receipt, not acceptance, and the bar is the same on both
paths. And on a captained line the captain is the only one who pushes: a worker
commits locally and hands up the SHA, and the captain pushes after that review.
A line with no captain keeps the old behaviour. The worker pack is its own short
block, gated on a live captain. Its first rule is the edit gate: a worker on a
captained line never edits files, runs mutating commands, or starts work of any
kind until its captain @mentions it with an explicit assignment — the line's
goal and topic are standing context, not an assignment, and an @mention from a
person or another worker is answered, not acted on, unless the captain said so.
Then the push rule: commit locally, hand up the SHA, do not push. A worker
briefed while a captain sits on the line gets the pack at join, is re-briefed
when one is appointed, and loses the block when the captain goes; every wake of
a captained worker also carries a one-line reminder that the goal is context
and the captain's @mention is the job.

Work that pops up a level is reviewed again, not countersigned. Five rules keep
that honest. **Fresh scrutiny at every hand-off:** work reviewed and accepted
below still gets its own review when it reaches a captain — a lower captain's
acceptance is input, never a substitute. **Scope differs by level:** a captain
with children checks whether the assignment it gave was fulfilled and whether the
piece integrates; a captain with same-line workers checks implementation
correctness; a root captain also checks the whole user request and shipping
readiness. **Inspection delegable, acceptance not:** a captain may commission the
inspection, but the acceptance decision is its own and cannot be delegated or
inherited. **Evidence reuse is SHA-bound and optional:** recorded gate and test
evidence carries only at the same unchanged exact SHA — a new SHA voids it — but a
captain may always re-run any gate a finding warrants; reuse is permitted, never
mandated. **Acceptance records three things:** the independent checks this
captain ran, the evidence it reused with that SHA, and the rationale for
accepting at its scope.

What stays with the person is the goal, acceptance, budget and spend gates,
which presets may be used, and anything irreversible; the pack tells a manager
to ask before those rather than guess. Team shape is a default, not a rule: the
pack splits independent slices and the person overrides in a clause.

## Depth, worktrees, and where work goes

Depth is a line's ancestor count; a root line is depth 0. A machine may create
child lines only above `MAX_CAPTAIN_DEPTH` (2): a line at the cap is a **leaf**,
and its captain receives a pack that says so — staff this line from the
presets, assign, review, report up — instead of the "spin up a sub-line"
procedure that had every captain spawning another. The pack is gated on being
captain, not on the create-child permission, so a leaf captain is never
mistaken for an ordinary participant. `GET /api/capabilities` reports `depth`
and `max_depth`. People are never boxed by the cap.

A child line is placed when it is born. If the parent line works inside a git
repository, the child gets `<repo>/.partyline-worktrees/<slug>` on branch
`line/<slug>` (kept out of `git status` through `.git/info/exclude`), and the
line hears "☏ working directory: … a git worktree on branch …". A birth may
also target another repository this machine has: `POST …/children` accepts an
optional `repository` — an absolute path anywhere inside a git repository —
and the child is placed under *that* repository's `.partyline-worktrees`,
with the same capability checks and the same branch naming. This is for work
that belongs to another project entirely (a partyline-improvement line while
the parent captains a book project); the birth notice names the directory, so
everyone can see the child does not live in the parent's checkout. An
explicit `repository` is never git-initialised and never created: a relative
path or a directory outside any repository is refused with 400. Otherwise it
inherits the parent's directory. A machine attaching a process to a line
cannot choose another directory: the process works where the line works. A
person may. Purging a line drops its worktree; the branch stays.

A parent line whose directory is not a repository gets one initialized (one empty root
commit) before its first child is placed, so a project started in a blank directory still
gives every child its own worktree. A file attached to a message that is relayed to a
process is readable by that process, and only that one, even though the file lives on the
line it was posted to; a captain briefed with a document does not need it copied to disk.

Archiving a line also removes its worktree, when it is **SAFE** to: the working tree is
clean, and every commit reachable from the worktree's HEAD — its branch `line/<name>`, or a
detached tip that lives on no branch — is reachable from the parent line's branch or the
repository's default branch; nothing sits only in the worktree about to disappear. When it
is not SAFE the worktree stays, the branch always stays, and the archive response's
`worktree_kept_reason` says why (`unmerged commits` or `uncommitted changes`); a person can
see this in the delete dialog. Purge keeps removing a line's worktree unconditionally, as
before. A captain may also retire a child line of its own tree with `DELETE
/api/conversations/<child-id>` — never its own line — when that child has no live processes,
its goal is cleared, and the SAFE test passes.

Before you clear a goal, detach the final workers, or retire a line, persist its
deliverables, assets, and unfinished work in the intended durable repository or application
storage, or an accessible handoff location, verify the read-back, and record the locations
in your handoff. A commit does not keep generated non-git assets, and a temp directory, a
worktree, or an upload only the child can reach is not a sole copy. Preserve unfinished work
and report blockers before any destructive cleanup.

A refused retirement answers with **every** blocker at once instead of one per round trip:
`409` body `{"detail": "…", "blockers": [{"code": "live_processes" | "goal_not_cleared" |
"child_lines" | "unmerged_commits" | "uncommitted_changes", "message": "…"}]}`. A person is
held only to child lines; a machine captain is held to all of them. The one explicit relief
is `DELETE /api/conversations/<child-id>?discard=true`: it throws away a **merged** branch's
uncommitted worktree so the line can retire, and it is refused outright when the branch is
not merged — those commits exist only in the worktree and a discard must never destroy them.
`include_children=true` still retires the whole subtree and supersedes the child-lines
blocker. When you have accepted a child's branch and its captain is done, retire the child:
its worktree goes with it. On startup the server sweeps `.partyline-worktrees` in every
repository it knows about and removes any worktree whose line no longer exists in the
database, unless it is dirty; a worktree belonging to a live or archived line is never
touched.

Operational hierarchy rules ignore archived children, while purge ordering and restore traversal
continue to include them.

## Approvals at the root

Requests that need a person bubble to the root. A write-set, memory-cap or restart request
filed on a child line posts its ordinary notice there plus one `⚑ approval pending` line on the
tree's root, naming the line, the requester and the approve call, and @mentions the root's
captain so that process wakes and can explain the request in context — the person talks to the
root captain and never reads sublines. A request filed on the root itself does not bubble, and
the staffing wake line counts what is still waiting anywhere below:
`approvals pending: N («line» write-set, «line2» memory)`, falling as each request is decided.

Work goes down, not sideways. Once a line has a child, a machine may no longer
attach processes to that line: the root captain that could not staff a child
otherwise hands the job to a sibling on the root line, in the checkout the
child lines are already editing. Presets double as handles, so the same preset
used twice in one tree used to collide with a 409 that read as "cannot staff";
the server now suffixes the handle (`grok-2`) and the agent helper prints the
server's reason on every failed request.

The rule is symmetric. A line that already carries live workers — attached by
its parent captain or by a person — cannot be split by its captain: `POST
…/children` is refused with the workers' names, `create_child` leaves its
capabilities, and its pack and every goal rider say "the workers on this line
are yours: assign them". Before this, a captain handed a worker read "spin up a
sub-line" in its pack and did exactly that, staffing a second copy of the same
preset on the grandchild while the first sat idle.

## The checkout a line works in

A line owns exactly one branch. Partyline creates the worktree and the branch
`line/<slug>` when the line is born, and nothing else a worker creates there
counts: the parent accepts the branch — its accepted SHA is recorded by
`POST …/accept` — never a side branch or a detached tip a worker happened to
make. An attachment placed outside the line's worktree (a person's choice;
machines always work where the line works) hears a warning on the line that
commits there land off the line's branch.

A captain once planned a whole book from a checkout whose `main` was 102 commits
behind `origin/main` and carried an old, uncommitted plan document; every child
it spawned was cut from the same base. So the line now hears a `☏ checkout:`
line — short SHA, branch, ahead/behind its upstream after a fetch, modified and
untracked counts — when a captain is appointed, and a child line hears its
`☏ base checkout:` when it is born. A machine cannot create a child from a
checkout that is behind its upstream (409 says why); a person can. The
per-message `(cwd git: …)` tag adds `N behind upstream` against the last fetch.
Nothing in this path pulls, resets or stashes: the pack tells the captain to
ask, and the person brings the checkout up to date.

When the checkout is behind anyway and the next child cannot wait, the birth
itself can be made safe: `POST /api/conversations/<id>/children` takes
`"base":"upstream"`. Partyline resolves the repository's configured upstream
default (`origin/HEAD`, else the current branch's upstream), fetches it, and
branches the child from that ref — the child starts at what the upstream
already has, never in the past, and the birth notice names the ref it was cut
from. The default stays `base:"checkout"`: the child branches from the parent
checkout's HEAD, exactly as before. The stale-checkout refusal for machines
applies only to the default; a person may cut from either base. Inside the
fence a line's view of the parent branch is launch-time fresh: `GET
/api/conversations/<id>/base` reports the parent branch as the host sees it
and how far behind the line is, and `POST …/refresh-base` re-copies that ref
into the line's fenced view; an accept on a line refreshes its children's
views automatically.

## The hand-off contract

A child line is born briefed. `POST /api/conversations/<parent>/children` takes
`name`, `goal`, and `topic`: the goal is recorded on the child and rides its
manager's every wake; the topic is the standing context every process on that
line reads — where things are, the budget, the gates, the acceptance criterion.
Both are announced on the child line so the hand-off is on the record. A
captain cannot read its parent's line, so what is not in the brief it does not
know; the manager pack asks for both fields every time a slice is split off.
The appointed manager is rung the moment it is appointed, with a private
notice that carries the manager pack in its digest, so a process that appoints
itself mid-turn reads the pack before it acts further — the first live root
otherwise staffed its own line before the pack reached it. A captain is briefed
the same way its root was. A worker attached to a line whose captain is already
live is born knowing the worker pack — wait for the captain's @mention, commit
locally, hand the captain the SHA, do not push — and hears it again whenever the
captain appears or leaves. Workers attached *before* the captain is appointed
had no pack at join, and the rider only carries it on their next wake, which
used to be whatever they decided to do with the goal. Appointing a captain now
also posts `☏ workers @a @b: <captain> is now this line's captain — wait for
your captain's @mention before editing anything` and routes it, so every live
worker wakes once with the pack in that digest; the captain is named bare there
because every `@` rings.

A handle written as `name:` at the start of a line is an address too, when a
live process on that line bears it: `worker: take the review` rings worker.
Weak models drop the sigil constantly; a label that names nobody rings nobody.

## The accepted SHA

The hand-off is the SHA on the line's branch; nothing else counts. Work used to
come back on detached refs and side branches while the line's own branch stayed
at an early commit, and a parent relaying the SHA from a report once pushed the
wrong commit. A captain of the parent — or the line's own captain, marking
hand-off — records it with `POST /api/conversations/<id>/accept` and JSON
`{"sha":"..."}`. The server verifies the SHA exists, verifies the line's branch
can fast-forward to it, moves the branch, records it on the line, and announces
it there. Under the write fence the line commits to its mirror branch, so
accept also reads that mirror when one exists: a SHA equal to the mirror tip
or descended from it is landed on the real branch with a compare-and-swap ref
update, while a mirror tip the SHA does not carry (ahead of it or diverging
from it) is refused as a stray. A worker often commits again after the review,
so the reviewed SHA is then an ancestor of the mirror tip rather than the tip
itself: `{"sha": "...", "allow_descendant": true}` accepts such a hand-off by
fast-forwarding to the tip instead of refusing it. The response names both
SHAs (`reviewed_sha` and `sha`), the ☏ notice counts what went in unreviewed
(`N commit(s) past the review`), and the reviewed SHA's review worktrees are
pruned along with the tip's — accepting work nobody reviewed stays visible in
the record, never silent. `GET /api/conversations/<id>/tip` returns
`{"branch", "branch_sha", "fenced_tip"}` — where the line's branch and its
fence mirror point (`fenced_tip` null with no mirror) — so a captain reads
the fenced tip before accepting instead of learning it from a 409. Accepting
only fast-forwards: a branch that carries commits the SHA
does not include, or a SHA from an unrelated history, is refused with 409
rather than merged or rebased, so accepting never orphans a commit. Nothing is
pushed; the captain still pushes after its own review, as before. The recorded
SHA rides the ☏ checkout line a captain hears on appointment, the staffing
board (`GET /api/conversations/<id>/staffing`) returns a `lines` list naming
each descendant line's `accepted_sha`, and every captain wake carries a
`(hand-off: …)` digest rider — the line's accepted SHA and worktree path, plus
each descendant that has an accepted SHA — so a captain planning from a wake
sees the hand-off without asking. A tree with no hand-offs carries no rider.
Anyone else who wants to record a
hand-off gets 403 — a captain higher up reviews the work again at its own
scope, so nobody accepts across two levels. The accept call also takes an
optional `"findings":["…"]` — at most 20 findings of at most 300 characters
each, what the review actually caught — recorded one row per accept with
the reviewer and the SHA, counted in the ☏ notice (`(N findings)`) and
listed newest first by `GET /api/conversations/<id>/accepts`.

## Review worktrees

An adversarial review needs a checkout of the exact SHA, and sub-captains used
to run `git worktree add /tmp/...` for it — around thirty times in one program,
and nothing pruned them. A review worktree is partyline's instead: `POST
/api/conversations/<id>/review-worktrees` with JSON `{"sha":"..."}` — creation
writes into the repository, so it needs `write` on the line (a person, its
captain, the parent's captain) — or the documented CLI form, `python -m
scripts.review_worktree --database <db> create --conversation <id>
--sha <sha>`. Either checks the SHA out detached at
`<repo>/.review/<full sha>`, records it on the line, and announces it there.
`GET .../review-worktrees` lists a line's recorded reviews. The body may also
name `"repository": "/abs/path"`: the checkout is placed in that repository's
`.review` when the line itself — or any line of its subtree — works in it
(finding 2.2: a captain verifies a toolkit candidate against the repository
it actually affects), and any other repository is refused. The record stays on
the calling line, so retirement, archiving and the startup sweep prune it in
whichever repository it was created, and a write-set request may grant a
review checkout by the same pair (`{"repository": ..., "sha": ...}`) — the
server derives `<repo>/.review/<full sha>`, so nobody types the path. The records drive
the cleanup: every review worktree of a line is pruned when the line is
retired, archived, or purged, and the accepted SHA's review goes when that SHA
is accepted (reviews of other SHAs stay until the line retires — they may
still be mid-review), so a finished
review never lingers. At startup the sweep also drops `.review` directories
whose line is gone or that no record claims — only full-SHA directories, since
partyline owns the directory but nothing else in a repository's `.review`.
Review checkouts are disposable by contract: pruning is forced, and the SHAs
themselves stay in the repository, so no reviewed work is ever lost.

## Scratch worktrees

A review checkout is for adversarial reads; verifying an integration needs a
build, and a build writes. `POST /api/conversations/<id>/scratch-worktrees`
with `{"sha":"...", "repository":"<abs path>"?}` checks the SHA out detached
and **writable** at `<repo>/.scratch/<full sha>` — same subtree rule, same
creation permission, recorded on the calling line. The fence binds a line's
recorded scratch checkouts writable, so the line's own process builds there
without a write-set request; review checkouts stay exactly as they are.
`GET …/scratch-worktrees` lists them, `DELETE
…/scratch-worktrees/<sha>` drops one early, and a scratch checkout is pruned
when the line retires or is purged and swept at startup when its record or
its line is gone — it is never pruned by an accept, because integration
checks follow the accepted work. The startup sweep owns only full-SHA
directories under `.scratch`.

## Pre-review checks and the tree sync

Some findings need no judgment, so they run without a model. `POST
/api/conversations/<id>/prereview` with `{"sha": "...", "data_paths":
["data/"]}` reads exactly the commit's bytes — `git ls-tree` and `git show`,
never a worktree — and reports every path-like string in the JSON tables
under `data_paths` that the commit does not track, flagging the ones the
checkout's ignore rules hide (the `out/` incident: real on disk, absent from
every commit, gone on any other machine). It returns `{"ok", "missing":
[{"file", "ref", "ignored"}], "checked"}`, needs only `read` on the line, and
resolves the SHA under the same subtree rule as review worktrees — probing
ignore rules in that subtree line's own checkout. A reference counts as
present when it resolves from the repository root or from the naming table's
own directory, or when it names a tracked directory — a reference ending in
a slash is read as that directory — and engine schemes are
checked through `res_roots` (e.g. `{"res://": "game/"}`), so a game's
`res://` tables are checked in the tree they ship from. After an
accept, the response and the ☏ notice carry `tree_sync`: any worktree holding
the accepted branch must sit at the accepted SHA with a clean status — a
stale or dirty checkout is reported (`⚠ tree not in sync: …`) in the accept
response, never fixed automatically.

## Partyline docs for captains

Partyline's own documentation is readable over the API, in shelves rather
than one dump: `GET /api/docs` lists the categories (captaining, attachments,
review-and-accept, fence-and-write-set, memory-and-resources, restart,
best-practices, lessons), `GET /api/docs/<category>` lists a category's
topics, and `GET /api/docs/<category>/<topic>` returns one section — sliced
live from the repository's `docs/*.md`, so there is no second copy to drift;
a mapped heading that disappears is refused, not paraphrased. People and
current captains read them; workers and ordinary participants are refused.
A captain's wake carries the pointer `(partyline docs: GET /api/docs — …)`
roughly every N line messages since the last one — a setting,
`docs_reminder_every_messages`, default 40 — and never on every wake.

## Compaction as a line event

A worker's context compaction used to show only on its own screen. On an
adapter that declares the `compaction_hooks` capability (Claude Code today),
the harness's `PreCompact` hook posts `⚠ @<handle> compacted (auto, Nth
time)` on the line and bumps a persisted counter that the staffing line
shows as `×N compactions`. The third `auto` compaction within five hook
turns rings the line's live captain once — that is thrash, and the remedy
is a fresh instance of the same preset, never a re-prompt.
`SessionStart(compact)` folds a partyline re-briefing back into the worker's
context: the goal, the line's topic, and the latest captain-or-person
message that @mentions the process, verbatim. Adapters without the
capability get no hooks, no counting, and a 403 from the rebrief endpoint.

## The line notebook

What must survive a compaction lives in the line notebook:
`GET` / `PUT /api/conversations/<id>/notes?scope=line|attachment|tree` with
`{"notes":"…"}`, capped at 4,000 characters. `tree` is stored on the root of
the tree (contracts, standing rules), `line` on the line itself (goal,
acceptance, decisions), `attachment` per process (what I am doing, files
touched, last gate result, next step). A captain writes `line` notes; each
process writes only its own `attachment` notes; `tree` writes need `assign`
on the tree root, so the root captain (or a person) writes them; people
write all three; anyone with `read` on the line can read. The notes ride the
post-compaction re-briefing in that order, ahead of the latest assignment,
inside the same 4k cap.

## Shared-resource leases

Anything on the host that needs exclusivity — a GPU render, a timing run —
is serialised by a lease, not by prose in a topic. `POST /api/leases` with
`{"name":"godot","ttl_s":900,"mode":"exclusive"|"shared"}` returns
`{"granted", "holder", "queue_position", "expires_at"}`: an exclusive lease
waits behind any holder, shared leases coexist with each other but not with
an exclusive one, and queue place is held — polling never slides a waiter
backwards, and when the slot frees, promotion is by queue order (the
earliest waiter, or the leading run of shared waiters). TTLs cap at four
hours; posting again renews or re-queues; `DELETE /api/leases/<name>`
releases the caller's lease, and a process's leases die with it on exit or
detach. `GET /api/leases` lists holders and queues, the staffing line shows
held leases (`leases: godot (exclusive) @sonnet «world-assets», 1 queued`),
and a captain's wake carries a host summary (cores, free memory, load) at
most once every ten minutes. Leases are taken and released by processes; a
person is refused.

## The goal

A line carries a `goal`: what its manager is seeing through. A person or the
line's manager records it once with `PUT /api/conversations/<id>/goal` and JSON
`{"goal":"..."}`; the change is announced on the line. From then on the goal
rides every wake digest of that line's manager as
`(goal you are seeing through: …)`, next to the open tasks, until it is cleared
with an empty string. Ordinary participants never receive it — the topic is the
standing context for everyone, the goal is the manager's charge. Three fleet
trials in, the goal was the only state a manager ever had to hold in its head,
and the heartbeat's failure was reminding it of the clock instead. The topic
is capped at 20,000 characters (the goal at 3,000) — a longer brief belongs
in a repo file named by the topic, such as `docs/contracts/<line>.md`.


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

Unexpected process failures now have a separate recovery path: a durable incident
on the failed process and a private wake to the nearest live captain. A dead
captain is skipped in favor of its parent. The notice includes an inspection API
and directs the captain to fix the workload or approve a finite memory override
before resuming. Deliberate stops and normal exits do not escalate. See
[memory failures and recovery](write-fence.md#memory-failures-and-recovery).

Parent/child relationships do not replace the restart plan. A restart affects
all attached processes, including independent lines. Use the fleet planning and
recovery procedure in [restart.md](restart.md), and verify each line's recovery
afterward. A mid-turn process is resumed and privately rung to continue
automatically ([restart.md](restart.md#what-happens-to-a-process-mid-turn)); it
is not a reason to delay approval. Book teams must still drain provider calls
and reconcile spend before a restart lands — the automatic plan resumes the
conversation, not an in-flight billing transaction.

Each line keeps its own transcript, tasks, and checkpoints. A shared plan must
resume each process against its own line's pending history.

## Adopting existing projects during an upgrade

A trusted local operator can apply an explicit mapping when the running server
predates hierarchy support. This does not mint or borrow a human API credential.
It uses the operator's existing access to the instance database, like other
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
not stop, resume, or message any process. Follow the restart-request procedure
in [restart.md](restart.md) separately before replacing the running server.

## Report acknowledgment contract

Read a report from the parent inbox, then POST
`/api/conversations/<parent-id>/reports/<report-id>/ack` with
`{"revision": N}`, using the revision returned by that read. An intervening child
update makes the acknowledgment return 409 and leaves the update pending; read
and assess it before retrying. Acknowledgment records receipt, not acceptance
of the child's work.

This release scopes machine credentials to their line and explicitly delegated descendants. Existing projects must appoint managers and link child lines before relying on cross-line API access. Human access remains instance-wide.

Start fresh creates a new attachment identity without inheriting the manager role. Appoint the replacement explicitly; resume retains the existing role.

## One process on a line

The @mention says who acts next in a room with several processes. On a line whose
only live process is X, a person's message with no mention and no colon-address
reaches X as if it said `@X`: there is nobody else it could be for, and typing the
handle before every line was a tax that protected nothing. The shortcut is for
people only — an agent's plain speech stays a reply for the room, so two processes
cannot ring each other forever — and it switches itself off the moment a second
process is live on the line. A held wake (a process mid-turn with receipt
completion) treats such a message as addressed, the same as a mention.

Parallel slices mean parallel lines. A machine attaching a second
implementer to a line that has a captain and a live worker is refused with
409 — one branch accepts all-or-nothing — unless the attach call names
`{"allow_shared_branch": true}`; a person is never refused, but the attach
posts a ⚠ notice marking the branch as shared. A line with no captain is
unaffected.

A process can also be replaced outright: `POST /api/attachments/<id>/replace`
with `{"reason":"…"}` stops it and starts a fresh instance with the same
handle, preset, command and working directory — a new CLI session, never a
resume, because clean context is the point. The captain role survives, the
line reads `↻ @<handle> replaced with a fresh instance (by @<who>): <reason>`,
and the fresh process's first briefing carries the re-briefing (the line's
notes and its latest assignment) as its checkpoint. The line's captain, or a
person, may replace; a worker may not.

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

## Idempotent posts and the terminal echo

A message POST may carry a `client_key` (up to 64 characters). The same
sender presenting the same key within ten minutes gets the original message
back — 200, same id, nothing stored twice — so a retry after a false
`connection/request failed` cannot duplicate a post. Keys derived by
`agent_client` (sha256 of method, path and body) are marked `d:` and replay
for only 120 seconds, and every replayed response says `"replayed": true`; a
caller wanting a deliberate repeat of identical text sends its own key.
The other direction is collapsed too: a machine POST whose text equals that
process's own terminal-captured message on the same line within 15 seconds
returns the capture instead of storing a twin.

## Ack ping-pong limits

Two workers trading bare acknowledgements — "standing by", "suite at 13
of 61", "ok" — ring each other forever without moving anything. When a
worker @mentions exactly one live peer whose last message mentioned it
back, and nothing real happened on the line in between, the third such
consecutive exchange is refused: an API post answers 429 before anything
is stored, and terminal-captured speech is stored but its mention is not
delivered, with one ⚠ notice saying to react 👀 instead. Real activity
breaks the streak: a person or third process speaking, a file, a reaction,
an accept, a message carrying a commit SHA, or anything substantive (more
than 280 characters). Captains and people are always exempt — assignments
and hand-offs must ring — and so are `@all` and multi-addressee mentions.

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
- **A return rings only a requester that is waiting.** A captain that acks
  and keeps working has not stopped for an answer, so a notice owed to a
  mid-turn requester is deferred until its turn ends, and dropped if it handed
  off to anyone in the meantime. On the live run the un-deferred version cost
  one "still holding" turn per courtesy reply.
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

**Deprecated and off by default since 1.23.0**, behind the `heartbeat` feature flag
([configuration](configuration.md#feature-flags)). The return path and the goal riders
proved to be the wake signal; everything below describes the timer as it runs when the
flag is on.

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
