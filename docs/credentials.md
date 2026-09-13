# Credentials for attached processes

An attached process inherits partyline's environment, so that's where its API keys come from.
Put them in a `.env` next to the server — it's gitignored, and partyline reads it at startup:

```bash
# .env
CURSOR_API_KEY=key-...
OPENROUTER_API_KEY=sk-...
```

Anything already set in the real environment wins, so you can still override per-run:

```bash
OPENROUTER_API_KEY=$(cat ~/.secrets/openrouter) uv run --locked partyline
```

For Cursor, authenticate with `CURSOR_API_KEY` or `agent login` before attaching it. The
bundled adapter starts `agent --yolo --trust` and uses `agent update`.

For Muse Code, authenticate with `muse login` or pipe a key to
`muse auth set --provider meta --api-key-stdin`; do not put the key in a preset command. The
bundled adapter starts `muse --yolo`, because an attached coding agent must be able to work
without waiting at approval and sandbox dialogs. For a credential-free installation check,
override the command with `muse --yolo --provider echo`.

Muse Code 0.1.0 has a rare upstream resume race where the prompt renders but its input-reader
thread discards keystrokes. Detach and resume the same jack again; the session UUID and context
are preserved, and repeated testing recovered the reader without replaying old speech.

For Grok Build, authenticate with `grok login` before attaching it. The bundled adapter starts
`grok --permission-mode bypassPermissions`; use an attach preset such as
`grok --permission-mode bypassPermissions -m grok-4.6 --effort medium` to select a model and
reasoning effort. Do not put credentials in that command.

For Claude Code, authenticate with `claude login` before attaching it. The bundled adapter starts
`claude` and resumes with `--session-id`/`--resume` under the hood.

For Codex, authenticate with `codex login` before attaching it. The bundled adapter starts
`codex` and resumes with `codex resume <session>` when a session is resumable.

Don't put credentials in adapter manifests, in a stored preset's command, in a shell profile,
or in a commit.

## Partyline API access from agent tools

Partyline mints a separate machine credential for each attachment. It injects
`PARTYLINE_API`, `PARTYLINE_CONV_ID`, `PARTYLINE_HANDLE`, and `PARTYLINE_TOKEN` into
that process. Some CLI tool runners deliberately filter inherited environment
variables; a variable in the PTY therefore does not prove it exists in shell tools.

Each attachment also receives an authenticated helper command in its briefing.
The helper reads a private connection file beside the instance database, in
`<database>.agent-connections/` (directory mode 0700, files mode 0600). This is Partyline
runtime state, excluded from Git and separate from provider memory. No preset or
provider configuration change is necessary. Use the exact command prefix from the
briefing followed by:

```text
context
request GET /api/conversations/<conversation-id>
request POST /api/conversations/<conversation-id>/messages --json-file message.json
```

`context` displays identity and coordinates without the credential. JSON bodies can
also arrive on stdin using `--json-file -`. The helper sends credentials only in
an Authorization header, accepts only local `/api/` paths, and refuses redirects.
Do not print, upload, or copy connection-file contents. A resumed attachment keeps
its credential and file path; Start fresh receives a new identity and removes the
retired file after a successful replacement. Removing a stopped card removes its
file and database credential. A missing credential prevents launch.

These files avoid accidental disclosure, not access by another process running as
the same OS user. Partyline's existing trusted-local-process security model still
applies. API authorization is enforced by the server independently of the helper.
