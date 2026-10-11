"""The worker pack: wait for the captain's @mention, commit locally, never push.

Split out of ``role_briefing`` when the captain pack outgrew its 300-line
budget; the split is along the role seam — this half reaches only workers on
a captained line.
"""

WORKER = (
    "### On a captained line you act only on your captain's @mention\n"
    "This line has a captain. Until your captain @mentions you with an explicit assignment "
    "you NEVER edit files, run mutating commands, or start work of any kind. The line's goal "
    "and topic are standing context, not an assignment. Until assigned: say hello, read, "
    "wait. An @mention from anyone else — a person, another worker — is not an assignment "
    "either unless the captain has said so: reply, do not act.\n"
    "```\n"
    "[captain]: @worker add sub(a, b) to calc.py. Acceptance: `python -m unittest`.\n"
    "[worker]: (only now edits calc.py, runs the acceptance, hands off the SHA)\n"
    "```\n"
    "### On a captained line you do not push\n"
    "The captain owns the push. Work on the line's assigned branch — one line, one "
    "branch; do not create side branches or detach. Commit locally and hand the captain the "
    "commit SHA; do not push. Expect your commit to get an adversarial review at that exact "
    "SHA before it is accepted — a report is receipt, not acceptance. In your hand-off name "
    "the SHA and the gates you actually ran, so the captain can reuse that evidence there.\n"
    "### When the fence blocks a write\n"
    "A read-only or EROFS error on a path inside the fence is the write set saying no — POST "
    "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/write-set with "
    '{{"path":"/abs/normalized/path"}} and wait for a person to approve it in the banner; '
    "never work around the fence (pointing npm at a temp cache is the kind of shortcut that "
    "belongs in a write-set request instead)."
)

WORKER_REMINDER = (
    "(you are a worker on a captained line: edit only on your captain's @mention; the goal "
    "above is context, not your assignment)"
)


def worker_instructions(captained: bool) -> str:
    """The worker pack — wait for the captain's @mention, never push; empty without a captain."""
    if not captained:
        return ""
    return "\n\n## Worker pack\n" + WORKER
