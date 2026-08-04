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
- `partyline/static/index.html` — frontend (vanilla JavaScript; no build step)
- `skills/add-process-adapter/` — procedure and contract for new adapters

## Run and test

```bash
uv run partyline
PARTYLINE_DB=/tmp/partyline-test.db PARTYLINE_PORT=8643 uv run partyline
uv run coverage run -m unittest discover -s tests && uv run coverage report
```

The suite must stay above 90% line and branch coverage; `coverage report` fails the build below
that. Nothing is omitted from measurement — if a line genuinely cannot be covered without a
timing-dependent test, mark it `# pragma: no cover` with a comment saying why, rather than
excluding its file. A flaky test is worse than an uncovered line.

Tests must never touch a real database, a real port, or a real CLI: use a temp `PARTYLINE_DB`,
FastAPI's `TestClient`, and fake transcript files rather than spawning a real coding CLI.

**If you change the frontend, look at it.** `scripts/uishot.py` starts a throwaway server and
drives the real page in headless Chromium, so a UI change can be seen rather than reasoned
about — capture the state you changed and actually open the image. Reviewing a screenshot has
already caught things static reading did not (icon glyphs rendering as tofu; a menu clipped by
its scroll container). Do not describe a visual change as verified when you have only checked
that it parses.

```bash
uv run playwright install chromium                        # once
uv run python -m scripts.uishot --out /tmp/partyline-ui   # the standard state set
uv run python -m unittest tests/ui/test_line_menu.py -v   # browser regressions
```

Browser tests live in `tests/ui/` and are excluded from `unittest discover` on purpose: a
missing browser must never break the ordinary suite, and they are not counted toward the
coverage floor.

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
- **Test on a throwaway port and database**, one per person, so several agents can test at once
  without colliding: `PARTYLINE_DB=/tmp/<you>.db PARTYLINE_PORT=864x uv run partyline`.
- **Restarting the cockpit is a scheduled act, not a side effect.** Announce it, let everyone
  commit and post status, then restart and resume. Uncommitted work in an agent's head does not
  survive; committed work always does, and chat history is replayed from SQLite on resume.
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
- **Aim for under 300 lines per `.py` file** (tests excepted — they are allowed to be long and
  boring). This is an encouragement, not a gate: a file crossing it is a prompt to look for the
  seam, not a reason to split something coherent in half.
- **Lint must pass**: `uv run ruff check .`, clean, before every commit. The autoformatter is
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
