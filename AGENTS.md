# AGENTS.md

Guidance for coding agents working in this repository.

## What this is

partyline is a local chatroom that attaches real interactive processes to conversations through
ptys. Read `README.md` first. The pty and transcript-tailing design are load-bearing: do not
replace an interactive process with a headless invocation or screen scraping.

## Layout

- `partyline/server.py` — FastAPI app: REST, WebSocket, and mention routing
- `partyline/adapters/` — built-in process adapters and adapter discovery
- `partyline/db.py` — SQLite schema, migrations, and queries
- `frontend/` — the TypeScript web client: Vite + Svelte 5 + Tailwind (see below)
- `partyline/static/` — **build output, committed.** Never edit by hand
- `skills/add-process-adapter/` — procedure and contract for new adapters

## Frontend

The client is a Svelte 5 app built by Vite into `partyline/static/`, which the
server serves: `/` is `index.html` and `/assets/*` is mounted `StaticFiles`.

```bash
cd frontend
npm install
npm run verify    # format:check + lint + svelte-check + tests — the gate
npm run build     # → partyline/static/  (do this before committing UI changes)
npm run dev       # hot reload against a partyline on $PARTYLINE_PORT (default 8642)
npm run format    # apply Prettier; `lint:fix` for the auto-fixable lint
```

**`npm run verify` must pass before every frontend commit**, and it is what CI
runs — the same command, so the two can never disagree. It is four gates:
Prettier formatting, ESLint, `svelte-check` at zero errors *and zero warnings*,
and the unit tests.

Formatting is Prettier's alone; `eslint-config-prettier` is last in the flat
config so ESLint has no stylistic opinions left to argue with. Note this is the
opposite of the Python rule below, where the autoformatter is deliberately not
enforced — that exception is about hand-wrapped Python, and does not extend to
the frontend.

Two ESLint settings are load-bearing rather than taste:

- **Core `prefer-const` is off inside Svelte files**, replaced by
  `svelte/prefer-const`. Props are declared `let { … } = $props()` and are
  reassigned by the framework rather than by us, so the core rule "fixes" them
  into `const` and silently breaks reactivity. It wanted to do that to 45
  declarations.
- **`svelte/no-useless-mustaches` allows string escapes**, because
  `placeholder={"a\nb"}` is the only way to get a newline into an attribute.

**`partyline/static/` is committed on purpose.** partyline installs and runs as
a Python package; requiring Node to build a wheel, or to start a fresh clone,
would break that. The cost is that a UI change is two things in one commit — the
source under `frontend/src/` and the rebuilt bundle. Rebuild before you commit,
or you will ship a stale UI that matches none of the source.

**Release and frontend build identity are different facts.**
`partyline/__init__.py` is the single source of truth for Partyline's semver
release as a whole: server, bundled client, database/protocol behavior, and
fixes. `partyline/static/build.json` identifies only the frontend bundle and
decides whether an open document must reload. A reconnect must still refresh
the release version even when the build ID is unchanged. Adapter repositories
have independent versions; `frontend/package.json` is not a Partyline release
source.

Layout, and where things belong:

- `src/lib/` — **pure functions, no framework.** Markdown rendering, mention
  candidates, jack selection, routing, the REST client. Anything with a rule in
  it belongs here, because this is the layer that gets unit tests.
- `src/state/*.svelte.ts` — runes stores: `session`, `room`, `wire`, `draft`,
  `dialogs`. One owner per concern; components read them and call methods.
- `src/components/` — presentation, grouped by region (`rail/`, `chat/`,
  `board/`, `dialogs/`).

**Responsive layout.** Three columns need about 900px. Below that the rails
become drawers over the line and exactly one can be open — before this, the
centre column computed to `0px` on a phone and the conversation itself was
invisible while the lines list and attach form took the whole screen.

The breakpoint lives in two places that have to agree, because CSS cannot read
a TypeScript constant: `NARROW_MAX_WIDTH` in `state/layout.svelte.ts`, and the
`@media (max-width: 899px)` blocks in the components. If you move one, move the
other. Everything responsive is inside those blocks on purpose — the desktop
layout is the app's identity, and keeping it out of the cascade is what lets
the parity harness prove it has not moved.

Two rules that are load-bearing rather than stylistic:

- **The wire's generation guard.** `wire.connect()` bumps a counter and every
  handler checks it. A socket closed while switching lines keeps firing, and
  without the guard the old line's traffic lands in the new line's feed.
