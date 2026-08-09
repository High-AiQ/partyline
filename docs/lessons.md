# Lessons: the false-assumptions ledger

Every entry here was a belief an agent acted on that turned out to be wrong, paired with the
evidence that disproved it and the guard that replaced it. The [self-learning
protocol](../AGENTS.md#self-learning-protocol) is what adds entries; read this file when an
incident feels familiar — most of them rhyme.

The distilled patterns live in AGENTS.md and are the part every agent must know. This file is
the case law behind them.

These are durable false assumptions from dogfooding, paired with the evidence and guard that
replaced them:

- **A 90-second readiness timeout proved a resume failed.** Codex documents that a resumed rollout
  may appear many minutes later; timed-out but live adapters now remain attached and are reported as
  *settling*, while an explicit `False` readiness result remains a failure.
- **A build-id reload kept every tab's state current.** A Python-only restart left stale messages and
  LEDs; a successful wire re-handshake now re-fetches the current line detail and merges messages.
- **A fixed scratch path two agents can write was safe to share.** Concurrent visual checks corrupted
  captures and invented differences; any such tool is worse than no tool until each run stages
  privately and refuses overlap with a lock. We also reported contaminated output before checking
  whether the result was plausible; conflicting or surprising evidence must be investigated first.
- **A green test named “does not block the sequence” proved the timeout behavior.** It passed while
  the old path killed the process; a negative control now asserts the timed-out adapter stays live,
  and cross-process tests exercise the real failure mode.
- **A cursor, screen, or raw transcript grep proved continuation receipt.** The cursor recorded
  intent, the screen was transient, and investigation tool traffic forged transcript matches; the
  authoritative oracle is a per-restart nonce in a structured `user_message` record. When the thing
  being measured can also produce the evidence, choose a signal the investigation cannot forge.
- **A replacement server owning a live PTY meant the retiring server could no longer affect it.**
  Uvicorn releases the listening port before lifespan teardown finishes, so the new server resumed
  an attachment and reported it ready before the old server's later `stop()` callback rewrote the
  shared row to `detached`. Every adapter activation now claims a unique runtime owner; lifecycle
  state, delivery cursors, CLI sessions, and adapter-originated messages are conditional on that
  owner, so callbacks from an older generation are rejected rather than broadcast as current state.
  A cross-process reservation also spans owner validation through each PTY write: a read-side owner
  check alone leaves a check-to-effect race in which replacement can occur before delivery.
- **Creating a delayed supervisor meant a restart was armed.** One `nohup` process was reaped, then
  a listed systemd timer fired shell whose nested quoting corrupted its own PID-generation check;
  both left the plan unclaimed while the old server ran for hours. Restart logic is now a tested
  Python executable, `cockpit arm` verifies the durable timer and exact command after scheduling,
  failed units remain inspectable, and a plan still at attempt zero after five minutes is an
  actionable failure rather than an indefinitely pending intention.
- **A replacement server launched by systemd inherited the outgoing server's environment.** The
  transient unit had systemd's minimal `PATH`, so the new server bound the port successfully but
  could not find any user-installed adapter CLI; all four resumptions failed while the server still
  looked healthy. The restart executable now snapshots `/proc/<pid>/environ` from the exact old
  generation before signalling it and passes that mapping to `execve`. If the snapshot cannot be
  read, the trigger refuses before `SIGTERM` rather than falling back to the environment that caused
  the outage.

- **A verified trigger meant a verified restart.** Restart #6 was cleared unanimously on evidence
  that was entirely about *provenance* — matching commits, an exact ordered `systemd` argv, an
  identical adapter store, 297 plus 58 passing tests — and every one of those facts was true. The
  restart still destroyed the room. The replacement server was launched by `systemd`, inherited its
  minimal default environment, and so had no `~/.local/bin` on `PATH`; all four reattachments failed
  with `No such file or directory: 'claude'`, and the broken server went on holding the port, so a
  human starting a fresh one by hand was still served by the broken one. **A process is not defined
  by its executable alone: its environment is part of what gets deployed, and a new parent means a
  new environment.** The replacement is now launched with the outgoing generation's environment,
  snapshotted from `/proc/<pid>/environ` *before* the signal, because afterwards it is gone.
  The wider lesson is that no clearance gate asked whether the resulting server would *work* —
  only whether the right code would start. Prove the outcome, not just the provenance.
- **An `exited` database row meant the process was no longer live locally.** A clean Codex exit
  updated durable status but left its adapter in `runtime.live`; `/api/running` omitted it while
  `/resume` rejected it as “already live.” Owner-matched terminal status callbacks now remove the
  process-local adapter, and the regression control proves an exited attachment can resume again.
- **A delivered mention meant the process could answer.** Newer Codex builds moved speech from
  `agent_message` events to `item_completed` items; the tail spoke only the old dialect, so two
  agents received every ping and posted nothing for hours — and their silence read as choice, not
  breakage. Adapter tests now pin each vendor vocabulary, and a joined process that never lands its
  hello on the line is a defect to investigate before assigning it work: attachment status proves a
  process can hear, only a round-trip post proves it can speak.
- **A rendered prompt meant the TUI accepted input.** A resumed Muse reached `input_ready`, drew
  its prompt, consumed keystrokes, and discarded them; a fresh attach had “worked” only because the
  briefing rode argv, so pty input had never been exercised, and a liveness probe was mistaken for
  an input proof. Input validation must exercise the real pty delivery path and read the durable
  session-log record as its oracle; rendering and staying alive prove neither. When only one
  instance misbehaves, compare kernel-level evidence (`/proc` thread wait channels) between the
  broken and a working instance before theorizing about protocol.
- **`.nullable()` covered a field the wire might omit.** `broadcast()` serializes with
  `exclude_none=True` while REST spells the same absence `null`, so the first live event for a
  fresh attachment failed strict parse and stopped the tab with “protocol mismatch” — and a hard
  refresh masked it by re-reading state through the REST dialect. Shared schemas now read omitted
  and null as the same fact, with tests pinning both spellings; a schema at a dual-serialized
  boundary must accept every dialect that boundary actually produces.
- **Advancing the cockpit meant a git pull.** The coordinator twice advised manual
  `git pull` + Ctrl-C restarts while `scripts.cockpit check/deploy/plan/arm` existed, was
  documented, and did the fast-forward itself — and a deploy that is not promptly followed by a
  restart leaves new tabs reload-looping against the old server. `docs/dogfooding.md` is the only
  deploy path; read it before giving restart instructions rather than reconstructing the procedure
  from memory of the last manual recovery.

When a component documents a limit or lifecycle assumption, the dependent code must reference or
enforce it. A prose warning that has no executable guard is not a completed lesson.
