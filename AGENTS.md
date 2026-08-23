# AGENTS.md

The contract for coding agents in this repository. Depth lives in `docs/` and `skills/`;
this file holds only the rules you must not break.

## What this is

partyline is a local chatroom that attaches real interactive processes to conversations
through ptys. The pty and transcript-tailing design are load-bearing. Read `README.md` first.

| DO | DO NOT |
| --- | --- |
| Keep every process a real interactive process in a pty | Substitute a headless invocation or an SDK call |
| Post assistant speech from structured transcripts | Turn terminal screen contents into chat messages |

## Layout

- `partyline/server.py` — FastAPI app: REST, WebSocket, and mention routing
- `partyline/adapters/` — built-in process adapters and adapter discovery
- `partyline/db.py` + `partyline/db_schema.py` — SQLite queries, schema, and migrations
- `frontend/` — TypeScript web client: Vite + Svelte 5 + Tailwind (`docs/frontend.md`)
- `partyline/static/` — build output, committed
- `docs/` — depth: `frontend.md`, `dogfooding.md`, `adapters.md`, `lessons.md`, `releases.md`
- `skills/` — procedures: `add-process-adapter/`, `adversarial-review/`, `verify-visual-change/`

| DO | DO NOT |
| --- | --- |
| Regenerate `partyline/static/` with `npm run build` | Edit `partyline/static/` by hand |

## Gates — all must pass before every commit

```bash
uv run --locked ruff check .        # lint (no autoformatter: match surrounding style by hand)
./scripts/capped-test               # full suite under a 2 GB memory cap
uv run --locked coverage report     # ≥90% line and branch, nothing omitted
./check-code-lines                  # production files ≤300 lines
cd frontend && npm run verify       # format:check + lint + svelte-check + tests
```

A hung allocating test has twice taken this whole machine down (19 GB and 31 GB incidents,
`docs/lessons.md`); `./scripts/capped-test` exits 137 when a test *allocated without bound*,
not when an assertion failed. The 300-line cap is a context budget, not a style rule.

| DO | DO NOT |
| --- | --- |
| Run the suite only through `./scripts/capped-test` | Run the test suite uncapped on a developer machine |
| Use a temp `PARTYLINE_DB`, FastAPI `TestClient`, and fixture transcripts | Let a test touch a real database, port, or CLI |
| — | Run `tests.test_grok_adapter` bare on the dogfood machine |
| Mark a genuinely uncoverable line `# pragma: no cover` with a reason | Omit files from coverage |
| Prefer a plain unit test | Write a browser test (`tests/ui/`) except for layout, hit-testing, or two-sided protocols |
| Split files along functional boundaries at the 300-line cap | Grow `line-length-exceptions.txt` — it is frozen debt |
| Look at every visual change; prove invisible ones with `skills/verify-visual-change/SKILL.md` | Claim a visual change is verified from reading code |

## Frontend

partyline installs as a Python package, so a fresh clone must never need Node — the built
bundle is committed. TypeScript is strict through compiler and ESLint. Full conventions:
`docs/frontend.md`.

| DO | DO NOT |
| --- | --- |
| Run `npm run verify` green, then `npm run build` → `partyline/static/`, and commit the bundle | Ship frontend changes without the rebuilt bundle |
| Give every boundary-crossing value a named contract — Zod in the browser, Pydantic v2 on the server | Use `any`, double casts, or blanket suppressions |
| Keep the release version single-sourced in `partyline/__init__.py` | Treat `static/build.json` as anything but a bundle identifier |

## Run

```bash
uv run --locked partyline                                                  # default bind
PARTYLINE_DB=/tmp/<you>.db PARTYLINE_PORT=864x uv run --locked partyline   # throwaway
```

`pkill -f partyline` matches the instance hosting your own conversation and your own shell.
Find the pid that owns the port instead:

```bash
ss -ltnp | grep 8643        # → users:(("partyline",pid=NNNNN,...))
kill NNNNN
```

| DO | DO NOT |
| --- | --- |
| Test against a throwaway database and port — one per person | Point anything at a real local database |
| Keep secrets in `.env` | Put secrets in shell profiles, source, or commits |
| Kill the pid that owns the port | Ever run `pkill -f partyline` |

## Working on partyline from inside partyline

This project is developed through a running copy of itself, and a careless restart drops every
participant including you. The procedure is `docs/dogfooding.md` — read it before any cockpit
deploy or restart.

| DO | DO NOT |
| --- | --- |
| Run the *cockpit* from its own clone and edit the *workbench* | Host the conversation from the checkout being edited |
| Deploy only via `scripts.cockpit check → deploy → plan → arm` | Use any restart trigger other than `arm` |
| Arm only after preflight is green, every planned participant has explicitly cleared, and no known finding remains | Restart without deploying — that only starts the old code again |
| Prove recovery afterward: identity, continuation receipts, live attachment state | Let anyone be mid-turn when the restart lands, including yourself |

## Self-learning

A surprising failure must become a durable lesson. The full protocol and the distilled
patterns live at the top of `docs/lessons.md`; read it when an incident feels familiar —
most of them rhyme.

| DO | DO NOT |
| --- | --- |
| State the false assumption, add a regression test or guard that fails against the old behavior, and record it in `docs/lessons.md` | Fix a surprising failure and move on without a durable lesson |

## Adapters

Rules and depth: `docs/adapters.md` and `skills/add-process-adapter/SKILL.md`.

| DO | DO NOT |
| --- | --- |
| Tail the process's structured transcript | Post raw screen contents |
| Locate and *claim* the transcript unambiguously | Let two attachments resolve the same transcript |
| Send pty input as bracketed paste then Enter | — |
| Ship the adapter's own tests | Run the vendor's CLI in tests |

## Process and releases

| DO | DO NOT |
| --- | --- |
| Append new idempotent entries to `MIGRATIONS` in `partyline/db_schema.py` for schema changes | Edit an already-applied migration entry |
| Write one-line Conventional Commits — `type(scope): subject` with `feat`, `fix`, `docs`, `refactor`, `test`, `chore` | Add a commit body |
| Bump semver in `partyline/__init__.py` in the same commit: feature → minor, fix → patch, breaking → major | Bump for docs, test, refactor, or chore commits |
| Branch and open a PR; pass `backend`, `frontend`, `code-line-limits`, `conventional-commits`, `version-policy` | Push to `main` — it is protected |
| Review adversarially in a throwaway worktree pinned to the exact SHA (`skills/adversarial-review/SKILL.md`) | Review on a shared workbench or a mutable branch |
| Let CI create tags — tags are the release record | Hand-create a GitHub Release (`docs/releases.md`) |
