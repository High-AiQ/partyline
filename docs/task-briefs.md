# Task briefs: the goal is a pointer, the brief is a file

`create_task(name, goal, implementer, review)` accepts a `goal` of at most
**20,000 characters** (`MAX_TASK_GOAL` in `partyline/goal.py`). `set_task_goal` and
`reopen_task` share that limit. Captain-line goals and `create_child` retain their
3,000-character limit. Long reusable briefs can still live in a committed file
that the goal names, so implementer and reviewer read the same requirements.

## The pattern

1. **Write the brief as a file** in the repository the task changes, for example
   `briefs/<slug>.md`. Cover what to build, what is out of scope, the acceptance checks the
   reviewer can run, the gates that must pass, and what the captain already ruled out.
2. **Commit the brief on the root line's branch before `create_task`.** The default
   `base` is `checkout`: the task's worktree is cut from the root's current commit, so a
   brief that is not committed there is not in the implementer's checkout. Use
   `base='upstream'` only when the brief is already on upstream.
3. **Keep the goal short and point at the file by path and commit.** The goal states the
   outcome, the brief path, and the acceptance in one line.

```text
create_task(
  name="handles-and-memwarn",
  goal="Ship the three improvements in briefs/handles-and-memwarn.md (commit <sha>). "
       "Acceptance and gates are in that file; report with request_review.",
  implementer="builder",
  review="captain",
)
```

The implementer opens the brief from its checkout before it starts. Because the brief is
a committed file, the reviewer checking the SHA reads the same acceptance checks the
captain wrote, not a paraphrase of them.

## What the goal still carries

- The outcome in one sentence, and the brief path.
- Anything the brief cannot change: the person's decision that is already made, the line
  or repository the work must stay inside.
- Nothing that will go stale. The goal is repeated to the captain on each wake-up
  (`docs/hierarchy.md`, the goal section), so status belongs in task messages, not the goal.

## Checking the length

Task goals above 20,000 characters are rejected before creation by MCP validation
(which names the field and limit) or HTTP validation (422). Captain-line goals
above 3,000 characters are refused by `set_goal` and `PUT …/goal` with HTTP 400.

## Retrying creation

An active child name is reserved under its root. Repeating `create_task` with the
same trimmed name, goal, implementer and review policy returns the existing task
without starting a second worker. A failed initial worker launch can be retried
under the same task and attachment identity. A conflicting assignment or an
unfinished child without a task record returns 409 with the existing line ID;
inspect it before choosing a different name. Archived names may be reused.

Once the task exists, a staffing or notification failure returns its task record
with `creation_error` describing the failure. A lost HTTP response can still leave
the result unknown to the caller; retry with the same name and assignment or use
`tasks()`, rather than changing the name. Task responses expose `goal` from the
conversation's durable goal column; there is no separate task-row goal to reconcile.
The joining task pack includes that goal. Wake riders repeat it until the
transcript is claimed and the delivery cursor proves the pending batch, including
its assignment or goal update. Later wakes omit an unchanged proven goal. A goal
change or the first wake after restart sends the full goal again, with the same
proof requirement for retries.

Memory-cap approvals queue a private continuation before resuming the process.
Even an idle task therefore gets a first wake with the fresh goal rider and its
current task state, rather than only a READY greeting.
