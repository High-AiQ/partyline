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

**A task's workspace (`partyline/task_workspaces.py`).** An orchestrator task is born into
`<root folder>/.partyline-worktrees/<slug>`: a worktree of the root folder when that is a
repository, a plain folder otherwise (its top-level `AGENTS.md` and `CLAUDE.md` are symlinked
in, never written through), plus a worktree of every clone under the root folder (depth 3;
`.git`, `node_modules`, `.partyline-worktrees`, `.review`, `.scratch` skipped) at the same
relative path, each on `line/<slug>` in its own real clone and recorded in `task_workspaces`.
The fence binds each worktree's git like a single-worktree line and protects its real clone.

All attachments on a line share its Git refs mirror. Every launch refreshes sibling
refs while preserving the line branch and the launching worktree's HEAD branch in
loose refs, packed refs, and reflogs. A detached reviewer launch must preserve the
line branch too, including when its unpublished tip exists only in packed refs.

Commits live in the line's private refs mirror until accept, so each `request_review`
and idle hook writes `refs/partyline/tasks/<slug>` in the real clone, where git's gc can see
it. The mirror tip is where the worker's commits live until accept. The `tasks` and
`process_overview` captain reads, and the task GET endpoint, show every workspace's real and
mirror tips plus a bounded sample of unaccepted commit subjects; do not infer task progress
from the nested checkout's host branch alone. `request_review()` with no arguments reviews
every workspace whose branch moved; a SHA in any recorded clone is admitted.

A root captain can give a live task a commit or branch created after its launch with
`share_ref(conv_id, ref_or_sha, name, repository?, replace?)`. The default repository is the
task's primary `task_workspaces` row; `repository` selects another recorded workspace. The
server resolves and verifies a commit in that real clone, then writes only
`refs/partyline/shared/<name>` in the task's refs mirror. Names contain at most 64 letters,
digits, dots, underscores or dashes, cannot start with a dot or contain `..`. An existing name
is idempotent at the same commit and otherwise moves only with `replace=true`. The operation
never changes the task branch, HEAD, packed refs or reflogs. The result includes the full SHA,
the ref and `git merge refs/partyline/shared/<name>`; one private message tells the live
implementer the ref. The fence mounts the real clone's object store into the task Git directory,
so no object copy or alternates file is needed. Launch/resume preparation preserves shared refs
instead of treating them as sibling refs to refresh.

Accept records every reviewed commit and fast-forwards only the task's own `line/<slug>` in
each clone; the person's checked-out branch never moves. Retiring a task first copies each
mirror tip onto its `line/<slug>`, then removes each nested worktree through its clone with
no `--force` (a dirty one stays and is named), then the task folder; the branches stay. A
clean worktree registered to another clone is not a "nested repository" to the P0 guard; an
independent clone (a `.git` directory) still keeps the folder.

A parent line whose directory is not a repository gets one initialized (one empty root
commit) before its first child is placed, so a project started in a blank directory still
gives every child its own worktree. A file attached to a message that is relayed to a
process is readable by that process, and only that one, even though the file lives on the
line it was posted to; a captain briefed with a document does not need it copied to disk.

Archiving a line removes its worktree when all commits are merged into the parent
or default branch and its changes are either absent or durably snapshotted (below).
Automatic storage cleanup then revisits any retired worktree kept by this SAFE pass.
It saves uncommitted and unmerged Git work to `refs/partyline/discarded/storage-<id>/`
in the owning repository before removal. Independent nested clones, protected restart
plans and failed recovery keep the path with a reason; see [storage](storage.md).
A captain may retire a child of its own tree with `DELETE /api/conversations/<child-id>`
when the child has no live processes, its goal is cleared, and the stricter clean
and merged checks pass; a person may archive a dirty line with snapshot preservation.
End-of-work rule: once every task is merged and released, or the captain is completely
blocked waiting on a person, the captain detaches every other process on its tree
(implementers, reviewers, sub-captains and helper processes); no worker stays attached
"standing by". `POST /api/conversations/<id>/attachments/close` called by a captain stops
everyone on the line except the caller.

