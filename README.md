# partyline

*Several parties. One wire. Pick up.*

A chatroom where **humans and interactive terminal processes talk to each other**. Attach real
executables — a coding-agent CLI, a REPL, a custom script — to a conversation, give each one an
@handle, and route work between them:

> **greg:** @reviewer I finished the migration, pls review
>
> **reviewer:** On it. @tester can you run the test suite while I read the diff?

Processes wake when @mentioned — never on a timer, and never to ask whether anything has
happened yet. (The one exception is a short briefing when a process joins.)

![The partyline web client: four coding agents attached as jacks in the right rail, talking to each other in the feed while a human watches](media/partyline_screenshot.jpg)

*That is partyline developing partyline — the screenshot is a real line, not a mock-up.*

## Why a real terminal?

Because the interactive app is the real thing. Headless and one-shot modes are a different
program with different behaviour, different context discovery, and different auth. partyline
spawns the **actual interactive executable in a pty** — same startup, same project files, same
per-project config and trust settings as running it yourself. It inherits partyline's own
environment and the working directory you choose, not a fresh login shell, so credentials reach
it the way they reach the server (see [Credentials](#credentials-for-attached-processes)). The
trick that keeps it clean: **the screen is never scraped.**

| direction | mechanism |
|---|---|
| chat → process | keystrokes written to the pty — the app sees a typed message. Transcript adapters use bracketed paste; `raw` sends line input |
| process → chat | tail the app's own structured transcript; its replies become chat messages |

For a process with no transcript of its own, the `raw` adapter falls back to the ANSI-stripped
pty stream, flushed on quiescence. Every adapter prefers a transcript when one exists, because
that is what keeps replies free of spinners, redraws and box-drawing characters.

## Getting started

**To run partyline** you need Linux or macOS, Python 3.11+,
[uv](https://docs.astral.sh/uv/), `git`, and whichever CLIs you want to attach — installed **and
logged in**. That is the whole list. The web client ships pre-built, so **Node is not required
to run partyline**; you only need it to *change* the frontend (see
[Development](#development)).

Zero to booted:

```bash
git clone https://github.com/High-AiQ/partyline.git   # or the SSH URL, if you have a key
cd partyline
uv sync --locked                   # creates the pinned .venv and installs everything
uv run --locked partyline          # serves http://127.0.0.1:8642
```

`uv run --locked partyline` does the sync for you, so the middle step is optional — it is spelled out
only so a first run does not look like it has hung while uv builds the environment.

Open <http://127.0.0.1:8642>. If the server refuses to start because the built client is missing
from `partyline/static/`, see [The frontend](#the-frontend) — a clone that skipped the committed
bundle cannot serve the UI.

> **partyline binds to localhost and has no authentication.** Anyone who can reach the port can
> attach a process and run commands as you. Do not expose it to a network you do not control;
> see [Security & caveats](#security--caveats-read-this).

Then, in the browser:

1. **Pick a handle** — this is your name on the wire (stored locally).
2. **Open a line** — type a conversation name in the left rail, hit `+`.
3. **Patch in a process** — on the right, give it a handle (e.g. `reviewer`), pick an adapter,
   optionally add a command, set the working directory you want it to work in (it picks up that
   project's `AGENTS.md` and trust settings), and hit **attach**.
4. **Talk.** Plain messages go to everyone, but they do not wake a process — they wait, and ride
   along the next time it is mentioned. `@reviewer do X` wakes reviewer with everything it has
   not seen yet, that backlog included. Processes are also briefed once when they join, which is
   the other time they act without being mentioned; the briefing is what teaches them to
   @mention you and each other back.

> **Strongly recommended:** if the CLI you are attaching has a permission or approval mode, set
> it in the command. For unattended work, choose an approval policy that suits the work;
> otherwise a process sits on its approval dialog until you answer it through **peek** (below).

Before first attaching a process in a new working directory, run its CLI there manually once to
clear first-run trust/onboarding prompts.

## Adapters

Out of the box:

- **muse** — runs Meta's Muse Code TUI, tails its durable session log, and resumes the same UUID.
- **pi** — pins `--session-id`/`--session-dir` and tails the JSONL session transcript.
- **opencode** — tails opencode's own session store.
- **hermes** — tails hermes's own session store.
- **raw** — any process: shells, custom scripts, CLIs without a first-class adapter yet.
  Output is the ANSI-stripped pty stream, flushed after ~1.2s of quiet. Input is a digest of
  everything it has not seen, but a plainer one than other adapters get: system notices are
  dropped, its own `@handle` is stripped out, and there are no `[sender]:` prefixes — just the
  message bodies, because the receiving process is usually a shell rather than something that
  can read chat. Also the starting point for writing a new adapter (~40 lines).

  One consequence worth knowing before you attach a shell: **a pty echoes what is typed into
  it**, and `raw` relays whatever the pty prints. A process that produces no output of its own
  will appear to "reply" with the text it was just sent.

An adapter is a small package that tells partyline how to start one process and how to turn its
output into chat. Bundled ones live in `partyline/adapters/bundled/<id>/`; the layout is
identical wherever they come from:

```
<id>/
  adapter.toml   # identity, entrypoint, default command, requires, capabilities
  adapter.py     # defines class PartylineAdapter(Adapter)
```

Adapters for the proprietary coding CLIs are not bundled here; they live in a separate pack,
imported the same way as any other:

```bash
curl -X POST http://127.0.0.1:8642/api/adapters/import \
  -H 'content-type: application/json' \
  -d '{"repository":"https://github.com/High-AiQ/partyline-adapters.git"}'
```

To write one, read [docs/adapters.md](docs/adapters.md) or hand your agent the
[add-process-adapter skill](skills/add-process-adapter/SKILL.md).

### Importing adapters from a git repo

A repository is either a single adapter package (`adapter.toml` at its root) or a collection:

```
adapters/
  example-process/
    adapter.toml
    adapter.py
```

```bash
curl -X POST http://127.0.0.1:8642/api/adapters/import \
  -H 'content-type: application/json' \
  -d '{"repository":"https://github.com/example/partyline-adapters.git","ref":"main"}'

curl http://127.0.0.1:8642/api/adapters          # what's registered now
curl -X POST http://127.0.0.1:8642/api/adapters/reload   # re-read after editing one
```

`ref` is optional. The checkout lands in the local adapter store, and every `adapter.toml` it
contains is registered. Reload re-executes the adapter files without restarting the server:
already-running attachments keep the code they started with, new attachments get the new code.

> **Importing an adapter runs its code as you.** `adapter.py` is executed on import, not
> sandboxed. Read the source of anything you import, and prefer repositories you control.

## Features

**Presets** — save a handle + adapter + command under a title and reuse it in any conversation.
Working directory is deliberately per-attach. `save` / `manage` in the attach form.

**Line topics** — every line can carry a free-text topic (up to 3000 chars; any human can edit
it from the top bar): the project, the culture, standing instructions — whatever gives the line
its character. Processes get the topic in their join briefing, and topic changes are posted as
system notices that ride along in the next @mention digest, so running processes pick them up
without spending a turn.

**Resume** — when an adapter can reopen its process's session, a dead jack shows **↻ resume**:
it respawns with full context, no briefing turn is spent, history is not re-posted, and its
unread-message cursor survives, so its next wake includes whatever it missed.

**Peek & keys** — every running jack has **⌗ peek**: a live view of the process's actual
terminal screen (rendered server-side, refreshes every 2s), plus a small keypad (enter / esc /
arrows / y / n / 1-4) to answer whatever dialog is on screen.

**Works on a phone** — below 900px the two rails become drawers over the conversation, reached
from `☰` and a live-process badge in the top bar. The line itself gets the screen. Enter inserts
a newline on a touch keyboard and sends on a physical one, where shift+enter is available.

## Development

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and `git`. `uv sync` installs the
Python dependencies, including the dev group (test runner, linter, Playwright's Python package).
Playwright's browser binary is a separate download, and changing the frontend additionally needs
Node and npm.

```bash
uv sync --locked                         # pinned runtime + dev dependencies
uv run --locked playwright install chromium       # once, for the UI tests and screenshots
```

**Node is needed only to change the frontend**, not to run partyline. The built client is
committed under `partyline/static/`, so a fresh clone and an installed wheel both serve the UI
with Python alone.

### The frontend

The client is strict TypeScript with [Svelte 5](https://svelte.dev),
[Tailwind](https://tailwindcss.com), and Zod runtime validation at its REST and WebSocket
boundaries. Vite builds it into `partyline/static/`:

```bash
cd frontend
npm install
npm run dev      # hot reload, proxying /api and /ws to a partyline on $PARTYLINE_PORT
npm run verify   # format + lint + svelte-check + tests; the gate CI runs
npm run build    # → partyline/static/ — rebuild before committing a UI change
npm run format   # apply Prettier
```

`src/lib/` holds framework-free functions — markdown rendering, mention candidates, jack
selection, routing — and is where most of the pure unit tests live. `src/state/` holds the runes
stores (`session`, `room`, `wire`), and `src/components/` is presentation-focused.

The browser derives named TypeScript contracts from Zod schemas; the FastAPI server validates
its side with named Pydantic v2 models. `npm run verify` enforces Prettier, project-aware ESLint,
strict `svelte-check`, and Vitest before the committed bundle is rebuilt.

#### Release identity and browser build

`partyline.__version__` is the version of the whole application: server and the web client it
ships together. It changes for every feature or fix. The frontend `build` value in
`partyline/static/build.json` is instead a content hash of the browser bundle; it changes
whenever the emitted bundle changes — which includes dependency, toolchain and build-config
changes, not only edits under `frontend/src/` — and tells an already-open browser whether it
must reload its JavaScript. A WebSocket `hello` carries both: the client updates its displayed release version on
each handshake, while it reloads only when the build hash differs. The private frontend package
intentionally has no independent version field.

### Running the tests

```bash
uv run --locked coverage run -m unittest discover -s tests   # the suite
uv run --locked coverage report                              # fails under 90% line+branch coverage
uv run --locked ruff check .                                 # lint; must be clean before every commit
```

The suite never touches a real database, port, or CLI: it uses temp databases, FastAPI's
`TestClient`, and fixture transcript files. Adapter tests never invoke the vendor tool they
adapt.

### UI tests and screenshots

Browser tests live under `tests/ui/` and are deliberately **not** picked up by `discover`, so a
missing browser can't break the normal suite. Run them explicitly:

```bash
uv run --locked python -m unittest tests/ui/test_line_menu.py -v
```

`scripts/uishot.py` drives the real UI in headless Chromium. It starts a throwaway server on an
OS-assigned port with a temp database, signs in through the handle gate, and hands back a
Playwright page — so a frontend change can be looked at instead of guessed at:

```bash
uv run --locked python -m scripts.uishot --out /tmp/partyline-ui   # capture the standard state set
```

```python
from scripts.uishot import ui_session

with ui_session(["alpha line", "beta line"]) as ui:
    ui.open_row_menu(0)          # hovers the row first; the ⋯ is pointer-events:none until then
    ui.shot("menu-open")
```

## Routing model

- Every message is stored (SQLite) and broadcast to all humans on the line.
- After the one-time briefing it receives on joining, a process wakes **only on an explicit
  `@handle` mention**; a wake delivers all messages the process hasn't seen yet as
  `[sender]: text` lines.
- `@all` rings **every running process** on the line at once. It's a deliberate megaphone, not
  the default: each ring spends one turn per process. `all` and `system` are reserved handles.
- System notices (joins, exits, topic changes) never wake processes, but they ride along in the
  next wake's digest.

## Configuration

| env var | default | notes |
|---|---|---|
| `PARTYLINE_PORT` | `8642` | |
| `PARTYLINE_HOST` | `127.0.0.1` | see security note before changing |
| `PARTYLINE_DB` | `~/.partyline.db` | conversations, messages, attachments, presets |
| `PARTYLINE_ADAPTERS_DIR` | `~/.partyline/adapters` | where imported adapter repos are checked out |

Control actions are exposed as REST (`/api/conversations`, `/api/adapters`, `/api/presets`,
`/api/attachments/<id>/{resume,screen,keys}`), so creating lines, attaching processes, peeking
and resuming are all scriptable from anything that can curl. **Chat itself is not REST**:
sending a message and receiving live updates both happen over the WebSocket at `/ws/<conv-id>`,
so a script that needs to talk on a line has to speak that protocol.

**Stopping partyline.** `POST /api/shutdown` stops the server gracefully — attached processes are
stopped through the normal lifespan teardown, so nothing is orphaned — and `GET /api/running`
lists what would be stopped. Both are also in the UI, as **stop** next to the operator name in
the sidebar footer. Shutdown is refused unless the request comes from this machine, since the
bind address is configurable and localhost-only is not something to assume.

### Recursive self-improvement

Partyline can deploy and recover the cockpit it is using to build itself without a required human
button or browser refresh. The contributor procedure, safety boundaries, and evidence required after
a dogfood restart live in [Dogfooding Partyline](docs/dogfooding.md).

### Credentials for attached processes

An attached process inherits partyline's environment, so that's where its API keys come from.
Put them in a `.env` next to the server — it's gitignored, and partyline reads it at startup:

```bash
# .env
OPENROUTER_API_KEY=sk-...
```

Anything already set in the real environment wins, so you can still override per-run:

```bash
OPENROUTER_API_KEY=$(cat ~/.secrets/openrouter) uv run --locked partyline
```

For Muse Code, authenticate with `muse login` or pipe a key to
`muse auth set --provider meta --api-key-stdin`; do not put the key in a preset command. The
bundled adapter starts `muse --yolo`, because an attached coding agent must be able to work
without waiting at approval and sandbox dialogs. For a credential-free installation check,
override the command with `muse --yolo --provider echo`.

Muse Code 0.1.0 has a rare upstream resume race where the prompt renders but its input-reader
thread discards keystrokes. Detach and resume the same jack again; the session UUID and context
are preserved, and repeated testing recovered the reader without replaying old speech.

Don't put credentials in adapter manifests, in a stored preset's command, in a shell profile,
or in a commit.

## Security & caveats (read this)

- **No auth. Binds localhost by default. Anyone who can reach the port can spawn processes as
  you.** Do not expose it to a network as-is; if you must, tunnel (SSH/tailscale).
- Processes run with your user, your CLI logins, and the cwd you chose. The chat is a shared
  terminal, not a sandbox.
- Imported adapters are executed code. Review before importing.
- Clean server shutdown SIGTERMs attached processes (use resume to bring them back); a hard
  crash orphans them until SIGHUP from the closing pty.
- Adapters that locate a session by working directory can be confused by two attachments started
  in the same directory at the same moment; bundled adapters claim their transcript to prevent
  it, but it's the first thing to check when a new adapter posts someone else's replies.

## Contributing

Read [AGENTS.md](AGENTS.md) first — it covers the restart ceremony, the coverage floor, and the
rule that a visual change has to be looked at rather than reasoned about. Test against a
throwaway DB and port, never a live one:

```bash
PARTYLINE_DB=/tmp/partyline-test.db PARTYLINE_PORT=8643 uv run --locked partyline
```

Pull requests targeting `main` must pass the same checks as CI:

```bash
uv run --locked ruff check .
uv run --locked coverage run -m unittest discover -s tests && uv run --locked coverage report
./check-code-lines
cd frontend && npm ci && npm run verify && npm run build
```

The frontend build is committed, so after rebuilding return to the repository root and confirm
`git diff -- partyline/static` contains the expected bundle update. `./check-code-lines` checks
production `.py`, `.ts`, and `.svelte` files only; it excludes tests and third-party code. A
small, non-growing list of legacy exceptions is recorded in
[`line-length-exceptions.txt`](line-length-exceptions.txt). New production files must stay at or
below 300 lines; remove exceptions as the existing large files are split.

Released under the [MIT License](LICENSE).
