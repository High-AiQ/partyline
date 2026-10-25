# Task briefs: the goal is a pointer, the brief is a file

`create_task(name, goal, implementer, review)` takes a `goal` of at most **3000 characters**
(`MAX_GOAL` in `partyline/goal.py`; `TaskIn.goal` in `partyline/orchestrator_contracts.py`).
That is enough for an outcome, a pointer and the one or two constraints that cannot be
found in the code. It is not enough for a real brief: scope, file lists, acceptance checks,
gates, out-of-scope items and the reasons behind them. Those go in a committed file, and the
goal names the file.

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

A goal longer than 3000 characters is refused: `set_goal` and `PUT …/goal` return HTTP 400
(`goal is capped at 3000 characters`), and `create_task` fails validation because
`TaskIn.goal` has `max_length=3000`. Shorten the goal and move the rest into the brief; do
not split a goal across several messages.