- **Escape first, then parse.** `renderMessage` escapes the body before
  `marked` sees it, and DOMPurify runs after. Escaping is not redundant with
  the sanitiser: it is what keeps a message that *says* `<b>` looking like the
  text somebody typed, and stops a hand-written `<span class="mention">` from
  drawing a fake mention.

`window.partyline` exposes `{room, session, wire}` as a deliberate test surface
for `tests/ui/`, which needs to drop a socket and deliver fabricated events.
Treat it as API: if you rename a store, fix those tests.

TypeScript is strict from the compiler through ESLint: `strict`,
`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, and project-aware
typescript-eslint rules are all gates. Do not introduce `any`, double casts, or
blanket suppressions to get through them; narrow `unknown` or fix the contract.

Zod owns external browser boundaries: REST responses, WebSocket frames, and
persisted browser values are parsed before they enter application state. Name a
schema `PascalCaseSchema` and derive its TypeScript type with `z.infer` so the
runtime validator and compile-time contract cannot drift. The server mirrors
this with named Pydantic v2 request, response, and event models.

Object-shaped values that cross a function, component, store, REST, or wire
boundary need a named interface, type, or schema. Local object literals are
normal implementation code; anonymous object *contracts* are what is banned.

## Run and test

```bash
uv run --locked partyline
PARTYLINE_DB=/tmp/partyline-test.db PARTYLINE_PORT=8643 uv run --locked partyline
uv run --locked coverage run -m unittest discover -s tests && uv run --locked coverage report
```

The suite must stay above 90% line and branch coverage; `coverage report` fails the build below
that. Nothing is omitted from measurement — if a line genuinely cannot be covered without a
timing-dependent test, mark it `# pragma: no cover` with a comment saying why, rather than
excluding its file. A flaky test is worse than an uncovered line.

Tests must never touch a real database, a real port, or a real CLI: use a temp `PARTYLINE_DB`,
FastAPI's `TestClient`, and fake transcript files rather than spawning a real coding CLI.

**Reach for a plain unit test first.** If a behavior can be pinned down without a browser, pin
it down without a browser: unit tests are faster, they cannot flake on rendering, and they are
what the coverage floor is measured against. A browser test earns its place only when the thing
under test genuinely needs one — layout, hit-testing, a two-sided client/server protocol.

**But if you change something visual, look at it.** `scripts/uishot.py` starts a throwaway
server and drives the real page in headless Chromium, so a UI change can be seen rather than
reasoned about — capture the state you changed and actually open the image. This has already
caught things static reading did not (icon glyphs rendering as tofu; a menu clipped by its
scroll container). Do not describe a visual change as verified when you have only checked that
it parses. Looking is the point; a committed browser test is optional.

**Beware a browser test that passes for the wrong reason.** A page reload closes its WebSocket
cleanly, timers fire on their own, elements are often visible for reasons unrelated to the
change. When a browser test protects something subtle, write the control that should fail and
confirm that it does — a reconnect test here passed until its control proved the reconnect path
was never being reached.

```bash
uv run --locked playwright install chromium                        # once
uv run --locked python -m scripts.uishot --out /tmp/partyline-ui   # the standard state set
uv run --locked python -m unittest tests/ui/test_line_menu.py -v   # browser regressions
```

**When a change is supposed to be invisible, prove it.** A refactor, a
conversion, a formatter — anything claiming not to touch the UI — should be
bracketed by:

```bash
uv run --locked python -m scripts.uidiff baseline   # before
uv run --locked python -m scripts.uidiff check      # after; non-zero if anything moved
```

It renders the standard state set — 17 states covering the rail, the menus, the
dialogs, the populated feed in both message modes, the board, the mention
popover, and the narrow layout including a shortened keyboard-up viewport — and
compares PNG bytes. Three details are load-bearing, and each was established by
measurement after the obvious assumption turned out to be wrong:

- **Every command captures twice.** Headless Chromium is *nearly* deterministic
  — about one run in three had a single state off by a hair, and not the same
  state each time. A state is only compared if two consecutive captures agree;
  one that disagrees with itself is named and excluded. This is what separates
  a timing flake (differs sometimes) from a regression (differs every time),
  without a fuzz threshold that would hide the small changes worth catching.
- **Animations are finished before each shot, not suppressed.** Forcing
  `animation-duration: 0s` looks like the obvious freeze and is wrong: `.msg`
  arrives with `fill-mode: both`, so a zero-duration animation pins it to its
  *opening* frame and the whole feed captures faded. Finite animations and
  transitions are run to their end state; only infinite ones (the LED pulse, a
  ringing jack) are paused at a fixed frame.
