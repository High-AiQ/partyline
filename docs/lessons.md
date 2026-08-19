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
- **A fast-forwarded tree is an installed environment.** Deploy of v0.32.0 advanced the
  cockpit clone to `fc0c6db` and the restart timer fired on schedule. The replacement
  died in three seconds: `ModuleNotFoundError: No module named 'PIL'`. The lockfile
  named Pillow; the cockpit `.venv` did not have it. `uv run` later synced and bound
  the port — that listener is a manual shell child, not the timer. `deploy` now
  `uv sync --locked`s the cockpit venv, and the restart executable refuses *before*
  `SIGTERM` unless that interpreter loads *this* cockpit's `partyline` (path and
  version). A green `import partyline.server` that resolved the workbench via an
  editable `.pth` is the same failure wearing a passing grade. ``check`` also
  reads live ``/api/version`` against the cockpit tree so a healthy-but-stale
  server cannot hide; ``arm`` skips that gate because restart is the remedy.
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
- **Patching `asyncio.sleep` on the adapter module stops a tail that no longer lives there.** On
  2026-08-19 a presence-stack split moved the Grok wait into `tail.py`. Tests still patched
  `partyline.adapters.bundled.grok.adapter.asyncio.sleep`; the loop never yielded. Combined with
  `test_a_transcript_that_never_settles_is_refused_out_loud`'s `keep_growing()` writer, that
  filled ~31 GB twice and OOM-killed WSL. The tail now waits only on `adapter._poll`. A source
  scan fails if `tail.py`/`resume.py` call `asyncio.sleep`, and a regression fails if a stop
  patch on `_poll` never runs. Do not "repro" this by running `tests.test_grok_adapter` uncapped
  on the dogfood VM.
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
- **A guard that passes its own control can still be aimed at the wrong door.** Grok's resume
  watermark survived four rounds of controls and still failed on a fifth dogfood restart. The
  early guards were individually true — settle before counting, refuse an empty count, treat the
  first replacement as a restore — but they all preserved the same false premise: an ordinal in
  a CLI-owned file could represent what Partyline had delivered. The final restore placed 39
  never-delivered mute-window messages before an already-delivered tail. Carrying the ordinal
  skipped part of that backlog and reposted the tail. Two independent reads of the captured
  artifact found that 19 of 21 apparent duplicate bodies occurred exactly once in the transcript;
  the CLI had not duplicated or re-serialized them. Sequence alignment then showed only 20
  already-delivered occurrences: the twenty-first body match was a legitimate new repetition from
  the mute window. Partyline had moved its own watermark backwards, and body matching had overstated
  the replay while measuring it. Body deduplication was therefore also the wrong repair: repeated
  `Idle.` and clearance messages were legitimate separate occurrences. The durable boundary is
  now Partyline's ordered message
  history, scoped to the one resume flush. A unique suffix of delivered bodies anchors the restored
  transcript, occurrence-aware sequence alignment suppresses only matched records, and unmatched
  records remain backlog. An ambiguous anchor is refused out loud and the existing file is skipped,
  while later speech still flows — refusal cannot become another permanent mute. The old settling
  guards remain as narrower protections, but the structural lesson is sharper: **persist and align
  the fact the product needs; do not repeatedly infer it from a mutable proxy.**
- **A guard is only as good as the question its control asks.** One night produced four
  distinct instances of the same shape, each caught by a different pair of eyes and none by
  the author. A probe test that mocked the subprocess's exit code verified the parsing of an
  outcome and never the command that produced it, so a probe that had stopped importing
  `partyline.server` stayed green. A control retyped from memory omitted the blank line
  GitHub actually emits, so the fix it proved did not match the artifact it was written for.
  A test whose fixture held one conversation could not see a snapshot that leaked every
  conversation, and one holding a single jack could not see a badge lighting the wrong card.
  A test calling a method that had become `async` passed while executing no production code
  at all. The rules that survive: **the control's input should be captured, not authored**;
  **a probe needs one real-interpreter control, because mocking the result skips the
  invocation**; **if the code partitions by X, the fixture needs two Xs**; and when a sync
  method becomes async, run the suite once with `-W error::RuntimeWarning` — an un-awaited
  coroutine is a green test that ran nothing.
- **Refusing to do the wrong thing is not the same as doing the right thing.** A watermark
  guard was written to stop a resumed process replaying its whole history into the room. It
  worked: it refused a re-anchor it could not verify and held its position. The transcript
  then settled shorter than the held ordinal, so no future record could ever clear it, and
  the process went silent for hours — alive, receiving mentions, producing replies visible
  only in its own terminal. From the line, "replays everything" and "says nothing" are the
  same failure: a participant you cannot trust. Every refusal path needs a bound and a way
  back; holding a position is right, holding it forever is a mute. And prove the recovery
  with **two beats** — silence proves nothing, so require the process to speak *and* to
  answer a mention before calling it fixed.
- **The deployed build is the only thing whose behaviour counts.** Four rounds of reasoning
  about a file lost to one deterministic control run against the shipped adapter. The same
  night, a browser regression measured a stale bundle, a cockpit deploy fast-forwarded source
  without installing its dependencies, and configuration bound at import before `.env` was
  merged. Reason about source; verify against the artifact that actually runs.
- **A runaway test should cost one command, not one machine.** Twice a Python test process has
  grown without bound — `coverage` to 19 GB (2026-08-14), `unittest` to 30.6 GB and then
  31.0 GB (2026-08-19) — and both times the first symptom anyone saw was the VM disappearing:
  the OOM killer took the cockpit, every attached CLI, and finally systemd's boot, which then
  reboot-looped until a human ran `wsl --shutdown`. Neither cause was exotic. The second was a
  poll whose `asyncio.sleep` had been patched in the module it used to live in, after the tail
  was split into its own file, plus a test writer appending a line on every `sleep(0)` — this
  same file's oldest lesson, reappearing because a *refactor* moved the patch target rather
  than because anyone wrote a new mistake. The durable guard is not another review rule: it is
  `./scripts/capped-test`, which runs the suite under a kernel memory cap so the runaway dies
  in seconds and the machine survives to show you the failure. **When a hang can take the
  host, the bound belongs in the runner, not in the reviewer's attention.** Corollary for
  refactors: moving a function to a new module moves every patch target aimed at it, and a
  test that patches the old location still passes — it just no longer patches anything.
