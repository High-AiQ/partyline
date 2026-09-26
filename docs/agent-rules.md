# Agent rules (full)

The contract for coding agents in this repository. Depth lives in `docs/` and `skills/`;
this file holds only the rules you must not break.

## What this is

partyline is a local chatroom that attaches real interactive processes to conversations
through ptys. The pty and transcript-tailing design are load-bearing. Read `README.md` first.

| DO | DO NOT |
| --- | --- |
| Keep every process a real interactive process in a pty | Substitute a headless invocation or an SDK call |
| Post assistant speech from structured transcripts | Turn terminal screen contents into chat messages |
| React when a reaction says it all: one on a machine's message wakes that process privately, as a note in its next digest | Expect a reaction to ring the room or leave a transcript line — a reaction on a human's message posts and wakes nothing |

## Layout

- `partyline/server.py` — FastAPI app: REST, WebSocket, and mention routing
- `partyline/adapters/` — built-in process adapters and adapter discovery
- `partyline/db.py` + `partyline/db_schema.py` — SQLite queries, schema, and migrations
- `frontend/` — TypeScript web client: Vite + Svelte 5 + Tailwind (`docs/frontend.md`)
- `partyline/static/` — build output, committed
- `docs/` — depth: `frontend.md`, `restart.md`, `adapters.md`, `lessons.md`, `releases.md`
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
| Clear inherited `PARTYLINE_*`, then set `PARTYLINE_DB=/tmp/<run>.db` for gates | Let imports fall through to `~/.partyline.db`, where another branch's migration can alter the schema |
| Run tests through `./scripts/capped-test`, which clears inherited Partyline connection variables and sets a fresh temporary database | Let test imports inherit the live service's database, API coordinates, token, or media directory |
| Refuse to run tests unless `memory.max` inside the transient scope or inherited child `RLIMIT_AS` proves the cap; put every Linux attached process in its own verified systemd scope (default 4G, configurable with `PARTYLINE_PROCESS_MEMORY_LIMIT`) | Run a suite or attached CLI when its effective memory cap cannot be verified |
| Check installed Partyline services for `OOMPolicy=continue` and finite `MemoryMax` below host RAM; for foreground launches, create a scope automatically and verify `memory.max` and `memory.oom.group=0`; verify attached-process scopes by reading `memory.max` | Require a service installation for the documented quick start, or rely on an unverified memory setting |
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
| Prefer Tailwind utilities for component looks; depth in `docs/frontend.md` | Grow scoped `<style>` for layout/color/typography Tailwind already covers |
| Give every boundary-crossing value a named contract — Zod in the browser, Pydantic v2 on the server | Use `any`, double casts, or blanket suppressions |
| Keep the release version single-sourced in `partyline/__init__.py` | Treat `static/build.json` as anything but a bundle identifier |

## Run

```bash
uv run --locked partyline                                                  # default bind
PARTYLINE_DB=/tmp/<you>.db PARTYLINE_PORT=864x uv run --locked partyline   # throwaway
```

Killing by pattern-matching the word partyline across every command line (the full-cmdline
form of pkill) matches the instance hosting your own conversation and your own shell. The
literal command is deliberately not written here: Grok's shell guard refuses any script that
quotes it, including a captain's brief that copied this rule.
Find the pid that owns the port instead:

```bash
ss -ltnp | grep 8643        # → users:(("partyline",pid=NNNNN,...))
kill NNNNN
```

| DO | DO NOT |
| --- | --- |
| Test against a throwaway database and port — one per person | Point anything at a real local database |
| Keep secrets in `.env` | Put secrets in shell profiles, source, or commits |
| Kill the pid that owns the port | Ever kill by matching the word partyline across all command lines |

## Working on partyline from inside partyline

This project is developed through a running copy of itself, and a careless restart drops every
participant including you. The procedure is `docs/restart.md` — read it before filing a restart
request.

| DO | DO NOT |
| --- | --- |
| Before planning from a stale clean checkout, the captain refreshes its attached checkout with `git pull --ff-only`; after merge, the captain fast-forwards it, verifies `git rev-parse HEAD`, runs `uv sync --locked`, then requests a restart; use HTTPS with `git -c credential.helper='!gh auth git-credential'` if fenced SSH is unavailable | Ask the person to pull; skip a dirty-checkout ask; reset, stash, or discard in a person's checkout |
| File a restart request; use human approval or explicitly delegated local operator approval (`docs/restart.md`) | Restart without saving the fleet-wide recovery plan |
| Trust the automatic mid-turn mark and private continue notice to resume interrupted work | Delay approval waiting for every participant to go idle first |
| Prove recovery afterward: identity, continuation receipts, live attachment state | Report success without checking `/api/running` |

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
| Give each attachment a claim marker of its own and relay no transcript speech until the session records it | Adopt a session by directory scan order or mtime, or relay one carrying another attachment's marker |
| Send pty input as bracketed paste then Enter | — |
| When a CLI crashes before creating a transcript or session, ask a person to check the host kernel log (`dmesg` or `journalctl -k`) around the failure time | Treat a fenced process's inability to read the kernel log as evidence that the kernel was healthy, or infer a provider cause from a generic no-session timeout |
| Ship the adapter's own tests | Run the vendor's CLI in tests |

## The write fence

Every attached process runs inside a platform sandbox where managed
repositories and the Partyline database are read-only by default. Full
detail: `docs/write-fence.md`.

| DO | DO NOT |
| --- | --- |
| Launch fenced by default and fail closed — no bubblewrap means no process | Start a process unconfined, or treat the flag as a permanent off switch |
| Protect active managed repositories and the Partyline database by default; grant extra write scope only by person or captain-above decision | Assume an unknown repository is protected, or let a line widen its own scope |
| Share git via the mirror: objects shared, refs/logs/packed-refs copy-on-write, sibling worktrees read-only | Bind the parent `.git`, another checkout, or a sibling line's metadata writable |
| Review the child’s reported SHA in a Partyline-managed review worktree; mirrored refs are private per line and shared by its processes | Judge a child’s progress from its worktree as seen by the captain: accepted refs can make newer committed work appear uncommitted |
| Replace a CLI sandbox that cannot nest (codex's bwrap) with `fence_args`, only while fenced | Run two sandboxes at once, or leave a CLI's sandbox as the only one on an unfenced host |

## Process and releases

| DO | DO NOT |
| --- | --- |
| Append new idempotent entries to `MIGRATIONS` in `partyline/db_schema.py` for schema changes | Edit an already-applied migration entry |
| Write one-line Conventional Commits — `type(scope): subject` with `feat`, `fix`, `docs`, `refactor`, `test`, `chore` | Add a commit body |
| Bump semver in `partyline/__init__.py` in the same commit: feature → minor, fix → patch, breaking → major | Bump for docs, test, refactor, or chore commits |
| Branch and open a PR; pass `backend`, `frontend`, `code-line-limits`, `conventional-commits`, `version-policy` | Push to `main` — it is protected |
| Ensure an adversarial review in a throwaway worktree pinned to the exact SHA is completed before accepting — the same bar for a child line's branch/report and a same-line worker's hand-off — and review again at your own scope when work pops up, reusing evidence only for the same unchanged SHA (`skills/adversarial-review/SKILL.md`) | Review on a shared workbench or a mutable branch, accept a report or a delegate's "done" without the review having happened, or treat a lower captain's acceptance as your own |
| On a captained line, push only as the captain, after review; a worker commits locally and hands over the SHA | Let a worker push on a captained line, or push before the review is completed |
| Let CI create tags — tags are the release record | Hand-create a GitHub Release (`docs/releases.md`) |