- **Fixtures carry a fixed timestamp.** Messages render `HH:MM`, so a baseline
  recorded at 09:15 and checked at 09:20 would otherwise differ every time.

A state that races an async load will wobble rather than fail loudly — wait for
the *response*, not for a rendered proxy. The empty feed looks identical before
and after a line loads, which is how a seeding race first showed up as an empty
mention popover rather than as an error.

A reported difference is not automatically a bug — an intended visual change
shows up here too. It has to be *looked at*, then accepted by re-running
`baseline`.

Browser tests live in `tests/ui/` and are excluded from `unittest discover` on purpose: a
missing browser must never break the ordinary suite, and they are not counted toward the
coverage floor.

## Self-learning protocol

**A surprising failure must become a durable lesson, not just a local fix.** When an agent finds
that an assumption was wrong, a test passed for the wrong reason, or tooling produced misleading
evidence:

1. State the observed symptom and the false assumption in the handoff and the relevant code
   comment or documentation.
2. Add a regression test, negative control, or diagnostic assertion that fails against the old
   behavior and proves the new behavior. A green test without its failing control is incomplete
   evidence.
3. Make the failure actionable: distinguish a real regression from an unstable capture,
   environment failure, timeout, or expected visual delta, and report the exact artifact or
   command that establishes the distinction.
4. If the lesson concerns shared state, concurrency, or scratch files, isolate each run or refuse
   unsafe overlap; never let corruption masquerade as a product failure.
5. Promote a lesson that can recur into the smallest durable guard—code, test, command, or this
   document—and mention it in the final handoff. Repeated incidents are a signal to strengthen
   the guard rather than rely on agent memory.

This protocol is part of recursive self-improvement: the system should become harder to fool after
each incident, while preserving enough evidence for the next agent to understand why the guard
exists.

### What we got wrong

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

**A silent fallback re-creates the failure it was written to prevent.** Where a guard cannot obtain
the fact it needs — an unreadable generation, an uncapturable environment — it must refuse and say
so. Substituting a plausible default is how a stripped environment, an empty `awk` field, and an
unreadable database each became invisible rather than loud.

The recurring root failure is **the code or tool running was not the code or tool being reasoned
about**: a stale cockpit, an uncommitted adapter, two harnesses sharing scratch paths, or a
replacement server inheriting a different environment from a different parent. Every
authoritative-artifact boundary must therefore be checked by the machine before a restart or proof;
agent memory and a clean main checkout are not enough.

Always test with a throwaway database and port, never a person's normal local database. Use an
inexpensive, short-running test configuration. Keep secrets in `.env` and pass any test-only
credentials only to the process command; never add them to shell profiles, source, or commits.

**Never `pkill -f partyline`** (or any pattern matching a port or the project name). It matches
the instance hosting the conversation you are in, and it matches your own shell's command line.
Find the process that owns the port and kill that pid:

```bash
ss -ltnp | grep 8643        # → users:(("partyline",pid=NNNNN,...))
kill NNNNN
```

## Working on partyline from inside partyline

This project is developed through a running copy of itself, so a careless restart drops every
participant in the room — including whoever is doing the work. The rules that make that safe:

- **The instance hosting the conversation is never the checkout being edited.** Run the
  *cockpit* from its own clone at a known-good commit; edit the *workbench* checkout. An agent
  that edits the code its own line is running has no way to load its own fix.
- **A restart does not pick up your work. Advancing the cockpit does.** The cockpit is a
  separate clone: it changes only when it is pulled. Restarting it without pulling relaunches
  the same commit it was already on, successfully and silently, and the old UI comes back
  looking like the change never happened. Run the preflight — it is not optional ceremony, it
  is the only thing standing between you and a restart that costs everyone their turn for
  nothing:

  ```bash
  uv run --locked python -m scripts.cockpit check     # is the workbench fit to deploy?
  uv run --locked python -m scripts.cockpit deploy    # check, fast-forward the cockpit, verify
  uv run --locked python -m scripts.cockpit plan "line name" --debrief "what to continue"
  uv run --locked python -m scripts.cockpit arm --pid NNNNN  # schedule the exact generation
  # Add --manual-offer only when a human should inspect the plan first.
  ```

  `check` refuses a dirty tree, a missing or **stale** bundle (it rebuilds and diffs, which is
  the one way to catch `frontend/src/` edits that were never built), and unpushed commits —
  the cockpit pulls from the remote, so work that is only committed locally cannot reach it.
  `deploy` then fast-forwards the cockpit and asserts it is at the same sha as the workbench.
  `check`, `deploy`, and `plan` do not restart anything. After the plan and clearances, `arm` is
  the only supported trigger: it invokes a reviewed Python executable through systemd without
  inline shell, then reads back the timer, service command, and exact PID generation before
  reporting success. A failed trigger remains a named failed unit, and an automatic plan left
  unclaimed at attempt zero becomes a preflight finding after five minutes.
