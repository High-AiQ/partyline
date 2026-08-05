# partyline

*Several parties. One wire. Pick up.*

A chatroom where **humans and interactive terminal processes talk to each other**. Attach real
executables — a coding-agent CLI, a REPL, a custom script — to a conversation, give each one an
@handle, and route work between them:

> **greg:** @reviewer I finished the migration, pls review
> **reviewer:** On it. @tester can you run the test suite while I read the diff?

Processes only wake when @mentioned. No polling loops, no cron jobs.

## Why a real terminal?

Because the interactive app is the real thing. Headless and one-shot modes are a different
program with different behaviour, different context discovery, and different auth. partyline
spawns the **actual interactive executable in a pty** — same startup, same project files, same
login as typing in your terminal. The trick that keeps it clean: **the screen is never scraped.**

| direction | mechanism |
|---|---|
| chat → process | keystrokes written to the pty (bracketed paste + Enter) — the app sees a typed/queued message |
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
git clone git@github.com:High-AiQ/partyline.git
cd partyline
uv sync                   # creates .venv and installs everything
uv run partyline          # serves http://127.0.0.1:8642
```

`uv run partyline` does the sync for you, so the middle step is optional — it is spelled out
only so a first run does not look like it has hung while uv builds the environment.

Open <http://127.0.0.1:8642>. If the page loads but is blank, the built client is missing from
`partyline/static/` — see [The frontend](#the-frontend).

Then, in the browser:

1. **Pick a handle** — this is your name on the wire (stored locally).
2. **Open a line** — type a conversation name in the left rail, hit `+`.
3. **Patch in a process** — on the right, give it a handle (e.g. `reviewer`), pick an adapter,
   optionally add a command, set the working directory you want it to work in (it picks up that
   project's `AGENTS.md` and trust settings), and hit **attach**.
4. **Talk.** Plain messages go to everyone; `@reviewer do X` wakes reviewer with every message
   it hasn't seen yet. Processes are briefed on join, so they @mention you and each other back.

> **Strongly recommended:** if the CLI you are attaching has a permission or approval mode, set
> it in the command. A headless TUI cannot ask you questions — without it, processes pause on
> approval dialogs until you answer via **peek** (below).

Before first attaching a process in a new working directory, run its CLI there manually once to
clear first-run trust/onboarding prompts.

## Adapters

Out of the box:

- **pi** — pins `--session-id`/`--session-dir` and tails the JSONL session transcript.
- **opencode** — tails opencode's own session store.
- **hermes** — tails hermes's own session store.
- **raw** — any process: shells, custom scripts, CLIs without a first-class adapter yet.
  Output is the ANSI-stripped pty stream, flushed after ~1.2s of quiet; input is the message
  body verbatim. Also the starting point for writing a new adapter (~40 lines).

An adapter is a small package that tells partyline how to start one process and how to turn its
output into chat. Bundled ones live in `partyline/adapters/bundled/<id>/`; the layout is
identical wherever they come from:

```
<id>/
  adapter.toml   # identity, entrypoint, default command, requires, capabilities
  adapter.py     # defines class PartylineAdapter(Adapter)
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

## Development

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and `git`. Everything else is
installed by `uv sync`, including the dev group (test runner, linter, browser driver).

```bash
uv sync                                  # runtime + dev dependencies
uv run playwright install chromium       # once, for the UI tests and screenshots
```

**Node is needed only to change the frontend**, not to run partyline. The built client is
committed under `partyline/static/`, so a fresh clone and an installed wheel both serve the UI
with Python alone.

### The frontend

The client is [Svelte 5](https://svelte.dev) + [Tailwind](https://tailwindcss.com), built by
Vite into `partyline/static/`:

```bash
cd frontend
npm install
npm run dev      # hot reload, proxying /api and /ws to a partyline on $PARTYLINE_PORT
npm run verify   # format + lint + svelte-check + tests; the gate CI runs
npm run build    # → partyline/static/ — rebuild before committing a UI change
npm run format   # apply Prettier
```

`src/lib/` holds framework-free functions — markdown rendering, mention candidates, jack
selection, routing — and is where the unit tests live. `src/state/` holds the runes stores
(`session`, `room`, `wire`), and `src/components/` is presentation only.

### Running the tests

```bash
uv run coverage run -m unittest discover -s tests   # the suite
uv run coverage report                              # fails under 90% line+branch coverage
uv run ruff check .                                 # lint; must be clean before every commit
```

The suite never touches a real database, port, or CLI: it uses temp databases, FastAPI's
`TestClient`, and fixture transcript files. Adapter tests never invoke the vendor tool they
adapt.

### UI tests and screenshots

Browser tests live under `tests/ui/` and are deliberately **not** picked up by `discover`, so a
missing browser can't break the normal suite. Run them explicitly:

```bash
uv run python -m unittest tests/ui/test_line_menu.py -v
```

`scripts/uishot.py` drives the real UI in headless Chromium. It starts a throwaway server on an
OS-assigned port with a temp database, signs in through the handle gate, and hands back a
Playwright page — so a frontend change can be looked at instead of guessed at:

```bash
uv run python -m scripts.uishot --out /tmp/partyline-ui   # capture the standard state set
```

```python
from scripts.uishot import ui_session

with ui_session(["alpha line", "beta line"]) as ui:
    ui.open_row_menu(0)          # hovers the row first; the ⋯ is pointer-events:none until then
    ui.shot("menu-open")
```

## Routing model

- Every message is stored (SQLite) and broadcast to all humans on the line.
- Processes wake **only on an explicit `@handle` mention**; a wake delivers all messages the
  process hasn't seen yet as `[sender]: text` lines.
- `@all` rings **every running process** on the line at once. It's a deliberate megaphone, not
  the default: each ring spends one turn per process. `all` and `system` are reserved handles.
- System notices (joins, exits, topic changes) never wake processes, but they ride along in the
  next wake's digest.

## Configuration

| env var | default | |
|---|---|---|
| `PARTYLINE_PORT` | `8642` | |
| `PARTYLINE_HOST` | `127.0.0.1` | see security note before changing |
| `PARTYLINE_DB` | `~/.partyline.db` | conversations, messages, attachments, presets |
| `PARTYLINE_ADAPTERS_DIR` | `~/.partyline/adapters` | where imported adapter repos are checked out |

Everything in the UI is also plain HTTP (`/api/conversations`, `/api/adapters`, `/api/presets`,
`/api/attachments/<id>/{resume,screen,keys}`, WebSocket at `/ws/<conv-id>`), so partyline is
scriptable from anything that can curl.

**Stopping partyline.** `POST /api/shutdown` stops the server gracefully — attached processes are
stopped through the normal lifespan teardown, so nothing is orphaned — and `GET /api/running`
lists what would be stopped. Both are also in the UI, as **stop** next to the operator name in
the sidebar footer. Shutdown is refused unless the request comes from this machine, since the
bind address is configurable and localhost-only is not something to assume.

### Credentials for attached processes

An attached process inherits partyline's environment, so that's where its API keys come from.
Put them in a `.env` next to the server — it's gitignored, and partyline reads it at startup:

```bash
# .env
OPENROUTER_API_KEY=sk-...
```

Anything already set in the real environment wins, so you can still override per-run:

```bash
OPENROUTER_API_KEY=$(cat ~/.secrets/openrouter) uv run partyline
```

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
PARTYLINE_DB=/tmp/partyline-test.db PARTYLINE_PORT=8643 uv run partyline
```

Released under the [MIT License](LICENSE).
