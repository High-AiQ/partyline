---
name: adversarial-review
description: Review a Partyline pull request or patch adversarially at an exact commit. Use when asked to clear, approve, audit, or find blockers in a proposed change before merge.
---

# Adversarial review

Review the artifact that could merge, not a mutable branch or another participant's checkout.

## Pin the review

```bash
git fetch origin
git worktree add /tmp/<reviewer>-r<pr> <full-sha>
cd /tmp/<reviewer>-r<pr>
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
| Mutate inside the disposable worktree for evidence — e.g. swap in an old file to prove a regression test fails on prior code | Fix the change under review unless the coordinator explicitly assigns it |
| Separate merge blockers from scoped, non-blocking observations | Blur findings into one undifferentiated list |

## Report evidence

A clear verdict means the exact reviewed SHA satisfies the stated bar.

| DO | DO NOT |
| --- | --- |
| Cite the exact reviewed SHA and the throwaway worktree used | — |
| List the commands actually run and their results | — |
| Give each blocker its failing path or invariant, or an explicit clear/approve result | — |
| Remove the worktree (`git worktree remove /tmp/<reviewer>-r<pr>`) once no artifact is needed | Leave disposable worktrees behind |
