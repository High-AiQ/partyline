---
name: adversarial-review
description: Review a Partyline pull request or patch adversarially at an exact commit. Use when asked to clear, approve, audit, or find blockers in a proposed change before merge.
---

# Adversarial review

Review the artifact that could merge, not a mutable branch or another participant's checkout.

## Pin the review

Resolve the exact commit SHA named by the coordinator. Create a unique disposable worktree at
that commit; never review in the shared workbench:

```bash
git fetch origin
git worktree add /tmp/<reviewer>-r<pr> <full-sha>
cd /tmp/<reviewer>-r<pr>
```

Confirm `git rev-parse HEAD` equals the assigned SHA before reading the diff or running gates. If
the assigned SHA is unavailable, stop and report that blocker instead of substituting the current
PR head. Treat a replacement SHA as a new artifact: state which prior verdict it supersedes and
re-drive the changed delta plus any affected invariants.

## Drive the change

Read the complete diff from its intended base, then inspect the surrounding production paths and
tests needed to challenge the change's claims. Run the repository gates relevant to the review;
do not claim a command that was not actually run. Mutations for evidence inside the disposable
worktree are encouraged — for example, swap in an old file to prove a regression test fails on
prior code. Do not fix the change under review unless the coordinator explicitly assigns it.

Separate merge blockers from scoped, non-blocking observations. A clear verdict means the exact
reviewed SHA satisfies the stated bar; it never transfers implicitly to a later commit.

## Report evidence

Every verdict must include:

- the exact reviewed SHA;
- the throwaway worktree used;
- the commands actually run and their results;
- each blocker with the failing path or invariant, or an explicit clear/approve result.

After the verdict is recorded and no artifact is needed, remove the disposable worktree with
`git worktree remove /tmp/<reviewer>-r<pr>`.
