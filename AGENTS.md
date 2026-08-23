# AGENTS.md

The contract for coding agents in this repository. Depth lives in `docs/` and `skills/`;
this file holds only the rules you must not break.

## What this is

partyline is a local chatroom that attaches real interactive processes to conversations through
ptys. Read `README.md` first. **The pty and transcript-tailing design are load-bearing: never
replace an interactive process with a headless invocation or screen scraping.**

## Layout

- `partyline/server.py` — FastAPI app: REST, WebSocket, and mention routing
- `partyline/adapters/` — built-in process adapters and adapter discovery
- `partyline/db.py` + `partyline/db_schema.py` — SQLite queries, schema, and migrations
- `frontend/` — TypeScript web client: Vite + Svelte 5 + Tailwind (`docs/frontend.md`)
- `partyline/static/` — **build output, committed.** Never edit by hand
- `docs/` — depth: `frontend.md`, `dogfooding.md`, `adapters.md`, `lessons.md`, `releases.md`
- `skills/` — procedures: `add-process-adapter/`, `adversarial-review/`,
  `verify-visual-change/`

## Gates — all must pass before every commit

```bash
uv run --locked ruff check .        # lint (no autoformatter: match surrounding style by hand)
./scripts/capped-test               # full suite under a 2 GB memory cap
uv run --locked coverage report     # ≥90% line and branch, nothing omitted
./check-code-lines                  # production files ≤300 lines
cd frontend && npm run verify       # format:check + lint + svelte-check + tests
```

- **Never run the test suite uncapped on a developer machine.** A hung allocating test has
  twice taken this whole machine down (19 GB and 31 GB incidents, `docs/lessons.md`).
  `./scripts/capped-test` exits 137 when a test *allocated without bound*, not when an
  assertion failed. Never run `tests.test_grok_adapter` bare on the dogfood machine.
- Tests never touch a real database, port, or CLI: temp `PARTYLINE_DB`, FastAPI `TestClient`,
  fixture transcripts. A line that cannot be covered gets `# pragma: no cover` with a reason.
- Prefer a plain unit test; browser tests (`tests/ui/`, excluded from coverage) are only for
  layout, hit-testing, or two-sided protocols.
- **The 300-line cap is a context budget.** Split along functional boundaries instead of asking
  for an exception; `line-length-exceptions.txt` is frozen debt — it may never grow.
- If you change something visual, look at it; if a change claims to be invisible, prove it:
  `skills/verify-visual-change/SKILL.md`.

## Frontend musts

`npm run verify` green, then `npm run build` → `partyline/static/`, **committed** — partyline
installs as a Python package, so a fresh clone must never need Node. TypeScript is strict
through compiler and ESLint: no `any`, double casts, or blanket suppressions. Every value
crossing a boundary gets a named contract — Zod in the browser, Pydantic v2 on the server.
`partyline/__init__.py` owns the release version; `static/build.json` identifies only the
bundle. Full conventions: `docs/frontend.md`.

## Run

```bash
uv run --locked partyline                                   # default bind
PARTYLINE_DB=/tmp/<you>.db PARTYLINE_PORT=864x uv run --locked partyline   # throwaway
```

Always test against a throwaway database and port — one per person, never a real local
database. Keep secrets in `.env`, never in shell profiles, source, or commits.

**Never `pkill -f partyline`** — it matches the instance hosting your own conversation and
your own shell. Find the pid that owns the port and kill that:

```bash
ss -ltnp | grep 8643        # → users:(("partyline",pid=NNNNN,...))
kill NNNNN
```

## Working on partyline from inside partyline

This project is developed through a running copy of itself; a careless restart drops every
participant including you. The procedure is `docs/dogfooding.md` — **read it before any
cockpit deploy or restart.** The rules that make it safe:

- The instance hosting the conversation is never the checkout being edited: run the *cockpit*
  from its own clone, edit the *workbench*.
- A restart does not pick up your work; advancing the cockpit does. The only deploy path is
  `scripts.cockpit check → deploy → plan → arm`; `arm` is the only supported trigger.
- Arm only after machine preflight is green, every planned participant has explicitly cleared,
  and no known finding remains. Green gates are necessary, not sufficient — the post-restart
  proof must cover identity, continuation receipts, and live attachment state.
- Nobody may be mid-turn when the restart lands, including whoever triggers it.

## Self-learning

A surprising failure must become a durable lesson: state the false assumption, add a
regression test or guard that fails against the old behavior, and record it in
`docs/lessons.md` — the full protocol and the distilled patterns live at the top of that
file. Read it when an incident feels familiar; most of them rhyme.

## Adapters

Rules and depth: `docs/adapters.md` and `skills/add-process-adapter/SKILL.md`. The musts:
tail the process's structured transcript, never post raw screen contents; locate and *claim*
the transcript unambiguously; pty input uses bracketed paste then Enter; adapters bring their
own tests, which never run the vendor's CLI.

## Process and releases

- Schema changes are new idempotent entries appended to `MIGRATIONS` in
  `partyline/db_schema.py`; never edit an applied entry.
- One-line Conventional Commits, no body: `type(scope): subject` with `feat`, `fix`, `docs`,
  `refactor`, `test`, `chore`.
- Semver, single-sourced from `partyline/__init__.py`, bumped in the same commit: feature →
  minor, fix → patch, breaking → major. Docs/test/refactor/chore don't bump.
- **`main` is protected.** Branch, open a PR, and pass the required checks (`backend`,
  `frontend`, `code-line-limits`, `conventional-commits`, `version-policy`).
- Adversarial reviews run in a throwaway worktree pinned to the exact commit SHA, never a shared
  workbench or mutable branch. Verdicts cite that SHA and the commands actually run; see
  `skills/adversarial-review/SKILL.md`.
- Tags are the release record; CI creates them. Never hand-create a GitHub Release
  (`docs/releases.md`).