Who may detach whom: a worker cannot detach anything, itself included (`close` is a
captain's capability). A captain detaches other processes freely. A captain detaches
*itself* only when a person explicitly tells it to, or through a captain handover, which
the server performs. The server refuses a captain's own `DELETE /api/attachments/<id>`
unless it names the person who asked (`?told_by=<handle>`), and the refusal says so.
Being idle, having finished, or having asked a person a question is not a reason: a
captain that leaves after every question has to be resumed for every answer. A captain
never schedules its own detach with a sleep or background timer; a timer cannot see that
new work arrived and stops the captain in the middle of it.

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
database, saving recovery refs before removal and retaining independent nested clones.
The same event-driven pass revisits retired lines and runs from Settings → Storage →
Clean up now; it never automatically retires idle open lines. A worktree
belonging to an open line is never swept.

Operational hierarchy rules ignore archived children, while purge ordering and restore traversal
continue to include them.

### Preserved worktree storage

Normal retirement removes a merged worktree even when it has uncommitted changes:
first it saves a recovery snapshot outside the checkout under
`<database path without extension>/worktree-snapshots/<repository hash>/<line slug>/<timestamp>/`.
Each snapshot has a 64 MiB cap and contains binary patches for staged and working
changes, a tar of untracked non-ignored files, and a manifest naming the original
HEAD and restore steps. The original index is never modified. The retirement
response's `worktree_snapshot` and a system notice on the archived line give the
snapshot directory. Snapshots are retained until a person removes them. The optional
orchestrator maintenance removes only clean, merged tasks. Unarchived dirty tasks keep their
working changes and ignored build files so they can be reopened, without
snapshotting or reclamation.

The automatic storage pass revisits retired and orphaned paths, including unmerged
history and worktrees this first pass kept. Clean, merged checkouts are removed
without adding recovery refs. It saves working files, staged files,
and available HEAD/branch/mirror tips with the forced-retirement snapshot machinery
under `refs/partyline/discarded/storage-<id>/` in each real owning repository, checks
the evidence again, then removes the checkout. Nested linked worktrees receive
recovery refs in their surviving owners before registered removal. Independent
nested clones, live/restart-planned attachments, uninspectable Git state, unsupported
files, failed recovery, and changing evidence keep the path with a reported reason.
See [storage](storage.md) for recovery commands, the one-click action and idle-line
inventory. Startup runs this same pass once; nothing schedules periodic sweeps.

Human credentials can `GET /api/worktrees` for paths, byte sizes, kept reasons,
and owning line names/IDs with `live`, `archived`, or `none` ownership. The listing
includes live managed worktrees for visibility; cleanup refuses them until the
line is archived. `POST /api/worktrees/cleanup` takes `{"path":"<listed path>"}`
and retries safe snapshot/removal or ignored-file reclamation. For a
worktree, `{"path":"<listed path>","force":true,"confirmation":"<listed path>"}`
preserves uncommitted changes in Git recovery refs before forced removal. Confirmation must
repeat the exact full path. Force anchors HEAD (including an unmerged detached tip)
in `refs/partyline/preserved-worktrees/` in the original repository before removal;
the response's `preserved_refs` names the recovery refs. Task mirror tips are also
preserved in their original repositories. Force never waives nested-repository
protection. These management endpoints are human-only. Settings → Storage provides
Clean up now for all safe cleanup and lists kept paths with their size and reason.


### Root decisions about obsolete descendants

The tree's root captain may explicitly retire a strict descendant with dirty files or
superseded unmerged history. This grants no self-retirement, sibling or cross-tree access,
and no extra authority to non-root captains. People have the same API option. The existing
guarded DELETE and merged-only `discard=true` behavior remain the default.

First read `GET /api/conversations/<id>/retirement-preview?include_children=true` (omit the
query for one line). It reports tracked/untracked/ignored paths and counts, unmerged SHAs
and subjects, host and fenced tips, live processes, goals, descendants, uploads and assets.
Its `required_flags` names every flag this plan needs — `force_discard` always, plus
`include_children`, `stop_processes` and `clear_goal` when the plan holds child lines, live
processes or an uncleared goal — so one response answers what to pass. A guarded refusal
returns the same list beside its `blockers`, and a forced refusal names every missing flag
in one `detail`; a caller never learns one flag per round trip.
A tracked path that Git stores as a blob is the line's own content: a committed symlink such
as `CLAUDE.md -> AGENTS.md` is accepted, even where the checkout holds a directory in its
place. Untracked directories (including embedded repositories), submodule gitlinks and
untracked special files are still refused as unsupported.
Paths and history are displayed at most 100 entries each, with truncation markers. A plan
is limited to 50 lines, 2,000 tracked/untracked dirty files and 256 MiB of those files across
the tree. Ignored files have a separate metadata-only scan capped at 100,000 files and 4 GiB,
so virtualenvs and dependency directories do not consume the recovery snapshot budget.
Individual small files are hashed up to 1 MiB, with a 16 MiB per-line hashing budget; larger
files use size, nanosecond modification/change times and inode. Large-file metadata cannot
prove unchanged content against a concurrent external writer.

After preserving deliverables, verifying read-back and recording the handoff, the root
decides: `DELETE /api/conversations/<id>?force_discard=true&preview_token=<token>`, adding
`include_children=true`, `stop_processes=true` and `clear_goal=true` explicitly as needed.
No human approval is required for this root decision. Native MCP `retirement_preview` and
`retire_child` expose the same fields. The token is bound to its principal, target and
subtree evidence; it grants no authority. Authority and state are checked again at execution.
A changed preview returns 409; fetch and assess a new preview rather than retrying blindly.

Before stopping any processes, all lines receive Git recovery commits made with a temporary
index and `git add -A` semantics, without stash or modifications to the real index. A separate
commit captures a copy of the real index, including bytes staged differently from working files.
Recovery refs live at `refs/partyline/discarded/<audit-id>/<line-id>/{index,snapshot,head,branch,mirror}`
(available tips only). A failed snapshot refuses retirement. **Ignored files are not backed
up**; the preview and audit list them. `snapshot` preserves the final tracked/untracked working
files; `index` preserves the independently staged files. A conflicted index refuses retirement
with a request to resolve or commit it first. Inspect either recovery tree with
`git show <recovery-ref>:<path>` or create a recovery branch from it.

Ignored nested linked Git worktrees may be removed only when HEAD is attached to a
branch and both working files and index match the line's private mirror tip (or host
HEAD when no mirror exists). The mirror tip must be equal to, or an ancestor of, a
local branch in the owning repository outside the retiring folder; a captain's direct
merge therefore counts even without task acceptance. Without a mirror, the owning
branch must still preserve HEAD. Their commits remain reachable in that surviving
repository. Evidence records the path, `nested-worktree`, host HEAD SHA and branch,
plus the mirror tip SHA when present; a changed mirror tip invalidates the preview.
After removing the folder retirement runs `git worktree prune` in the owning repository.
Removal keeps each linked checkout registered until its directory is gone; an interrupted
removal can leave files missing but preserves Git's HEAD and index for inspection and retry.
A legacy orphan with a missing registration is refused: preserve any unfinished work, verify
the assigned branch is an ancestor of main, then remove the directory manually and run
`git worktree prune` and `git branch -d <branch>` in its owning repository.
Detached worktrees, owners inside the retiring folder, mirror tips absent from owning
branches, and uncommitted edits beyond the mirror tip are refused with the path and
specific reason. Unsupported directories, FIFOs, sockets and devices are refused with
the path and kind; independent nested clones remain protected.

Retirement checks the whole selected subtree, then removes owned worktrees and host branch
refs deepest first. Recovery refs remain; private fence mirror refs are also retained.
A guard refusal has no side effects: every flag and every Git inspection runs before any
process is stopped or worktree removed. An operational failure during removal can leave a
partially removed directory, but its registration remains until the directory is gone.
A host branch a task's own preservation has already advanced
to the line's accepted tip is no longer the unchanged ref inspection found: retirement keeps
it beside the recovery refs instead of deleting it, rather than failing after the worktree is
already gone.
Explicit stopping may interrupt mid-turn work, but an unconfirmed stop refuses deletion.
State is checked after snapshots and process stops. During execution this server refuses new
Partyline writes, staffing, acceptance and child creation on selected lines. These guards
serialize forced retirement requests, not arbitrary host filesystem writers. A failure returns completed
and pending IDs plus recovery refs. Completed lines cannot be rolled back; a failure after
worktree removal can require restoration from its recovery ref. Remaining lines stay intact.

Uploads/messages remain intact. As in ordinary archive, forced retirement removes line temporary
directories, runs the legacy temporary sweep once, and prunes clean auxiliary review/scratch
worktrees. Only auxiliary worktrees with a non-empty `git status --porcelain` are retained:
their paths appear in the preview, audit and response's `preserved_paths`. They are exempted
from startup sweeping while retained. Explicit purge releases their exemptions; deleting an
auxiliary worktree's record also clears its exemption. A later forced retirement reassesses
the line's auxiliary worktrees and removes any that are now clean. Preserve intended deliverables
outside these locations before cleanup. Retirement is not purge, which destroys uploads too.
Every auxiliary preview entry also names its HEAD and whether that commit is unique (not
reachable from any existing ref). Changed auxiliary HEADs invalidate the preview. Before a
clean auxiliary checkout is removed, its HEAD is saved under
`refs/partyline/discarded/<audit-id>/<line-id>/aux/<table>/<n>` even when already referenced.
These refs appear in the response and audit and keep detached unique commits reachable.