- **Test on a throwaway port and database**, one per person, so several agents can test at once
  without colliding: `PARTYLINE_DB=/tmp/<you>.db PARTYLINE_PORT=864x uv run --locked partyline`.
- **Restarting the cockpit is a scheduled act, not a side effect.** This is the
  **recursive self-improvement** path: agents use their own judgement, and it does not require
  mandatory human input when an agent has judged the tree safe. The full ceremony remains: everyone
  commits and posts status →
  `scripts.cockpit deploy` passes → run `scripts.cockpit plan` for the requesting line with a
  concrete continuation debrief → announce → confirm nobody is mid-turn → restart. Planning does
  not restart anything. A cockpit plan is automatic by default and is consumed in the background
  after startup; use `--manual-offer` when a human should inspect it first. Only the exact line and
  plan token can consume it. Automatic or accepted plans resume each saved process fully and wait
  for its adapter readiness signal before starting the next one. That strict sequence is
  load-bearing for CLIs whose concurrent resume discovery can claim the same rollout. Uncommitted
  work in an agent's head does not survive; committed work always does, and chat history plus the
  debrief are replayed on resume. A slow but live adapter remains attached while the sequence
  advances; a genuine exit is the failure case. The loop must close without a human: a required
  button or manual refresh is a correctness bug in the dogfood path, not a normal ceremony step.
- **The dogfood cornerstone is proof, not permission.** A restart may be armed only after machine
  preflight is green, every participant has explicitly cleared, and no known finding remains; any
  agent may block it. Automatic recovery must claim the persisted plan through a durable exclusive
  lease with expiry and reclaim, then reattach sequentially and re-sync open tabs. Green local gates
  are necessary but not sufficient: the same workflow must run on the real cockpit, and the
  post-restart proof must include each process's identity, live attachment state, plan completion,
  and an honest transcript with no unexplained warnings.
- **The automatic lease has one explicit lifecycle.** Claim with
  `claim_restart_plan(mode, owner, lease_seconds)`; renew with
  `renew_restart_plan_claim(token, owner, lease_seconds)` while waiting; release with
  `release_restart_plan_claim(token, owner)` on cancellation or error; and complete only after the
  final outcome with `complete_restart_plan(token, owner)`. A lost or expired owner is reclaimable,
  and a runner that loses ownership must launch no further processes.
- **Automatic recovery is bounded.** A successful automatic claim increments `attempt_count`
  atomically. The first run with unconfirmed continuation receipt preserves exactly one retry; the
  second consumes the stale plan and posts an actionable warning naming every unconfirmed process
  and the debrief's first line. The processes remain live and `reattaching` is cleared—unconfirmed
  input is not evidence that a healthy process should be killed.
- **Restart proof has two separate browser claims.** The untouched cockpit tab proves hands-off
  reload and the recovered snapshot. A deliberate socket-drop control must prove reconnect resync
  by changing server state during the gap, observing `tab_reloaded=False`, and verifying catch-up.
  The full proof also checks four self-reported process identities, four `/api/running` entries, a
  deleted completed plan, and no unexplained `⚠` transcript lines; a coordinator summary alone is
  not sufficient.
- **Nobody may be mid-turn when the restart lands — including whoever triggers it.** An agent
  killed mid-turn comes back to a CLI that resumes the interrupted turn and asks it to continue,
  so it posts a stray fragment into the room on wake. If you schedule the restart with a delayed
  detached command, the delay has to outlast *your own* turn, not just your announcement.
- **Wait for the exact old server PID to exit before launching its replacement.** A cleared port is
  not an exit signal: Uvicorn releases the listener before lifespan teardown finishes, which once
  let the retiring server overwrite a newly resumed attachment. Signal only the PID that owned the
  port, wait until that PID no longer exists, and only then launch the cockpit. Runtime-owner guards
  reject late callbacks once both generations support them; they cannot retroactively protect the
  first deployment from an older binary that still performs unconditional writes.
