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
same worktree. Do not re-prompt it — the summary it kept is not under your
control, and the next compact loses your acceptance criteria again.

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
hides, which is exactly the `out/` incident. After accept, read `tree_sync`
in the response: a worktree left dirty or behind is reported there and as a
⚠ in the ☏ notice.

## Merge main by a verified SHA

A fenced line cannot see the parent's current main. Merge main by a SHA
pasted in chat after verifying ancestry, or ask the root captain for the
current main SHA. Never merge from a stale belief about where main is.

## Reactions instead of acknowledgements

Every @ spends a turn and a wake. Acknowledge with a 👀 reaction, not a
"standing by" message, and never trade thanks between processes. A reaction
on a machine's message reaches it privately; it wakes nobody unless it
raises something new.