`retirement_audit` stores the principal, target, decision, flags, complete bounded plan,
discarded paths/SHAs, recovery refs and failure outcome independently of conversation purge.
`GET /api/conversations/<id>/retirement-audit` returns the latest 20 records to callers who
can read that line. Recovery references and preservation records require deliberate later
cleanup; this feature never garbage-collects its recovery copies.

## Approvals at the root

Requests that need a person bubble to the root. A write-set, memory-cap or restart request
filed on a child line posts its ordinary notice there plus one `⚑ approval pending` line on the
tree's root, naming the line, the requester and (when a captain can decide) the approve and
decline calls, and @mentions an eligible ancestor captain only when that captain may decide
every path. If no ancestor captain can grant the full request, the notice says a person decides
and has no captain mention or unusable links. The person talks to the
root captain and never reads sublines. The one-click banner on the filing line and every
ancestor updates live when a request is filed or decided. A request filed on the root itself does not bubble, and
the staffing wake line counts what is still waiting anywhere below:
`approvals pending: N («line» write-set, «line2» memory)`, falling as each
request is decided. On the root line the person doesn't even need the
notices: `GET /api/conversations/<root id>/approvals` (people only) lists
every pending request in the subtree — kind, line, requester, detail, and
the approve/decline endpoints — and the root line's one-click approvals
banner renders exactly that list with **Approve** and **Decline** buttons
per row. A multi-path write-set request is one decision; later filings merge into it, and
already-granted paths are omitted with an explicit `already_granted` response. A write-set row
that needs a person has no captain decision links in its notice. Approve returns the grants and their
`granted_at` timestamps. Task `wait_reason` clears on request decision, `blocked(reason)`, or
`resume_work(note)`; a new `waiting(reason, seconds)` replaces it. A write-set row also carries `deny`, the machine-callable
`POST …/deny {"reason"}`: a captain decides a child's write-set request itself
when every path lies inside a grant its own line already holds or inside its
own writable checkout (including `.git` carve-outs, `.review/` and `.scratch/`), and declines with
a reason as easily as it approves (see `docs/write-fence.md`, Scope expansion).

Work goes down, not sideways. Once a line has a child, a machine may no longer
attach processes to that line: the root captain that could not staff a child
otherwise hands the job to a sibling on the root line, in the checkout the
child lines are already editing. Presets double as handles, so the same preset
used twice in one tree used to collide with a 409 that read as "cannot staff";
the server now suffixes the handle (`grok-2`) and the agent helper prints the
server's reason on every failed request. The same is true of captains: a
`can_manage` preset may hold one live instance per line, and the staffing
line keeps counting it as free until its `max_instances` is reached — a
preset declaring `max_instances: 3` with one captain running shows as
`astra (2 more)` — so a scarce captain preset stops pretending to be spent.
An explicit auto-compact threshold rides the same seam: a preset declaring
`auto_compact_tokens: 80000` spawns its process with that window — Claude
Code reads it from `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, codex from a
`-c model_auto_compact_token_limit` override — and 0 leaves the CLI's own
tuned default alone.

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
from. `POST /api/conversations/<root>/tasks` (and the `create_task` tool) takes
`"base":"upstream"` too (default `"head"`), which is how a machine root captain
starts a task from a checkout that is behind: each repository under the root's
folder is cut from its own fetched default upstream, `base_sha` is that commit,
and a repository with no upstream fails the whole placement with a 409.
For a child line the default stays `base:"checkout"`: the child branches from the parent
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
`{"accepted_sha", "tip_sha", "ahead", ...}` — where the line's branch ref and
its real working tip point. The branch ref visible outside the fence,
including `git rev-parse line/<name>` from the main checkout, advances only
on accept, so it lags the line's actual work; read `tip_sha` for that (it
falls back to `accepted_sha` when no mirror exists, and `ahead` states the
commit count outright, so "two commits ahead" needs no git). `branch_sha` and
`fenced_tip` are older names for the first two values, kept for
compatibility. Reading the fenced tip before accepting instead of learning it
from a 409 remains the point. Accepting
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

Locked JavaScript packages get a local `node_modules` in the review checkout:
verified matching npm installations are linked for reading, with writable caches
kept local. This avoids copying dependency trees or sharing writable hard links.
When the installed state cannot be verified, the package manager installs from
the lockfile inside a restricted sandbox with lifecycle scripts disabled. If a
package needs those scripts, the install or later build may fail; report that to
the captain. Reviewers run the package's tests and build in the checkout. A
package that writes inside its linked installation can be refused by the fence;
report that failure. The checkout stays under the repository because its own
local `node_modules` stops Node's upward search, and its location preserves the
existing review fence and lifecycle. Install failures and timeouts are reported
to the task and captain before review.

## Scratch worktrees

Review checkouts are for adversarial review; verifying an integration of
multiple changes needs a separate build checkout. `POST /api/conversations/<id>/scratch-worktrees`
with `{"sha":"...", "repository":"<abs path>"?}` checks the SHA out detached
and **writable** at `<repo>/.scratch/<full sha>` — same subtree rule, same
creation permission, recorded on the calling line. The fence binds a line's
recorded scratch checkouts writable, so the line's own process builds there
without a write-set request; review checkouts remain separate.
`GET …/scratch-worktrees` lists them, `DELETE
…/scratch-worktrees/<sha>` drops one early, and a scratch checkout is pruned
when the line retires or is purged and swept at startup when its record or
its line is gone — it is never pruned by an accept, because integration
checks follow the accepted work. The startup sweep owns only full-SHA
directories under `.scratch`. A scratch checkout can also start from a
**trial merge**: `{"sha": "<candidate>", "merge_onto": "main"}` starts at
`main` as the host sees it and merges the candidate in with `--no-ff` under
a fixed partyline identity — the integration check in one call. The response
carries `merge: {"onto", "result", "conflicts"}`; on conflicts the merge is
aborted, the checkout is left clean at the ref, and the 409 detail lists the
conflicting paths. Trial-merge checkouts are recorded as
`<sha>-onto-<onto sha>` and swept like any other.

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
`res://` tables are checked in the tree they ship from. Plain path roots work
the same way: `path_roots: ["", "game/"]` is tried in order for scheme-less
references, so `assets/ground/tile.png` is found under `game/assets/`. Prose
stays out of the scan: `skip_files` globs (such as `**/*.provenance.json`)
exclude whole tables, and `skip_keys` (such as `notes`, `reason`, `command`)
exclude string values under those keys at any depth. References resolving
through committed symlinks (mode `120000`) count as present; symlink loops
and links escaping the tree do not resolve and are reported missing. The
response carries `summary: [{"file", "missing", "checked"}]`, grouped by
table and sorted by missing count, so one real miss stands out among many
false ones. After an
accept, the response and the ☏ notice carry `tree_sync`: any worktree holding
the accepted branch must sit at the accepted SHA with a clean status — a
stale or dirty checkout is reported (`⚠ tree not in sync: …`) in the accept
response, never fixed automatically.

