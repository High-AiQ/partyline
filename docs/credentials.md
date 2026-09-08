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
