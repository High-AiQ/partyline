# AGENTS.md

Guidance for coding agents working in this repository. This file is the contract every agent
must know; depth lives in `docs/` and `skills/`, each named where it applies.

## What this is

partyline is a local chatroom that attaches real interactive processes to conversations through
ptys. Read `README.md` first. The pty and transcript-tailing design are load-bearing: do not
replace an interactive process with a headless invocation or screen scraping.

## Layout

- `partyline/server.py` — FastAPI app: REST, WebSocket, and mention routing
- `partyline/adapters/` — built-in process adapters and adapter discovery
- `partyline/db.py` — SQLite schema, migrations, and queries
- `frontend/` — the TypeScript web client: Vite + Svelte 5 + Tailwind (see `docs/frontend.md`)
- `partyline/static/` — **build output, committed.** Never edit by hand
- `docs/` — depth: `frontend.md`, `dogfooding.md`, `adapters.md`, `lessons.md`
- `skills/` — procedures: `add-process-adapter/`, `verify-visual-change/`

## Frontend

Full contracts and conventions are in `docs/frontend.md`. The musts:

```bash
cd frontend
npm run verify    # format:check + lint + svelte-check + tests — the gate, same command CI runs
npm run build     # → partyline/static/  (do this before committing UI changes)
```

**`npm run verify` must pass before every frontend commit.** **`partyline/static/` is committed
on purpose** — partyline installs as a Python package, so a fresh clone must not need Node.
Rebuild before you commit, or you ship a stale UI that matches none of the source.

**Release and frontend build identity are different facts.** `partyline/__init__.py` is the
single source of truth for the semver release; `partyline/static/build.json` identifies only the
frontend bundle and decides whether an open document must reload. A reconnect must still refresh
the release version even when the build ID is unchanged.

TypeScript is strict from the compiler through ESLint — do not introduce `any`, double casts, or
blanket suppressions. Zod owns external browser boundaries (REST, wire, persisted values), with
named schemas and `z.infer` types; the server mirrors this with named Pydantic v2 models.
Object-shaped values that cross a boundary need a named contract.

## Run and test

```bash
uv run --locked partyline
PARTYLINE_DB=/tmp/partyline-test.db PARTYLINE_PORT=8643 uv run --locked partyline
uv run --locked partyline --host 127.0.0.1 --port 8643
PARTYLINE_HOST=127.0.0.1 PARTYLINE_PORT=8643 uv run --locked partyline
./scripts/capped-test && uv run --locked coverage report
uv run --locked coverage run -m unittest discover -s tests && uv run --locked coverage report
```

**Run the suite through `./scripts/capped-test` on a developer machine.** It runs the same
command under a 2 GB kernel memory cap. A hung test that allocates has twice taken this whole
machine down instead of failing — 19 GB on 2026-08-14, 31 GB on 2026-08-19 — and the second
one killed the running cockpit, every attached CLI, and systemd's boot with it. A healthy full
run peaks around 165 MB, so the cap has roughly twelve times the headroom an honest test needs.
Exit 137 from it means *allocated without bound*, not *assertion failed*. Use
`--memory` to change the cap and pass any other command after `--`. CI runs the bare command;
the cap is for the machine a person is sitting at.

The suite must stay above 90% line and branch coverage; `coverage report` fails the build below
that. Nothing is omitted from measurement — a line that genuinely cannot be covered gets
`# pragma: no cover` with a reason, never a file exclusion. A flaky test is worse than an
uncovered line.

Tests must never touch a real database, a real port, or a real CLI: use a temp `PARTYLINE_DB`,
FastAPI's `TestClient`, and fake transcript files rather than spawning a real coding CLI.

**Reach for a plain unit test first.** A browser test earns its place only when the thing under
test genuinely needs one — layout, hit-testing, a two-sided protocol. Browser tests live in
`tests/ui/` and are excluded from `unittest discover` and the coverage floor on purpose.

**If you change something visual, look at it; if a change claims to be invisible, prove it.**
The screenshot and pixel-diff procedure — `scripts/uishot.py`, `scripts/uidiff.py`, and the
traps already found in both — is `skills/verify-visual-change/SKILL.md`. Do not describe a
visual change as verified when you have only checked that it parses.

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
5. Promote a lesson that can recur into the smallest durable guard — code, test, command, or an
   entry in `docs/lessons.md` — and mention it in the final handoff. Repeated incidents are a
   signal to strengthen the guard rather than rely on agent memory.

The full case law — every false assumption, its evidence, and its guard — is `docs/lessons.md`.
Read it when an incident feels familiar; most of them rhyme. The distilled patterns:

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

