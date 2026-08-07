# Dogfooding Partyline

Partyline can improve and restart the cockpit instance it is using to coordinate the work. This is
**recursive self-improvement**: agents use their own judgment to deploy a reviewed change, recover
the planned line, and continue without a required button, browser refresh, or human in the loop.

This is an operational procedure for contributors. Read [AGENTS.md](../AGENTS.md) before using it;
that file is the authoritative safety contract and records the failure modes that shaped this one.

## The boundary

The instance hosting a conversation must run from a separate **cockpit** checkout. Edit and test in
the **workbench** checkout, then advance the cockpit deliberately. Restarting a cockpit without
deploying merely starts the old code again.

```bash
uv run python -m scripts.cockpit check
uv run python -m scripts.cockpit deploy
uv run python -m scripts.cockpit plan "partyline refactoring" \
  --debrief "Continue from the committed handoff."
# After every planned participant has explicitly cleared:
uv run python -m scripts.cockpit arm --pid NNNNN
```

`check`, `deploy`, and `plan` do not restart anything. `check` refuses a dirty or unpushed
workbench, a stale frontend bundle, a mismatched adapter source/runtime checkout, a failed trigger,
or an automatic plan that has remained unclaimed long enough to show that its trigger never fired.
`deploy` fast-forwards the cockpit and verifies that it matches the workbench.

`plan` is line-scoped and automatic by default. It persists the exact resumable attachments and a
continuation debrief; use `--manual-offer` only when a human should explicitly accept the plan.
Planning is authorization, not a restart.

## Arming a restart

Only arm after preflight is green, every planned participant has explicitly cleared, and no known
finding remains. Any participant may block the restart.

`arm` is the only supported trigger. It schedules a reviewed Python executable through systemd,
then reads back the timer and complete service argv before reporting success. It identifies the old
server by PID **and** process-generation start time, waits for that exact generation to exit, and
then launches the deployed cockpit.

The replacement receives an environment snapshot from the verified outgoing process. This is
load-bearing: a transient systemd unit does not inherit the interactive user's `PATH`, and attached
CLIs may live in a user-local directory. If the old environment cannot be read, the trigger refuses
before signalling the server rather than launching with systemd defaults.

## Automatic recovery

On startup, the cockpit claims the persisted automatic plan through a durable lease and resumes the
saved attachments one at a time. The sequence is intentional: several coding CLIs can otherwise
discover and claim the same transcript concurrently. A slow but live attachment remains attached
and is reported as settling; only a genuine exit is a failure.

Continuation delivery is not inferred from a cursor or pty write. For adapters that support it,
the debrief is part of the native startup command and must appear as structured process input before
the cursor advances. A failed receipt preserves one recovery retry; a second unconfirmed attempt is
consumed with an actionable warning while the process remains live.

## Proof after restart

Green local tests are necessary but not sufficient. A dogfood change is complete only when the real
cockpit has deployed, restarted, recovered, and continued its own work. Record evidence for:

- each process's identity and continuation receipt, using a fresh per-restart nonce in structured
  input rather than terminal screen contents or raw transcript grep;
- all planned attachments present in `/api/running`, including a second snapshot after a delay;
- the completed restart plan consumed at the expected attempt count;
- no unexplained warning lines in the conversation;
- reconnect resynchronization, by dropping a socket while state changes and proving catch-up without
  a document reload; and
- when a release changes only Python, the open tab's release badge updating on its next handshake
  while the unchanged frontend build avoids a reload.

The coordinator summary is useful, but it is not the proof. Keep the command output and transcript
evidence with the handoff so the next agent can distinguish a completed recovery from an assumption.
