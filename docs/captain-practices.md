# Captain practices

What a captain is for, drawn from the 3d-game findings of 2026-10-11: the
practices that kept that tree trustworthy, written as instructions.

## Brief short, contract long

Keep the child's topic short and put the long brief in a repo file at the
child's base — `docs/contracts/<line>.md` works well — then name that file
in the topic. The goal rides its manager's every wake and the topic is
standing context for everyone there; a captain cannot read your line, so
what is not in that brief it does not know.

## Assign in small pieces

Files by name, scoped test runs, one acceptance criterion per message. A
worker told to "improve the tests" thrashes; a worker told "add cases for X
in tests/test_y.py and run only that file" lands. Context is the scarce
resource: a captain that rations it well replaces fewer workers.

## Replace a thrashing worker

Three compactions in three turns means the assignment does not fit the
context: replace the worker with a fresh instance of the same preset and the
same worktree — `POST /api/attachments/<id>/replace` with a reason; the
fresh instance keeps the captain role if it held one and starts from the
re-briefing. Do not re-prompt it — the summary it kept is not under your
control, and the next compact loses your acceptance criteria again.

## Hand over captainship

Staff a successor on your own line with `attach_worker(successor=true)`, including
when the line has children or a worker. Wait 60 seconds, then use `offer_handover`
to offer captainship to that live attachment. `accept_handover` accepts and
`cancel_handover` cancels an offer. Reference files,
directories, notes, worktrees and report IDs in the debrief. Resolve or cancel
your pending restart request first. Both participants confirm with `complete_handover`; the server detaches the
old captain only after both confirm. See [captain handover](hierarchy.md#captain-handover).

## Visual acceptance needs eyes

Know which presets can read images or audio. A contract whose acceptance
names screenshots or clips needs a captain or co-reviewer that can actually
perceive them; "verified structurally" is not verification of a visual
feature.

## Read the tip, then accept

Before accepting, `GET /api/conversations/<id>/tip` shows the branch and the
fenced tip — never learn the tip from an accept refusal. When the line's tip
has moved past the SHA you reviewed, accept with `{"allow_descendant":
true}`: it fast-forwards to that newer tip and the notice counts the commits
that went in unreviewed. Read that count before you record the hand-off.

## Let the machines check first

Run the deterministic pre-review check before you review:
`POST /api/conversations/<id>/prereview` with the SHA and the data paths —
it finds referenced files that never reached git, including ones a gitignore
hides, which is exactly the `out/` incident. Tune it to the repository so
the misses are real: `path_roots` (such as `["", "game/"]`) for tables that
spell paths relative to a project folder, `skip_files` globs and `skip_keys`
for provenance prose, and read the `summary` — misses grouped by table —
before reading the flat list. After accept, read `tree_sync` in the
response: a worktree left dirty or behind is reported there and as a ⚠ in
the ☏ notice. Declare the line's gates (`PUT …/gates`) and accept with
`{"run_gates": true}` to have those commands run fenced in a scratch
checkout at the SHA before the branch moves. For a build against today's
main, open the scratch checkout as a trial merge:
`{"sha": "...", "merge_onto": "main"}` — conflicts come back as a 409 with
the paths, nothing half-merged.

## Merge main by a verified SHA

A fenced line cannot see the parent's current main: its ref view is a mirror
refreshed only at launch. `GET /api/conversations/<id>/base` reports the
parent branch as the host sees it and how far behind the line is, and `POST
/api/conversations/<id>/refresh-base` re-copies that ref into the line's
fenced view, so `git merge <branch>` inside the line resolves to today's
main. Merge by that verified SHA — never from a stale belief about where
main is. An accept on a line refreshes its children's views automatically.

## Retire finished descendant lines

After durable preservation and handoff, retire finished children through the API or native
`retire_child`. A root captain can inspect `retirement_preview`, assess dirty files and
superseded commits, and explicitly use `force_discard` with its `preview_token`; add
`stop_processes`, `clear_goal` and `include_children` only when intended. The preview's
`required_flags` already names every flag the plan needs, and a refusal repeats them all at
once — read it before calling, and a refused call changes nothing. The root makes this
decision without requesting human UI cleanup. Recovery snapshots retain tracked/untracked
files; ignored files are lost. Non-root captains retain guarded retirement. See
[root retirement decisions](hierarchy.md#root-decisions-about-obsolete-descendants).

## Reactions instead of acknowledgements

Every @ spends a turn and a wake. Acknowledge with a 👀 reaction, not a
"standing by" message, and never trade thanks between processes. A reaction
on a machine's message reaches it privately; it wakes nobody unless it
raises something new.
