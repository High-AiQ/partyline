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
- **Two independent `uv` checks were safe to run in parallel in one worktree.** Concurrent
  environment setup raced while removing a package directory under the shared `.venv`, so the test
  process never started even though the other check passed. Run commands that initialize a shared
  worktree environment sequentially, or give each run its own worktree/environment.
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
- **Preserving the environment did not preserve the server's command line.** Once bind settings
  gained CLI precedence, the restart executable's `execve(server, [server], env)` silently dropped
  `--host`, `--port`, and future flags; the replacement could come back on a different address while
  appearing healthy. The trigger now snapshots `/proc/<pid>/cmdline`, carries the arguments after
  the console-script path, and refuses if that authoritative source is unreadable. A working-
  directory config has the same lifecycle boundary: cockpit restarts chdir to the cockpit clone, so
  durable settings belong in an explicit `--config` path or the user config directory.

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
- **A shared workbench checkout was safe because each agent had its own branch.** The
  coordinator ran `git checkout -b` in the checkout another agent was actively editing, yanking
  HEAD off that agent's feature branch mid-work; a later `git add -A` then committed the other
  agent's half-written module onto the coordinator's branch, where it failed the coordinator's
  own CI. Branches do not partition a working tree: one checkout has one HEAD, one index, one
  set of files. An agent entering a checkout it does not currently own must do its own work in
  a `git worktree`, stage by explicit path rather than `-A`, and leave HEAD where it found it.
- **An append-only transcript stays append-only across every lifecycle path.** Grok's fresh
  session appended correctly, but `grok --resume` atomically replaced `chat_history.jsonl`
  (`inode 5567721 → 5567734`). An ordinal tail counts assistant records before spawn and the
  `os.replace` regression proves it follows the replacement without replaying history. That
  ordinal counts every assistant record, including filtered narration: a saved position must use
  a unit that does not move when relay policy changes.
- **A manifest capability is a product claim, not a parser property.** Grok's fixture tests and
  `--resume` probe proved that the CLI reused context, but only a real detach/resume room showed
  the resumed jack silently swallowed every reply. A capability such as `resume = true` must be
  exercised through its user-visible affordance before release; otherwise the UI promises a path
  the adapter has never completed end to end.
- **A held file handle is not a subscription to a path.** After Grok rewrote its transcript, the
  tail kept polling the old unlinked inode: the jack remained `running` and alive but could never
  post again. Grok's tail now checks every empty read for inode replacement or truncate-in-place,
  then reopens the path; the live codeword proof confirms the post-resume reply reaches the room.
- **An ordinal watermark cannot survive a history rewrite.** Grok compaction atomically replaced
  a live `chat_history.jsonl` with a shorter file (152 assistant records collapsed to 41, the
  older ones moved under `compaction/`). The tail reopened the new inode correctly, but the
  replay watermark was an ordinal counted against the *previous* file, so every post-compaction
  reply was skipped as "already relayed" while the jack stayed `running` — the CLI was receiving
  and answering, and only peeking at its terminal revealed the speech. The watermark is now
  re-anchored on every replacement by aligning fingerprints of the records already seen with the
  start of the replacement file, with regressions for a retained-tail compaction and a full
  rewrite. A position that must survive a rewrite has to live in the records, not in their count.
- **Dead code can contain an unwired guard.** Grok's private decoder rejected non-object JSON, but
  production never called it; deleting that helper exposed a crash on `[]`, strings, numbers, or
  `null`. Removing unreachable code must include checking what it knew. The live shared JSONL
  tailer now rejects non-object records, with regressions for every observed shape.
- **A coverage report describes the last coverage artifact, not necessarily the last intended
  run.** An interrupted `coverage run` left partial data behind, and a later standalone report
  confidently measured that partial run at 84%. Keep collection and reporting chained in one
  command (after `coverage erase` when a run was interrupted), so the report cannot silently
  describe a different execution than the one being handed off.
- **Patching `asyncio.sleep` to a non-yielding mock removes a loop's only suspension point and
  turns a poll into a spin.** A `claude` transcript-tail test patched `asyncio.sleep` with
  `AsyncMock()` to avoid waiting 30s; the tail's `while alive(): await sleep(1)` lost its
  suspension point, so the loop spun without yielding, never processed coverage flush, and timed
  out the suite. Replacing the mock with a counted `alive()` stub that exits after one iteration
  and a yielding `sleep` (`await orig_sleep(0)`) restores the suspension point. The same pattern
  applies to any async poll — if you mock the sleep, keep a `yield` or bound the loop.
- **A frontend-only deploy was safe without a restart.** `partyline/static/` is served by a
  `StaticFiles` mount that reads from disk per request, but the build id was captured once at
  import into `FRONTEND_BUILD`. After `cockpit deploy` swapped the bundle under a running server,
  the browser was served the *new* JavaScript while `/api/version` and the wire hello kept
  announcing the *old* id, so the client's reload guard reloaded, fetched the new bundle, saw the
  same mismatch, and looped forever. The tell was dismissed at the time: the version badge still
  read `v0.28.0` after a `v0.29.0` deploy, called cosmetic when it was the same stale constant.
  `current_frontend_build()` now re-reads the manifest so the served bundle and the announced id
  come from one source, falling back to the last good id if the manifest goes unreadable
  mid-run. Anything a `StaticFiles` mount serves is deploy-live; anything captured at import is
  not, and mixing the two in one decision is what loops.