- **Preserve the exact old server's execution environment across a scheduled restart.** A transient
  systemd unit does not inherit the interactive shell's `PATH` or other launch-time variables. Read
  `/proc/<pid>/environ` from the verified old generation before signalling it and pass that mapping
  to the replacement with `execve`; an unreadable environment is a safe refusal, not permission to
  launch from systemd's defaults. The replacement still reloads the cockpit's `.env` from its
  working directory during normal startup.
- **Adapter changes do not need a restart** — `POST /api/adapters/reload` re-executes adapter
  packages in place. Changes to the base class, loader, server, or frontend do.
- Prefer changes that make a restart cheaper (resume support, adopting live attachments,
  liveness reporting) over changes that assume restarts are rare.

## Code style

- **Write functionally where it pays.** Prefer pure functions: same inputs, same outputs, no
  hidden state read or written. Pass behavior as arguments — this codebase already does it with
  the `post` and `on_status` callbacks an adapter is constructed with, and that is why an
  adapter can be tested without a server.
- **Push side effects to the edges.** Database writes, pty writes, subprocess spawns, and
  broadcasts belong in a thin outer layer; the logic that decides *what* to do should be a
  function you can call in a test with a dict and assert on the return value. When a function is
  hard to test, that is the design telling you the effect is too deep inside it.
- **Production source files are capped at 300 lines.** Run `./check-code-lines` before every
  commit and before cockpit preflight. It covers tracked `.py`, `.ts`, and `.svelte` files only;
  tests and third-party code are excluded. The temporary entries in
  `line-length-exceptions.txt` are existing debt: they must never grow, no new exception may be
  added, and each entry should be removed when its file is split below the cap. Use
  `./check-code-lines --all` to see the remaining debt. A `.svelte` file counts its markup and
  styles too — a component that needs 300 lines is usually two components and a shared stylesheet.
- **`main` is protected.** Work on a branch and open a pull request; do not push directly to
  `main`. GitHub requires the `backend`, `frontend`, `code-line-limits`,
  `conventional-commits`, and `version-policy` checks before merge. The CI commands are
  `uv run --locked ruff check .`, the coverage test command in this file,
  `./check-code-lines`, and `cd frontend && npm run verify`.
- **Lint must pass**: `uv run --locked ruff check .`, clean, before every commit. The autoformatter is
  deliberately not enforced — this codebase hand-wraps for readability, and `ruff format` would
  undo that. Match the surrounding style instead.

## Adapter rules

- One bundled adapter package lives at `partyline/adapters/bundled/<id>/` and has a manifest
  (`adapter.toml`) plus an entrypoint (`adapter.py` defining `PartylineAdapter`).
- Prefer tailing the process's structured transcript or log. Never post raw terminal-screen
  contents as chat messages. A raw stream may be quiescence-flushed only for intentionally
  stream-based adapters.
- A transcript must be located unambiguously. If the CLI can be told which session id or session
  directory to use, pin it; if discovery has to fall back to matching on working directory and
  start time, the adapter must also *claim* the file it resolves, so a second attachment in the
  same directory cannot latch onto the first one's transcript and repost its messages.
- Anything injected into a pty must assume a person may be typing: use bracketed paste and
  then Enter.
- Keep discovery, manifest validation, import, and reload behavior compatible with external
  adapter repositories. See `skills/add-process-adapter/SKILL.md` before changing this surface.
- **Adapters bring their own tests, and those tests never run the vendor's CLI.** Test the
  parsing, claiming, and lifecycle logic against fixture transcript files; do not assert on how
  a third-party tool behaves, or the suite breaks on someone else's release schedule. This
  applies to the bundled packages here and to external adapter repositories alike.

## Data and releases

- Put schema changes in idempotent entries in `MIGRATIONS`; do not edit an already-applied
  schema definition.
- Use one-line Conventional Commits: `type(scope): subject`. Types are `feat`, `fix`, `docs`,
  `refactor`, `test`, and `chore`.
- Versioning is semver, single-sourced from `partyline/__init__.py`. Bump in the same commit:
  feature → minor, fix → patch, breaking change → major. Documentation, test, refactor, and
  chore changes do not bump the version.
- After every required check passes on `main`, a version-changing merge creates the annotated
  tag `v<version>`. A merge whose version is unchanged creates no tag. Existing version tags
  are immutable: automation must accept an idempotent match and refuse a conflicting target.
