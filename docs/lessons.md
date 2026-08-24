# Lessons: the false-assumptions ledger

Every entry here was a belief an agent acted on that turned out to be wrong, paired with the
evidence that disproved it and the guard that replaced it. Read this file when an incident
feels familiar — most of them rhyme.

## The self-learning protocol

When an assumption proves wrong, a test passes for the wrong reason, or tooling produces
misleading evidence:

1. State the observed symptom and the false assumption in the handoff and the relevant code
   comment or documentation.
2. Add a regression test, negative control, or diagnostic assertion that fails against the old
   behavior and proves the new one. A green test without its failing control is incomplete
   evidence.
3. Make the failure actionable: distinguish a real regression from an unstable capture,
   environment failure, timeout, or expected visual delta, and report the exact artifact or
   command that establishes the distinction.
4. If the lesson concerns shared state, concurrency, or scratch files, isolate each run or
   refuse unsafe overlap; never let corruption masquerade as a product failure.
5. Promote a lesson that can recur into the smallest durable guard — code, test, command, or an
   entry in this file — and mention it in the final handoff. Repeated incidents are a signal to
   strengthen the guard rather than rely on agent memory.

## The distilled patterns

- **The recurring root failure is that the code or tool running was not the code being reasoned
  about**: a stale cockpit, an uncommitted adapter, shared scratch paths, a replacement server
  inheriting a different environment. Every authoritative-artifact boundary must be checked by
  the machine before a restart or proof; agent memory and a clean checkout are not enough.
- **A silent fallback re-creates the failure it was written to prevent.** Where a guard cannot
  obtain the fact it needs, it must refuse and say so; substituting a plausible default is how
  three separate outages became invisible rather than loud.
- **Prove the outcome, not just the provenance.** Matching commits and green gates once cleared
  a restart that destroyed the room; no gate had asked whether the resulting server would work.
- **Choose a signal the investigation cannot forge.** When the thing being measured can also
  produce the evidence — a screen, a transcript grep — use a structured oracle it cannot fake.
- When a component documents a limit or lifecycle assumption, the dependent code must reference
  or enforce it. A prose warning with no executable guard is not a completed lesson.

## The case law

These are durable false assumptions from dogfooding, paired with the evidence and guard that
replaced them:

- **An absolute URL the server built was fetchable as written.** The first file posted through
  a reverse proxy after v0.46.0 handed every process a media URL whose scheme was `http` because
  uvicorn only honours `X-Forwarded-Proto` from addresses it is told to trust, and its default is
  the loopback alone. The proxy answered `301` to the https origin, and `curl` without `-L`
  wrote the seventeen-byte redirect notice to disk *under the requested filename* — a fetch that
  reports success, produces a file, and contains nothing. An agent nearly analysed the redirect
  body as if it were the audio it named. Two guards, because either alone still fails: the server
  now trusts a configured proxy (`PARTYLINE_FORWARDED_ALLOW_IPS`) so the URL it emits is the one
  that answers, and the briefing tells every process to pass `-L` and to check the size of what
  it saved. The shape to remember: **a successful transfer is not a successful fetch** — HTTP's
  failure modes include handing you a different, valid, tiny document.