## Partyline docs for processes

Partyline's own documentation is readable over the API, in shelves rather
than one dump: `GET /api/docs` lists the categories (captaining, attachments,
review-and-accept, fence-and-write-set, memory-and-resources, restart,
best-practices, partyline-development, lessons), `GET /api/docs/<category>`
lists a category's topics, and `GET /api/docs/<category>/<topic>` returns one
section — sliced live from the repository's `docs/*.md`, so there is no second
copy to drift; a mapped heading that disappears is refused, not paraphrased.
People and every attached process read them on demand. Captains can also use
the MCP `docs_read` operation; that operation remains captain-only.

Each process has its own message counter and help pointer. A fresh binding
starts counting from its first wake, then the pointer rides roughly every N
line messages since that process's last pointer, never on consecutive wakes —
`docs_reminder_every_messages`, default 40, configures N. Captains are pointed
to `guide(topic="captain")` and `docs_read(category="captaining")`; workers,
reviewers, and ordinary participants are pointed to `guide(topic="worker")`
and `GET /api/docs`. The worker guide lists the caller's live non-captain
tools, including task and resource operations, and shows how to read a docs
topic through `guide(category=…, topic=…)`.

## Compaction as a line event

A worker's context compaction used to show only on its own screen. It is now
a line event on every adapter that declares a compaction capability (finding
2.13, extended in §5 of the findings doc):

- **`compaction_hooks`** (Claude Code): the harness's `PreCompact` hook
  posts `⚠ @<handle> compacted (auto, Nth time)` on the line and bumps the
  persisted counter; `SessionStart(compact)` folds a partyline re-briefing
  back into the worker's context.
- **`compaction_detect = "transcript"`** (Codex, opencode-v2): the adapter
  tails its own transcript or storage for the compaction record — Codex's
  `{"type": "compacted"}` rollout record, opencode-v2's `type='compaction'`
  row with `status='completed'` — and counts it once per activation, so a
  re-read transcript never double-counts. The re-briefing is delivered as a
  private wake message instead of hook stdout.

Both routes share the counter (shown as `×N compactions` in the staffing
line) and the thrash rule: the third `auto` compaction within five hook
turns rings the line's live captain once. Adapters without a capability
report nothing.

## The compaction limit: rotating a process to a fresh instance

Every compaction is a lossy summary of the last, so a process is allowed only a few. The
**maximum compactions per process** setting (Settings → Processes; `GET`/`PUT
/api/settings/max_compactions`, people only; default 2, `0` turns it off) bounds how many
compactions one activation may have. A preset may carry its own `max_compactions`: blank
inherits the instance setting, `0` turns the limit off for that preset only.

When a compaction brings the activation to the limit, or the thrash rule fires, the process is
*armed*. Nothing happens mid-turn. At the end of that turn, the harness receipt sends one private
notice asking for a hand-off note (notes tool, attachment scope: state, decisions, next step, paths
and SHAs, at most 4,000 characters). At the end of the turn that read the notice, or of any later
turn, the process is stopped and a **new CLI session starts on the same attachment**: same
handle, preset, line, lead flag, task role, bridge, notes and delivery cursor, a new runtime
owner and session. Its first briefing is the normal role briefing plus the goal, the hand-off note
(first, so the cap never cuts it), and the latest message that assigned it work; it is told to
continue, not wait. A process that ignores the notice is rotated at its next turn end with its last
note, and the line gets one notice saying who was rotated and why. Wakes queued meanwhile reach
the fresh instance. A restart request, a captain handover, or a server stop in flight defers the
rotation to a later turn end, so a captain keeps captainship and its pack. The only deadline is a
short one-shot grace after the receipt, so the transcript tail can post the turn's last words.
Wakes held during the last turn go to the fresh instance, and are flushed to the old one if the
rotation is abandoned. The rotation runs on the turn-end receipt, so it applies to adapters that
declare `turn_end = "receipt"` (all bundled adapters that report compactions do); an adapter without
one never ends a turn the server can see and is never rotated. Claude, pi and grok pin their session
to the attachment id, so a rotation gives the attachment a fresh `session_pin`; the others start a new
session on their own.
Every compaction re-briefing also asks the process to refresh its attachment note, so a rotation
never depends on a degraded process's final turn.

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
inside the same 4k cap — and the re-briefing ends with the nudge to update
them. A worker whose notes go stale (16 turns without a write, on adapters
that report turns) hears a one-line reminder on its wake every 8 turns.

## Captain-declared exclusive resources

Captains use the MCP `resources(conv_id, operation, name?)` operation to `list`,
`declare` or `remove` named resources on a line. Declaration is idempotent; every
resource has exactly one slot. A name is 1–64 letters, digits, dots or dashes,
starting with a letter or digit. Names describe any scarce resource, for example
`gpu` or `port-8000`; Partyline has no device-specific behavior. A child task resolves
its own line first and then the nearest ancestor declaration. Separate roots do not
share names. Remove refuses while a holder or waiter exists.

Task implementers and reviewers call `acquire_resource(name, note?)` before starting
a job that needs the resource. It returns `status: held` immediately if free, or
`status: queued`, a one-based `position`, and the current `holder`. A queued caller
must wait for its private “you now hold <name>; start your job” notice. Release with
`release_resource(name)` when done; this also cancels the caller's queued request.
Repeated acquire preserves the original note and FIFO position, and reacquiring a
held lease is a no-op. Notes are capped at 500 characters and each resource accepts
at most 64 waiters. These leases are advisory: they do not sandbox or stop a job.

The server grants the oldest surviving waiter on release. Detach, process exit,
replacement, archive and retirement remove an attachment's claims. Every grant checks
for missing or stopped attachments; a five-second sweep also repairs stale holders
and promotes waiters. Grant and its single private message are committed together.
Captain `resources` list and `process_overview` show each declaration, holder identity,
`granted_at`, note and FIFO queue, including free resources. Task callers can only
acquire/release for their authenticated attachment; they cannot declare resources or
release another process's lease.

The REST equivalents are `POST /api/conversations/<line>/resources` with
`{"operation":"list|declare|remove","name":"…"}` (captain/person),
`POST /api/task/resources/<name>/acquire` with `{"note":"…"}` and
`POST /api/task/resources/<name>/release` (task participants only).

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
detach. A lease may carry a `purpose` (up to 80 characters) so the staffing
line can tell a timing run from a habit:
`godot (exclusive, "timing walk") @sonnet «world-assets»`. `GET /api/leases` lists holders and queues, the staffing line shows
held leases (`leases: godot (exclusive) @sonnet «world-assets», 1 queued`),
and a captain's wake carries a host summary (cores, free memory, load) at
most once every ten minutes. Leases are taken and released by processes; a
person is refused.

