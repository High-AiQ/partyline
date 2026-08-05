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

Layout, and where things belong:

- `src/lib/` — **pure functions, no framework.** Markdown rendering, mention
  candidates, jack selection, routing, the REST client. Anything with a rule in
  it belongs here, because this is the layer that gets unit tests.
- `src/state/*.svelte.ts` — runes stores: `session`, `room`, `wire`, `draft`,
  `dialogs`. One owner per concern; components read them and call methods.
- `src/components/` — presentation, grouped by region (`rail/`, `chat/`,
  `board/`, `dialogs/`).

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
uv run playwright install chromium                        # once
uv run python -m scripts.uishot --out /tmp/partyline-ui   # the standard state set
uv run python -m unittest tests/ui/test_line_menu.py -v   # browser regressions
```

**When a change is supposed to be invisible, prove it.** A refactor, a
conversion, a formatter — anything claiming not to touch the UI — should be
bracketed by:

```bash
uv run python -m scripts.uidiff baseline   # before
uv run python -m scripts.uidiff check      # after; non-zero if anything moved
```

It renders the standard state set and compares PNG bytes. Two details are
load-bearing and were both established by measurement rather than assumption:

- **Every command captures twice.** Headless Chromium is *nearly* deterministic
  — about one run in three has a single state off by a hair, and not the same
  state each time. A state is only compared if two consecutive captures agree;
  one that disagrees with itself is named and excluded. This is what separates
  a timing flake (differs sometimes) from a regression (differs every time),
  without a fuzz threshold that would hide the small changes worth catching.
- **Animations are frozen during capture.** A shot taken 20ms into a 120ms fade
  is a different image every run.

A reported difference is not automatically a bug — an intended visual change
shows up here too. It has to be *looked at*, then accepted by re-running
`baseline`.

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
- **A restart does not pick up your work. Advancing the cockpit does.** The cockpit is a
  separate clone: it changes only when it is pulled. Restarting it without pulling relaunches
  the same commit it was already on, successfully and silently, and the old UI comes back
  looking like the change never happened. Run the preflight — it is not optional ceremony, it
  is the only thing standing between you and a restart that costs everyone their turn for
  nothing:

  ```bash
  uv run python -m scripts.cockpit check     # is the workbench fit to deploy?
  uv run python -m scripts.cockpit deploy    # check, fast-forward the cockpit, verify
  ```

  `check` refuses a dirty tree, a missing or **stale** bundle (it rebuilds and diffs, which is
  the one way to catch `frontend/src/` edits that were never built), and unpushed commits —
  the cockpit pulls from the remote, so work that is only committed locally cannot reach it.
  `deploy` then fast-forwards the cockpit and asserts it is at the same sha as the workbench.
  Neither command restarts anything; that stays a deliberate, announced act.
- **Test on a throwaway port and database**, one per person, so several agents can test at once
  without colliding: `PARTYLINE_DB=/tmp/<you>.db PARTYLINE_PORT=864x uv run partyline`.
- **Restarting the cockpit is a scheduled act, not a side effect.** The full ceremony, in
  order: everyone commits and posts status → `scripts.cockpit deploy` passes → announce →
  confirm nobody is mid-turn → restart. Uncommitted work in an agent's head does not survive;
  committed work always does, and chat history is replayed from SQLite on resume.
- **Nobody may be mid-turn when the restart lands — including whoever triggers it.** An agent
  killed mid-turn comes back to a CLI that resumes the interrupted turn and asks it to continue,
  so it posts a stray fragment into the room on wake. If you schedule the restart with a delayed
  detached command, the delay has to outlast *your own* turn, not just your announcement.
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
- **Aim for under 300 lines per source file** — `.py`, `.js`, `.ts` and `.svelte` alike (tests
  excepted; they are allowed to be long and boring). This is an encouragement, not a gate: a file
  crossing it is a prompt to look for the seam, not a reason to split something coherent in half.
  A `.svelte` file counts its markup and styles too — a component that needs 300 lines is usually
  two components and a shared stylesheet.
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