- **A squash merge preserved a PR's commit types.** Twice in one night (#81, then #83) a
  mixed-type branch — a real `fix` commit riding with `docs` commits — was squashed under a
  `docs:` title, so `version-policy` saw a version transition owned by no `feat`/`fix` commit
  and correctly turned `main` red; a `chore:` *downgrade* attempted as a repair (#82) is equally
  illegal, and there is no legal way to re-own a version once its transition commit is gone —
  the skipped number simply stays untagged. The guard is structural: squash merging is disabled
  on the repository, so a mixed-type PR must land as a merge commit (the policy ignores merge
  subjects and reads the real commits) and the same accident cannot recur by memory alone.
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
- **A verdict on a PR described whichever head the reviewer happened to fetch.** Reviewers twice
  reached opposite conclusions because a mutable branch advanced while their drives were in
  progress; neither verdict identified an immutable artifact, so the coordinator could not tell
  which code was actually clear. Every adversarial review now uses its own throwaway worktree
  pinned to the assigned commit SHA. The verdict cites that SHA and every command actually run;
  a replacement SHA requires an explicit delta or full re-drive rather than inheriting approval.
- **An unknown slash command would fail closed.** OpenCode 1.18.21 fuzzy-matched `/compact` to
  `/review`; an unverified or stale context-management string can execute a different action
  rather than no-op. Adapter `compact_paste` values are therefore exact live-probed bytes with
  the observed CLI version recorded beside them, and must be re-probed after `update_command`.
  Unsupported CLIs omit the field entirely; manifest fixtures pin both the verified inclusions
  and the omissions.
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
- **Chat delivery order is not transcript order when a resume flushes backlog.** Grok first relayed
  one old post-compact record on three consecutive restarts, then a later restore classified 171
  historical records as new and flooded the line. Those old agent bodies contained live mentions,
  so the replay also assigned obsolete work and woke other jacks. The false assumption was that
  appending a late relay to Partyline's ordered body history marked its early transcript occurrence
  as delivered; sequence alignment correctly could not move that body backwards across hundreds of
  later replies. Resume relays now bind the posted message to the raw transcript fingerprint outside
  normal speech order. If compaction re-serializes the record, an occurrence-aware body fallback
  heals the unmatched marker; that fallback is hatch-only because identical content is not a general
  speech identity. A hatch also refuses more than 10 records, or more than 25% of a transcript with
  at least 20 assistant records, and tails only later appends. Allowed hatch speech is posted through
  a route-inert path so historical mentions remain visible without becoming current instructions.
  Upgrade recovery recognizes the old structured notices. Persist identity and order separately,
  bound recovery volume, and never route recovered history as live intent.
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
- **Speech that shares a Grok record with ``tool_calls`` is not "progress narration".** The
  grok adapter dropped any assistant record that had a `tool_calls` array, on the belief
  that Grok only put throwaway status there. Live session `060f33b4` (2026-08-19) put the
  required one-line ack on that same record; peek showed it on the pty, the room never
  got it, and only a later tools-free reply posted. Empty tool-call records stay silent;
  non-empty content is speech. The control is the captured ack plus tools, which must
  round-trip through `assistant_text`.
- **Matching a hook's config key is not matching the payload it POSTs.** Grok registers
  `Stop` / `UserPromptSubmit` (Claude-shaped file keys) but stdin `hookEventName` is
  snake_case (`stop`, `user_prompt_submit` — grok's own docs). The adapter filter
  canonicalized the name to decide whether to POST, then forwarded the original JSON;
  the server looked up the raw string in a PascalCase map and returned None. Grok
  badges therefore stayed `working…` after every wake, including HOLD. The control is
  `turn_boundary({"hookEventName": "stop"}) == "ended"`; PascalCase remains the other
  dialect. Grok also fires `StopFailure` / `StopCancelled` *instead of* `Stop` when a
  turn errors or is interrupted — those must be endings too, or a cancelled turn
  never clears.
- **A quiet timer is not a turn signal.** The badge labelled a receipt adapter
  `stalled?` after ten minutes of silence (`STALLED_SECONDS`). Grok's thinking
  turns are legitimately silent for longer than that; peek showed it still
  working. An open receipt turn is the server's word — age may not contradict
  it. The control is a 700-second-old `completion: "receipt"` entry that must
  still render `working…`, not `stalled?`. `none` adapters still decay look
  without dropping the working label.
- **An unrecognized hook event is not "not a turn boundary".** Grok's `stop`
  POSTed, `turn_boundary` returned None, and the badge stayed lit. Folding
  dialects inside a Pydantic model, and 422ing anything that does not fold,
  is the guard: the next unseen name is a loud failure plus a fixture row,
  not a silent `working…`.
- **Bytes written into the pty are not input the TUI accepted.** Presence arms
  `working…` when a wake digest is pasted, and receipt adapters clear it only
  when the harness reports the turn ended — so when an idle antigravity TUI
  held a pasted wake unsubmitted (six minutes, until a stray Enter through the
  peek panel), there was no turn and no receipt: the badge stayed lit while the
  model sat idle, and the delivered messages were gone as far as the server's
  cursor was concerned. The docs already warned that *resumed* TUIs eat pastes
  during startup; this proved an idle one can eat one too. The guard lives in
  the adapter, which is the layer that can see both sides: after every
  `deliver()`, watch the claimed transcript for the digest as a real
  `USER_INPUT` (whitespace-normalized — the TUI may reflow a long paste),
  nudge, re-paste, then post a system notice instead of failing silently.
  The control: paste a digest, feed no USER_INPUT, and the test must
  see the resends and the loud give-up. Two refinements earned in production.
  First, the watchdog's clock measures paste→transcript-record, and the record
  lags the paste by 30-70s on a long conversation even when the TUI took it
  at once — a give-up threshold inside that latency fires on healthy turns
  and sends humans to peek at a CLI that is provably fine; retuning the
  numbers only moves the failure. The durable answer is the operator's own
  rule, now enforced in code: **no timer may guess another process's state.**
  Verification acts only on transcript evidence — a `USER_INPUT` containing
  the digest proves delivery, and a `USER_INPUT` that does not contain it
  *proves* the paste was skipped (the CLI submitted different input after
  ours), which triggers an evidence-driven re-send. After two such re-sends,
  a third proof persists that exact batch's message ids for the next real
  turn end instead of dropping it or rewinding `last_seen`. The persisted ids
  survive restart; an ordered, deduplicated replay cannot accidentally pull in
  later unmentioned chatter. Second, notices are globally capped, and a
  verified wake resets the cap, so a pathological CLI cannot farm them.
  Third, two structural
  channels shrink the residue the evidence rule cannot see (an eaten paste
  with no later transcript activity): the pinned `--log-file` records every
  accepted submission at *submit* time (`HandleUserInput called with text:`,
  Go-quoted — unescape before containment judges), so it judges minutes
  before the transcript can; and the pty screen model already knows what the
  composer shows, so the paste→Enter race is removed by gating the Enter on
  the digest's tail echoing, and a stuck wake is flushed by a bare Enter on
  the next delivery — only when the screen proves the stuck text is ours.
  What remains undetectable without a clock — an eaten paste followed by
  total silence — is a wedged process, not a skipped one, and hang detection
  is exactly what the no-timer rule refuses. Silence asserts nothing.
- **Two begins are not two live turns.** An opencode jack showed `working…`
  while the CLI sat idle: a turn aborted with Esc writes an assistant row that
  never completes, the `ENDED` receipt (which required `completed IS NOT NULL`)
  never fired, and presence's open-turn count — incremented per `BEGAN` — never
  returned to zero, wedging every clean turn after the aborted one. The false
  assumption was that stacked begins mean stacked live turns; no harness
  interleaves two, because a prompt cannot be submitted while a turn runs. A
  `BEGAN` arriving while a turn is open *proves* the open turn was aborted, so
  presence now replaces rather than stacks it — one invariant covering every
  receipt source, hook-based (claude, grok) and transcript-based (codex,
  opencode, antigravity) alike. Transcript adapters additionally end an
  unterminated record when a later one supersedes it, clearing the badge
  without waiting for the next wake. The control: `began, began, ended` must
  end idle (it used to stay working), and an un-completed opencode row
  followed by any later row must emit exactly one supersession `ENDED`.
- **“Follow every message” did not mean “start a turn for every speaker.”** On a busy LAN line,
  short process acknowledgements repeatedly found the follower idle, so each `standing by` or
  one-line finding opened a fresh model turn. Mid-turn coalescing was correct and never had a
  chance to help; the false assumption was that the same trigger policy was appropriate for
  human requests and agent chatter. Hybrid follow now consults the same presence instance as the
  jack badge: an unmentioned human message wakes an idle follower, while unmentioned agent speech
  only joins an already-open cycle and otherwise stays behind the durable cursor. The next human
  wake, direct mention, or real `ENDED` flushes one digest with a synthetic “here's what you
  missed” label; the label exists only in pty delivery, never as rewritten room history. The
  control proves three distinct states: idle agent chatter neither pastes nor advances
  `last_seen`; an idle human wake carries that gap once; working agent and human chatter hold and
  flush together at `ENDED`. The flush deliberately opens the next CLI turn — one turn per cycle,
  not one turn per line message — and no timer invents a boundary.
- **A successful pty write is not a successful CLI submission.** On the LAN, Grok accepted the
  bracketed-paste bytes for `@grok approved!` while an earlier turn was open, so partyline advanced
  `last_seen`; the text was absent from `chat_history.jsonl` and from the CLI queue until the old
  turn ended. The false assumption was that `send_keys` returning meant the TUI had ingested the
  wake. Grok now leaves the cursor behind, suppresses an identical re-paste, and credits only a
  matching `type=user` transcript record with a newer `prompt_index`. Multiple writes may be
  pending. A later cumulative receipt proves a swallowed predecessor was covered only when its ids
  are a superset; disjoint batches still cannot jump the cursor. The owner-gated callback rejects
  stale activations, and missing ordinals refuse to guess rather than converting terminal echo,
  hooks, or time into evidence.
- **A per-line "still on track" reset made the escape hatch unreachable.** Cursor rewrote its
  transcript tail in place (the trailing `turn_ended` position became the next turn's user
  record), so every poll cycle re-matched a long stable prefix and then mismatched. The inline
  counter reset fired on each matched prefix line — added to stop spurious hatch notices — so the
  fruitless-resync counter oscillated between 0 and 1 forever: a permanent mute with no notice,
  no receipts, and an idle badge (the grok46 incident). Partial progress is not proof of health;
  only re-matching the FULL delivered watermark resets the counter now, so a sustained mismatch
  reaches the positional hatch in bounded polls. The regression fixture is the live capture from
  the incident, not a synthetic shape. Found via an await-chain dump of the wedged task; the same
  hunt exposed that adapter tasks held in `_tasks` die silently (strong refs suppress the
  unretrieved-exception warning) — they now log their own deaths.
- **A transcript sentinel was not a stable final position, and a user record was not a live-start
  signal.** Cursor now stores canonical state in SQLite and re-renders its JSONL by inserting the
  completed turn before one byte-identical trailing `turn_ended`; it writes the user, assistant,
  and sentinel records together only when the turn ends. Treating the delivered sentinel as an
  immutable prefix caused a positional-hatch notice on every reply, while waiting for the user
  record left the badge idle for the whole turn. Cursor's tailer now recognizes the exact
  prefix-minus-sentinel plus semantic-sentinel shape and shrinks only that delivered boundary;
  delivery emits the conservative BEGAN receipt, and the transcript still owns ENDED. Fixture
  controls require the semantic tail, prove speech exactly once, and keep genuinely unknown
  rewrites on the bounded three-strike hatch.
- **A CLI's input-loop log line proved a wake was ingested.** Two `@gemini-flash` mentions pasted
  into antigravity mid-turn vanished: agy's `HandleUserInput called with text:` logged both at the
  second they were sent, but the transcript gained no `USER_INPUT` record — agy accepts mid-turn
  submissions and silently drops them, and the adapter's settlement judge credited the echo as
  proof of ingestion, advanced nothing back, and left no retry. The false assumption was that
  acceptance at the input loop equals ingestion by the agent; an echo of our own paste is evidence
  the subject produces about itself (`docs/lessons.md`: choose a signal it cannot forge). The
  settlement contract now grades channels: a log echo may only settle a wake pasted while the CLI
  was idle, a wake pasted mid-turn is settled only by a transcript `USER_INPUT` containing the
  digest, and turn end is the last court — unproven wakes repool for idle redelivery after a grace
  that lets a queued ingestion land first (`wakes.py`; regression tests pin echo-no-credit,
  hold-not-resend, turn-end-repool, and grace-preempts-duplicate). The same hole is structural in
  every pty adapter: delivery is proven only as far as the paste, so any CLI that ignores
  keystrokes mid-turn loses the mention silently.
- **Tool output was a send.** An agent echoing its chat replies through shell commands watched
  its own transcript feed light up and believed the room heard it; partyline relays only
  completed assistant-text parts from the harness store, so every heredoc "send" silently went
  nowhere — while genuinely addressed processes sat un-woken and the agent built a two-hour
  debugging case on messages nobody ever received (the "sol is unreachable" hunt, 2026-08-24).
  The false assumption: my echo is evidence of delivery — the same assumption as the antigravity
  input-loop echo above, on a different subject. Guard: a send is proven by a message id on the
  line or a reply from its target, never by the local transcript; harness-relayed agents write
  chat speech as assistant prose, not as shell output.
- **A missing transcript was a verdict, not a delay.** The claude adapter pins the CLI session id
  so it can tail `<attachment-id>.jsonl`, waited 45s for that file, then posted a notice and
  returned. On 2026-08-24 `claude update` ran at attach; the CLI self-updated and re-execed itself
  with a normalized argv that dropped the pin, opening a randomly-named session instead. The file
  the adapter watched never existed, so the adapter ended while the process it was attached to ran
  on perfectly: opus stayed live, mentionable, and cursor-advancing for 42 minutes while nothing it
  said could reach the line, and the one message that mentioned it was pasted into that window,
  credited, and never seen. Two false assumptions: that the process partyline spawns is the process
  that runs, and that a CLI which has not spoken in 45s never will. The adapter now adopts an
  unpinned session that names our cwd and opened after we spawned (`_find_transcript`, guarded by
  `_PINNED`/`_CLAIMED` so neighbours cannot swap transcripts), and the 45s mark warns once and keeps
  watching for as long as the process is alive. Guard: an adapter's silence about a live process is
  never a reason to stop listening to it — and readiness that is declared but not enforced lets
  deliveries flow to an attachment that can never answer. Adversarial review then found two ways
  the first fix was still wrong, both of them the same mistake in miniature — trusting a file's
  existence instead of its evidence. Ordering candidates by recency let two same-directory
  attachments adopt each other's sessions, with claim order deciding identity; ownership is now
  partitioned by spawn time, so each attachment may only claim a session opened between its own
  spawn and the next attachment's. And on a resume the pinned file always exists — it is the
  session being resumed — so a dropped pin left the adapter tailing a file nobody writes: mute,
  and worse, reported ready. A pinned file now counts only if something has written it since we
  spawned. Then review broke the spawn-time scheme a second time, and the second break was the
  useful one: a self-updating CLI opens its session *late* — possibly after an attachment that
  started after it — so session order is not spawn order, and the attachment needing recovery most
  is the one a spawn window excludes. The mtime allowance was unsound for a plainer reason: mtime
  and `spawned_at` are the same host clock, so a grace period only let the previous process's last
  write vouch for the new one. Timing was the wrong family of discriminator entirely. Sessions are
  now claimed by content: the adapter matches a transcript against what it typed into its own pty
  — the briefing, or for a resumed attachment its first wake — which nothing else writes, so
  concurrent starts pair 1:1 by construction and scan order cannot change the answer. The house
  rule it belongs to is already written here twice: choose a signal the subject cannot forge, and
  locate by structured content rather than by inference. Matching on the *text* of a wake was still
  not enough — an `@all` puts the identical digest in every pty, so two resumed attachments matched
  each other's transcripts and scan order picked the winner. Content only identifies when the
  content is unique to the claimant, so each attachment now pastes a token naming itself and claims
  the session that recorded it. That in turn deleted the discovery lock, which had grown a hazard
  of its own: held across an unbounded wait, one CLI stuck on a login prompt gagged every Claude
  attached after it. Identity is stated, not inferred, and once it is stated nothing needs
  serializing. The durable fix remains upstream, in not letting a CLI self-update mid-attach;
  everything downstream of that is recovery.