## Declared gates

A line can declare the commands every hand-off must pass:
`PUT /api/conversations/<id>/gates` with
`{"commands": ["uv run --locked ruff check .", "./scripts/capped-test"],
"timeout_s": 1800}` (the line's captain, or a person; `GET …/gates` reads
them back). `accept` with `{"sha": "...", "run_gates": true}` then makes a
fenced scratch checkout at the SHA and runs each command there, in order,
under the process memory cap and the timeout, stopping at the first
failure: the accept is refused with 409 and
`{"gates": [{"command", "exit", "tail"}]}`, and on success the notice says
`(gates passed)`. On a host with no write fence the request answers 501 —
gate commands are never run unfenced inside the server.

## Detaching a task's workers on accept

A task line's workers never detach themselves, and an approved, accepted task's idle implementer and
reviewer keep costing context. `accept` with `{"sha": "...", "detach_workers": true}` records the SHA,
marks the task done, then stops both workers; the response lists them in `detached_workers`. Without the
flag nothing is detached, and `retire_child` (or `DELETE /api/attachments/<id>`) works either way.

## The goal

| Need | Operation |
| --- | --- |
| New orchestrator task | `create_task(name, goal, implementer, review)` |
| Change an active task's goal | `set_task_goal(conv_id, goal)` |
| Continue an approved or done task with a new goal | `reopen_task(conv_id, goal)` |
| New sub-captain line | `create_child(conv_id, name, goal)`; edit later with `set_goal(child_conv_id, goal)` |

`create_task` and `create_child` store the goal on the new child line. For task
operations, `conv_id` is the task line's ID, not the root captain's ID. For
`create_child`, `conv_id` is the parent; the returned ID identifies the child.
Each worker's briefing names its own line ID. Task implementers and reviewers
receive the stored task goal in their joining pack and on wakes until transcript
claim and cursor proof confirm delivery. An unchanged proven goal is omitted; a
change or the first wake after restart sends it again. `set_task_goal` also sends a durable
private message to each live task participant. Ordinary workers on captain lines receive assignments
from their captain; the manager goal rider and its captain-only framing are not sent
to them. Keep long briefs in a committed repository file visible at the child's
base, referenced in the goal; never park briefs in `/tmp` files.

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
`GET .../reports` returns at most `limit` reports (default 50, max 200), newest
first; `before_id` pages to older ones and `after_id` pages forward oldest first
(the two are exclusive). `GET .../reports/<report-id>` returns one report, 404 for
a report under another parent. The MCP `reports` tool and the `captain` op take
`operation` `list` (with `limit`, `before_id`), `get` (with `report_id`) or `post`.
Captain argument errors name the op, the unknown and missing fields, and the
accepted fields.
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

Two rules keep a *fresh* worker's hello from vanishing (finding 5.7). When
a process is replaced, the line's live captain is rung privately —
`↻ @<old> was replaced with a fresh instance (by @<who>) — assign now:
@<new> is ready and waiting for your @mention` — unless the replaced
process was itself the captain. And a worker's first message after attach
or replace, on a line with a live captain, is delivered to that captain as
a private copy when it doesn't already @mention them — once per
activation, so it can never become a chatter loop.

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

Sibling captains may talk without a relay: a captain may `POST
/api/conversations/<sibling-id>/messages` when both lines share the same
parent. The post is stamped with its line, so it reads `name via «line»`;
nothing else crosses — no attach, accept or assign on the sibling. A worker,
a cousin line and a root line get 403. To move one message verbatim instead of
retelling it, `POST /api/conversations/<src>/messages/<id>/forward {"to":
"<line id>", "note": "…"}` posts it to the target quoted as `↪ forwarded from
«line» — author said:`; it needs read on the source and write on the target.

### A mention that reached nobody

A mention can name a handle no live process wears: detached or exited, a process
on a line this speaker may not cross to, a former captain, or a name nobody
has. A person is told on the line, as before (`⚠ @name was mentioned but is not
attached — nothing was delivered`). An **agent** speaker is told privately, and
the notice **wakes it**: a line message wakes nobody, so an agent that ended its
turn on "@worker go build it" used to believe the work was handed off while the
line sat idle until a person noticed. One notice per spoken message is posted as
a private system message to the speaker, through the same path as the held-back
notice for another task's worker (`orchestrator_notices.tell`), so a speaker
that has already ended its turn is still rung. It lists every unreached handle
with its reason and the remedy:

- a task's worker (implementer or reviewer) that is detached or exited: the root
  captain revives it with `restart_implementer` / `restart_reviewer` with the
  task's `conv_id`, and `message_task(conv_id, text, to)` is read once it is back;