## Safety

Always test with a throwaway database and port, never a person's normal local database — one per
person, so several agents can test at once: `PARTYLINE_DB=/tmp/<you>.db PARTYLINE_PORT=864x`.
Keep secrets in `.env` and pass any test-only credentials only to the process command; never add
them to shell profiles, source, or commits.

**Never `pkill -f partyline`** (or any pattern matching a port or the project name). It matches
the instance hosting the conversation you are in, and it matches your own shell's command line.
Find the process that owns the port and kill that pid:

```bash
ss -ltnp | grep 8643        # → users:(("partyline",pid=NNNNN,...))
kill NNNNN
```

## Working on partyline from inside partyline

This project is developed through a running copy of itself, so a careless restart drops every
participant in the room — including whoever is doing the work. The operational procedure is
`docs/dogfooding.md`; **read it before advising or performing any cockpit deploy or restart**
rather than reconstructing the procedure from memory. The rules that make it safe:

- **The instance hosting the conversation is never the checkout being edited.** Run the
  *cockpit* from its own clone; edit the *workbench* checkout. An agent that edits the code its
  own line is running has no way to load its own fix.
- **A restart does not pick up your work. Advancing the cockpit does.** Restarting without
  deploying relaunches the same commit, successfully and silently. The only deploy path:

  ```bash
  uv run --locked python -m scripts.cockpit check     # is the workbench fit to deploy?
  uv run --locked python -m scripts.cockpit deploy    # check, fast-forward the cockpit, verify
  uv run --locked python -m scripts.cockpit plan "line name" --debrief "what to continue"
  uv run --locked python -m scripts.cockpit arm --pid NNNNN  # schedule the exact generation
  ```

  `check` refuses a dirty tree, a stale bundle, and unpushed commits; `deploy` fast-forwards the
  cockpit and asserts it matches the workbench; neither restarts anything. `arm` is the only
  supported trigger. Follow a deploy with its restart promptly: new tabs reload-loop against the
  old server while the two disagree.
- **The dogfood cornerstone is proof, not permission.** Arm only after machine preflight is
  green, every planned participant has explicitly cleared, and no known finding remains; any
  participant may block. Green local gates are necessary but not sufficient — the post-restart
  proof must cover each process's identity and continuation receipt, live attachment state, plan
  completion, and an honest transcript with no unexplained warnings. A required button or manual
  refresh in the recovery path is a correctness bug, not a ceremony step.
- **Nobody may be mid-turn when the restart lands — including whoever triggers it.** Uncommitted
  work in an agent's head does not survive; committed work always does, and chat history plus
  the debrief are replayed on resume.

## Code style

- **Write functionally where it pays.** Prefer pure functions: same inputs, same outputs, no
  hidden state read or written. Pass behavior as arguments — this codebase already does it with
  the `post` and `on_status` callbacks an adapter is constructed with, and that is why an
  adapter can be tested without a server.
- **Push side effects to the edges.** Database writes, pty writes, subprocess spawns, and
  broadcasts belong in a thin outer layer; the logic that decides *what* to do should be a
  function you can call in a test with a dict and assert on the return value. When a function is
  hard to test, that is the design telling you the effect is too deep inside it.
- **Production source files are capped at 300 lines.** The cap is a context budget: oversized
  files overwhelm an agent's working context and hide the seams where behavior should split. When
  a file approaches the cap, do not request a larger exception — decompose it along functional
  boundaries into small pure functions and well-placed modules, keeping shared logic DRY. Run
  `./check-code-lines` before every commit and before cockpit preflight. It covers tracked `.py`,
  `.ts`, and `.svelte` files only; tests and third-party code are excluded. The temporary entries
  in `line-length-exceptions.txt` are existing debt: they must never grow, no new exception may be
  added, and each entry should be removed when its file is split below the cap.
- **`main` is protected.** Work on a branch and open a pull request; do not push directly to
  `main`. GitHub requires the `backend`, `frontend`, `code-line-limits`,
  `conventional-commits`, and `version-policy` checks before merge. The CI commands are
  `uv run --locked ruff check .`, the coverage test command in this file,
  `./check-code-lines`, and `cd frontend && npm run verify`.
- **Lint must pass**: `uv run --locked ruff check .`, clean, before every commit. The
  autoformatter is deliberately not enforced — this codebase hand-wraps for readability, and
  `ruff format` would undo that. Match the surrounding style instead. (The frontend is the
  opposite: Prettier's formatting is the gate there.)

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
