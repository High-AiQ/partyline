---
name: adversarial-review
description: Review a Partyline pull request or patch adversarially at an exact commit. Use when asked to clear, approve, audit, or find blockers in a proposed change before merge.
---

# Adversarial review

Review the artifact that could merge, not a mutable branch or another participant's checkout.

## Pin the review

Create the review checkout through partyline, never a raw `git worktree add` — partyline
records it on the line and prunes it when the work is accepted or the line retires:

```bash
# API (a credential with read on the line):
curl -X POST "$PARTYLINE_API/api/conversations/<line-id>/review-worktrees" \
  -H "Authorization: Bearer $PARTYLINE_TOKEN" -H "Content-Type: application/json" \
  -d '{"sha": "<full-sha>"}'

# CLI (shell access, no credential for that line):
uv run --locked python -m scripts.review_worktree \
  --database /absolute/path/instance.db create \
  --conversation <line-id> --sha <full-sha>
```

Both answer with the checkout path, `<repo>/.review/<full-sha>`, detached at the exact SHA:

```bash
cd <repo>/.review/<full-sha>
```

| DO | DO NOT |
| --- | --- |
| Resolve the exact commit SHA named by the coordinator | Review in the shared workbench |
| Confirm `git rev-parse HEAD` equals the assigned SHA before reading anything | Substitute the current PR head when the assigned SHA is unavailable — stop and report that blocker |
| Treat a replacement SHA as a new artifact: state which verdict it supersedes and re-drive the changed delta plus affected invariants | Carry a verdict forward implicitly to a later commit |

## Drive the change

Read the complete diff from its intended base, then inspect the surrounding production paths
and tests needed to challenge the change's claims.

| DO | DO NOT |
| --- | --- |
| Run the repository gates relevant to the review | Claim a command that was not actually run |
| Reuse a recorded gate or test result only at the same unchanged exact SHA, and re-run any gate a finding warrants | Carry a recorded result to a new SHA, or skip a gate the review needs because a result already exists |
| Mutate inside the disposable worktree for evidence — e.g. swap in an old file to prove a regression test fails on prior code | Fix the change under review unless the coordinator explicitly assigns it |
| Separate merge blockers from scoped, non-blocking observations | Blur findings into one undifferentiated list |

## Report evidence

A clear verdict means the exact reviewed SHA satisfies the stated bar.

| DO | DO NOT |
| --- | --- |
| Cite the exact reviewed SHA and the throwaway worktree used | — |
| List the commands actually run and their results | — |
| Give each blocker its failing path or invariant, or an explicit clear/approve result | — |
| Leave the managed checkout to partyline — it is pruned when the line retires or the SHA is accepted (or `... prune --conversation <line-id>` via the CLI) | Leave disposable worktrees behind |