- a captain that is gone: the handle of the reachable captain to mention instead;
- a process on a line this speaker may not cross to: where it lives and whom to
  tell (the line's captain, or the root captain);
- a handle nobody wears: unknown, with the root captain to mention.

An unknown handle is a failed hand-off only when it plausibly was one. Agents write
`@dataclass`, `@scope/package` and the word "@mention" in ordinary prose, and a wake
over each of those makes the speaker apologise in public, which can trip the check
again. So a name that appears only inside a code span or fence is never reported, and
in a message that did reach someone (a live process, `@all`, or a person's handle) an
unknown name is reported only when this tree has worn that handle (it is real, just
not live where the speaker can reach) or when it is one slip away from a reachable
handle, with the suggestion (`did you mean @worker?`). A task worker's names go through
the same test. A message that reached nobody, or one already earning a notice for
another reason, still lists every unknown name.

The notice is a system message: routing it never produces another notice and the
return path never counts it as a request. Bridge messages and relay copies keep
their existing behaviour. Code: `unreached.py` (the collector and the reasons),
`mention_outcomes.py` (where a routed message settles).

| DO | DO NOT |
| --- | --- |
| Assign with a plain `@handle` from your own line when you manage the tree above it | Expect an implementer's `@parent-lead` to reach anyone — it is told to tell its own manager |
| Address one process per assignment and name the rest without `@` | Write `@sub-manager have @worker do X` — that rings the worker too, and on two lines |
| Treat a `did not reach everyone you mentioned` notice as a failed hand-off and act on its remedy | Wait on a handle the notice lists — nothing was delivered to it |
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

## Line bridges

Lines in one tree reach each other through the hierarchy. Lines in *different*
trees have no such path, so a person can open a **bridge**: a direct,
event-driven channel between one process on each line (the *ambassadors*). The
full contract is `docs/contracts/line-bridge.md`; the code is
`bridge_store.py` (rows), `bridge_service.py` (open and close),
`bridge_delivery.py` (speech), `bridge_routes.py` (API) and `bridge_pack.py`
(text).

- **Only a person opens or closes one** (`POST /api/bridges`,
  `DELETE /api/bridges/<id>`); a process token gets 403. A bridge is refused
  with 409 for lines in one tree, a line that already has a bridge, a
  non-live ambassador, or an archived line.
- **Speaking.** An ambassador's message containing `@[bridge]<peer>` is
  delivered whole to the peer as a private copy (audience = the peer, stamped
  `bridge_id`, forced wake). The ordinary `@name` regex never matches `@[`. A
  person's `@[bridge]` is ignored; a non-ambassador or wrong handle gets a
  private notice. A copy is foreign-sourced, so it is never relayed onward.
- **Hidden.** Rows with `bridge_id` are excluded from human transcript reads
  and the WebSocket fan-out (`message_visibility.py`), and from every
  digest except the copy's addressee. They stay in the table as an audit log,
  readable by a person at `GET /api/bridges/<id>/messages`.
- **Rate limit.** 30 delivered messages per side per 10 minutes; past that the
  sender is told privately and both lines get one "bridge paused" notice per
  window.
- **Closing.** A person, or automatically when either ambassador detaches,
  exits or is removed, or either line is archived. Each present ambassador is
  told, and each line gets one ordinary notice for the open and the close.
- **The pack** rides startup, resume and post-compaction briefings only while
  the bridge is open (`bridge_pack.pack_for`).

| DO | DO NOT |
| --- | --- |
| Let a process ask its people in plain text to open a bridge | Open or close a bridge from a process |
| Report anything people need in a normal message | Expect the other line's people to see your bridge message |

## Orchestrator captains and task lines

New root lines default to `captain_mode: "orchestrator"`; existing lines keep their
stored mode. A person can switch a root line between `orchestrator` and `manager_tree`
using `PUT /api/conversations/<root>/captain-style`. A child cannot be an orchestrator, and style cannot change
while children exist. The root's `default_review_policy` defaults to `captain`;
it may also be `none` or an exact reviewer preset name. A task's mode (full, light or
express) is chosen separately at creation (see Task modes below).

Preset role traits govern agent staffing: implementers need **Fast implementer**; captains,
sub-captains and reviewers need **Can manage a line**. Choose a free Fast implementer
for implementation. A person may attach, resume, replace or appoint a process directly
without those role traits; agents cannot staff presets with neither role trait. Helper processes (raw
adapters, counted in the worker total or not, such as the idle-check and rotate-captain helpers) hold no staffed role:
they need no role trait, and a captain can restart one with delete, edit command and resume. An agent
resuming any other process that is not a task worker, captain or helper still needs Fast implementer. When attaching a sub-captain, select the captain role; the server appoints it on a
vacant line. **Reads images** is advisory; prefer it for image and screenshot work. Existing
processes are not stopped when traits change, but subsequent staffing checks the current
preset. A named default review policy must satisfy the reviewer requirement; `captain`
and `none` remain available.

An orchestrator creates tasks through `create_task(name, goal, implementer, review)`.
The task goal is capped at 20,000 characters; longer briefs live in a committed file
that the goal names: see `docs/task-briefs.md`.
The server creates each task line in a managed worktree, attaches exactly one
implementer from the named preset and briefs it. Direct attach, including the
shared-branch override, cannot add an implementer. Task lines have no subcaptain
and cannot split further. `tasks()` returns every task's policy, status, round,
assigned attachment IDs, SHA, checkout path and merge state without reading chat.
GET `/api/conversations/<task>/task` reads one task; task participants retain their
role, current review SHA and request after compaction.

The implementer calls `request_review(sha?, what, where)`, or
`request_review(repositories=[{repository, sha}, …], what, where)` when the work spans
repositories (one to eight, each once; `sha` and `repositories` are exclusive). A
repository is admitted when this line or its subtree works in it: its checkout, an
attachment's folder or a write grant inside it. The task stores every `{repository,
sha, path}`; `sha` and `review_worktree` hold the first (primary) entry, whose checkout
is the reviewer's folder and stays first in later rounds. Each repository gets its own
stable `.review/task-<line id>` checkout, moved in place each round, and the round brief
lists every repository with its full SHA and path. `accept` fast-forwards the line's own
repository as before, verifies and records every other repository's reviewed commit, and
names them in the notice and the response's `repositories`. Without a SHA the server
uses the task's current fenced tip. Policies determine the next action:

- `none`: mark the task done and notify the root once.
- `captain`: create an exact-SHA managed review checkout and notify the root once.
  The root reviews and calls `review_verdict` with the task's `conv_id`.
- A reviewer preset: the server reserves a different reviewer attachment, moves the
  task's one review checkout (`.review/task-<line id>`, reset and cleaned) to the
  exact SHA, and starts the reviewer there. The implementer
  cannot select, attach or replace the reviewer. The same attachment and CLI
  session are resumed across rounds; launch failures without a session retry a
  fresh PTY under the same attachment identity. Reviewers never implement or push.

The reviewer's structured `review_verdict(approve | changes, findings)` drives the
state machine; prose is never a verdict. Changes wake the implementer and advance
the round count. There is no round cap. Approval marks the task approved and sends
one root report. **Reviewer approval is acceptance in orchestrator mode.** This is
a deliberate exception to the manager-tree rule that acceptance cannot be delegated.
The root reviews only captain-policy tasks and always owns merging and pushing.
`accept` records only the approved task SHA and refuses `allow_descendant` for tasks.

**Captain override of a staffed review.** The verdict belongs to the reviewer of
record, and an ordinary `review_verdict` call from anyone else — including the root
captain — is refused with 403. When the captain has already judged a result and
cannot wait on the reviewer, it records an **override** verdict:
`review_verdict(verdict, findings, override=true)` with the task's `conv_id`. The
flag is required, so nothing silently takes a review over; an ordinary call keeps
the reviewer-of-record refusal. Authorization is the live lead of the task's root
line and nobody else, and the call is refused when there is no open review, when
the task is already approved or done, or when the review never belonged to a
separate reviewer (a captain-policy task needs no override — the plain call already
works there). The override is auditable: the task row and `tasks()` record
`overridden_by` with the captain's handle for exactly as long as those findings are
the stored verdict — a new round, a later reviewer verdict, a blocked report, a
stall report or a reopen clears it with the findings they replace. The superseded
reviewer is told once, privately, that the captain overrode the review, with the
findings; a verdict it then tries to record can no longer land, because the review
it answered is closed. Rounds, status transitions, `previous_findings` and the
report text behave exactly as for a reviewer's verdict: `changes` returns the task
to implementing and wakes the implementer; `approve` approves it and reports once.

While review work proceeds, implicit return notices stay between implementer and
reviewer. A return notice does not create another return debt. The general idle-goal
guard does not wake orchestrators or task lines; structured terminal reports own
that wake path. Failed reviewer admission tells the implementer and root explicitly
and leaves the request retryable. Reviewers are ordinary managed PTY attachments,
so fleet restart plans include them alongside implementers. Terminal reports are
stored once per task and notification delivery is retried if the root is unavailable.

The root captain (the live lead of the task's `root_id`) retires finished task lines
through the normal archive and `retire_child` paths, including `include_children` and
`force_discard`, under the usual guards (unmerged work, live processes unless
`stop_processes`, goal, worktree safety). Task participants (implementer and reviewer),
captains of other trees and every other machine cannot archive or retire task lines.
After the approved SHA has been merged into the root's current checkout and the
whole task worktree is clean and merged, idle implementer/reviewer processes detach.
People may archive task lines. The optional global
[`auto_clean_task_history` setting](resource-budget.md#task-history-retention)
archives merged, approved/done task lines once no process is live and removes their
managed worktrees. It is disabled by default.

A reviewer that dies while its task is in review is revived by asking again
(`request_review`), by a person or the root captain (`POST …/task/reviewer`, the
`restart_reviewer` tool, or the button on the task line header), and once
automatically on its exit; a second exit reports to the root instead of looping.

A detached implementer (idle sweep, crash) is brought back the same way: a person or the
root captain calls `POST …/task/implementer` (the `restart_implementer` tool) on an
implementing, idle or blocked task. It resumes the implementer's own session where the
adapter supports it, tells it `resumed by <actor>; continue the task: …`, and hands the
return path from the root to it; `409` if it is still running.

After a server restart the restart plan reattaches previously attached task workers one at a
time, so a worker can be neither live nor detached for a while. Until the plan reaches it, the
staffing digest and `GET …/staffing` list it as `reattaching (queued)`, and `message_task`,
`share_ref`, `restart_implementer` and `restart_reviewer` answer `409` that it is queued for
automatic reattachment and to wait for the `sequential reattachment finished` notice, rather than
telling the caller to restart it. Only a truly detached worker gets the `restart_*` hint.

New work on an approved or done task is a reopen, never a chat hand-off: the root
captain or a person calls `reopen_task(conv_id, goal)` (`POST …/task/reopen`). The task
returns to `implementing` with the new goal, round 0 and cleared review, stall and
blocked fields; accept history, reports and the merge record stay. The implementer is
woken (resumed if detached) with the new goal. If the implementer begins a turn after a
message from the root captain or a person posted since the approval and the task was not
reopened, the root captain gets one private notice per approval; nothing reopens on its
own, so a "thanks" cannot reopen a task. Unrelated work goes through `create_task`.

A `blocked` task takes new direction without a reopen: the root captain or a person calls
`resume_work(conv_id, note)` (`POST …/task/resume`). It returns the task to `implementing`,
posts `note` to the implementer as a private message in the caller's name (the same path as
`message_task`), and hands the return path from the root to the implementer; the root gets no
`unblocked:` notice for its own act. The implementer still calls `resume_work(note)` itself
when it is working again; `blocked` stays implementer-only. An idle task, including one whose
stall has been reported, instead takes a nudge through `message_task`: the `resume_work` 409
names that operation and, when a declared wait is live, its reason. A refusal names who may
call the operation.

Task processes are named after their task, never their preset: the implementer is
`impl-<tag>` and the reviewer `review-<tag>`, where `<tag>` is the first six hex characters
of the task line's id (lengthened if a handle in the tree already uses it) and is stored
on the task row. The preset lives on the attachment's `preset` column, so cards and
staffing still show it. Tasks created before this keep their old handles. The root captain
or a person messages a task's workers with `message_task(conv_id, text, to)` (`POST
…/task/message`, 409 when that worker is not live) instead of @mentioning a handle. The
`conv_id` may also be the task's tag, its `impl-`/`review-` handle, or its line name; a name
matching two tasks is refused with 409. The same names resolve for `resume_work`, `reopen_task`
and the restart routes, and `GET /api/capabilities?conv_id=` resolves them for the captain ops
(every op but `retire_child`, which stays id-only; an unknown ref is a 404 `no line or task matches '<ref>'`,
never a "not authorized"). `detach_worker` and `appoint_lead` accept a process handle such
as `impl-48da9d` on the target line in place of an attachment id. `detach_worker` of a worker no longer
attached there (an implementer `accept` already detached) is an idempotent success,
`already_detached: true`, since the captain's goal is met; a ref no attachment on that line carries
(a typo, or another line's handle) is refused naming the line. A
root-captain mention in a task line of a process on a different task line is held back with
a private notice naming this line's handles.

An implementer that cannot proceed calls `blocked(reason)`. This sets the task's
status to `blocked` and sends a deduplicated notify report to its root. Calling
`request_review` resumes implementation and clears the blocked state before the
review attempt. When an implementer returns without a structured result and has
no reviewer peer, the server rings it once to call `request_review` or
`blocked(reason)`. That one reminder is built from the line's own workspace
state instead of a fixed line, and it reads the line's fence mirror first: a
worker commits there until accept, so from outside its own worktree still reads
as modified. A commit past the base names the full SHA to request review with
(plus any further edits to commit first), uncommitted changes say to run the
gates and commit, and an unchanged workspace names `blocked(reason)` and
`waiting(reason, seconds)`. It stays one message per stage, and a workspace that
cannot be read falls back to the generic text. If the turn consuming that
reminder also returns without either, the server sends one `stalled` report to
the root. Duplicate turn receipts and restarts do not repeat the reminder or
escalation. The rail shows blocked tasks, and task lines hide manual staffing
controls because staffing is owned by the server. Notify reports follow the
existing inbox coalescing and acknowledgement rules: a new task state updates
an outstanding report rather than ringing again.

An implementer waiting on a long command — a test run, a build, a monitor — calls
`waiting(reason, seconds)` (60–3600, default 900) instead. The server records the
wait on the task row and posts one `waiting, not stalled` note on the line: a
hand-off is not due yet, and the root is not paged. While the wait is live the
implementer is not reminded and never reported as stalled, and an implementer
whose harness turn is still open — a tool call in flight — is never stalled
either. The wait only defers the check: when it runs out the task owes a hand-off
again and gets the same single reminder, never a skipped straight to a stall
report. A wait is a structured statement, never prose: a chat message saying
"still waiting" waits for nothing.

## Task modes: full, light and express

`create_task(..., mode="full"|"light"|"express")` picks how much process a task carries. The
mode is fixed at creation (`reopen_task` keeps it) and shows as `mode` in `tasks()`, on the
task row and as `task_mode` in the conversation payload, which the rail and the task header
render as a colour-coded icon with a tooltip (bolt for express, feather for light, shield for
full); lines that are not tasks show none.

- **full** (default) is the review cycle described above, with every gate in `AGENTS.md`.
- **light** is the same review cycle and the policy as given, but gates scale with the diff.
  The one mapping from changed paths to gate commands is `partyline/task_gates.py`
  (`uv run --locked python -m partyline.task_gates [path ...]`, default: the diff against
  main): docs, markdown and skills only run none; Python runs ruff plus the tests that
  touch the changed modules; `frontend/` runs `npm run verify && npm run build`; a path or
  module the table cannot place falls back to the full gates. CI and the required checks on
  main are unchanged. The light task pack points the implementer at this helper.
- **express** has no reviewer and no review cycle, for mockups, explorations, assets and
  one-off investigations. Its policy is forced to `none`; `create_task` refuses any other
  `review` with 422. The implementer ends with `deliver(what, where)`
  (`POST /api/conversations/<task>/deliver`): text only, no SHA. That posts the terminal
  report to the root captain and marks the task `done`; no SHA is read, so the
  unverified-SHA warning never fires. `request_review` on an express task is refused with
  409 (`express task: no review — report results with deliver(what, where)`), and `deliver`
  on any other task with 409. `blocked`, `waiting` and `resume_work` work as before.
  Merging an express task's commits is not supported: use light or full for that.

## Captain handover

After completion, the old captain is detached and removed from the line roster.
The handover record and line messages remain; interrupted removal is retried after restart.

Staff a successor on your own line with `attach_worker` and `successor=true`, then wait
60 seconds. This attachment is not an implementer; only one live successor may be
staffed at a time. A captain can use `offer_handover(attachment_id, debrief)` to offer its role to
another live attachment on the same line after that attachment has been held for
at least 60 seconds. The debrief is required and limited to 4000 characters;
refer to files, directories, notes, worktrees and report IDs. The receiver hears
the marked offer and can call `accept_handover(handover_id)`; the old captain
can call `cancel_handover(handover_id)` while it is offered. Only one handover
may be pending per line. An offer expires after 15 minutes, including across a
server restart. A captain must resolve or cancel its pending restart request
before offering or accepting a handover.

Acceptance atomically transfers captainship, any open bridge ambassador role,
heartbeat, and pending write-set and memory-request receipt targets. Reports
and tasks are line-owned. Resource leases and attachment notes remain with their
original process. The old captain remains attached as an ordinary participant while handing off;
the new captain receives the captain pack. Both participants call
`complete_handover(handover_id)`, in either order. Once both confirm, completion
and a detach intent are recorded atomically; the server stops the old captain
through the normal detach path and retries unfinished detaches after restart.
The reply names the real state: `completed`, `old_captain` (`attached`, `gone`, `detaching` or
`detached`), who is still `awaiting`, and a `message` in words; a half-confirmed reply is
`from_done`/`to_done` true for one side only, so read `completed` first. If the old captain has
already left (detached, exited or removed) its confirmation can never come, so the new captain's
confirmation completes the handover. A one-sided confirmation never detaches the old captain. After 30 minutes the
line receives one notice naming who has not confirmed. A person can resolve a
stale handover with `POST /api/conversations/{conv_id}/handover/resolve` and
`{"handover_id":"…"}`; this releases the pending slot without detaching the old
captain. A person may detach it separately if appropriate.

Before either completion confirmation, the server inventories the outgoing captain's
live descendants (excluding its CLI and configured MCP service processes), including
available memory-scope members. MCP commands come from the attachment's config;
jobs started by those services still count. Process inventory runs in a worker
thread before the database transaction. Rider/briefing text uses a five-second
cache, refreshed off-loop; inspection failures appear as unavailable state text.
Offer and accepted state text show each job's pid, command, cwd, and observed
cwd/open files under the outgoing attachment's temp directory. Linux reads `/proc`, macOS asks `ps`
and `lsof`, Windows asks CIM and has no working directory; a field that cannot be read says
`command unknown` or `cwd=unknown` with the reason, never a bare `?`. A live job makes
completion return 409 before recording that confirmation or creating a detach intent.
Finish or kill each job, or explicitly call
`complete_handover(handover_id, live_jobs="transfer")`. Each confirmation with live
jobs needs this acknowledgement; completion inventories again, so jobs started
between confirmations are checked too. The successor receives a system notice
listing the jobs and retained paths. Transfer acknowledges the jobs and preserves
their files; the normal detach signals still apply.

Retained temp directories become line-owned through a private, durable manifest in
`<instance>/.pending-reaps/<old-attachment-id>.json`. They stay at their original
absolute paths, with a `TMPDIR/retained/<old-attachment-id>` link under the successor's
temp directory where directory symlinks are supported (otherwise use the original
retained path). Attached processes run as the server user, so they can read and write
these private directories. Keeping the original directory avoids breaking inherited
TMPDIR values and absolute redirects; it also preserves cwd-relative writes without
a cross-filesystem copy or rename. The manifest records process identities, not only
pids, and survives roster removal and restart. Copy deliverables to durable project
storage before the jobs finish: these files remain temporary.

Every attachment temp reap checks Linux server-user processes' cwd and open fds.
Readable cwd/fd holders and acknowledged live jobs defer cleanup. Before detach,
the server durably captures the attachment's process tree and scope; incomplete
inspection of those owned processes also defers cleanup. Permission denial from
an unrelated process does not pin the directory. Ownership snapshots in
`<instance>/.tmp-owners/<attachment-id>.json` keep earlier activation scopes until
cleanup and are removed with the reaped directory. Pending cleanup also waits
while the attachment is active. Other platforms conservatively
defer when they cannot prove the directory unused. Async cleanup routes run the
process scan and reap in worker threads.
Maintenance retries pending reaps every 30 seconds, even after the attachment row
has gone. A handover without live jobs or temp holders follows the usual immediate
detach and cleanup path.

On POSIX, detach currently signals the attachment's original process group with
TERM then KILL, and confirms that group exited. It does not stop the entire systemd
memory scope. A child that starts a separate session/process group can survive;
this handover change does not alter those kill semantics.

When an implementer requests review of different commits while a review is open,
Partyline moves the review checkouts and records the old and new SHAs. After this
re-pin, a verdict must explicitly identify the current SHA using `sha`, or, for
multiple repositories, list every current `{repository, sha}` in `repositories`.
A stale or missing identification is rejected with the current SHA; the reviewer
must review the new commits before retrying. Explicit SHA identifications are
checked even when the review has not been re-pinned.


Captains must not end a turn promising future work unless something will wake them,
such as a live worker, a task wait or a scheduled deadline. Otherwise they must do
the work now or tell the person plainly what blocks them.
At a captain turn end, Partyline warns the line and privately wakes the captain if
structured open work remains but nothing is running or scheduled. The captain should
restart, reopen or resume the work, or tell the person what it is blocked on. An unchanged idle verdict is reported only once.
Only live lines count: a retired line's task and its unread reports are history. The
alert names the first five items and counts the rest.
