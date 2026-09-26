# AGENTS.md

partyline attaches real interactive CLIs to chat lines through ptys and tails their
transcripts. Read `README.md` first; the full rulebook with every DO / DO NOT table is
`docs/agent-rules.md`, and it still governs — this page is the index.

**Never break:** every process is a real pty process (no headless/SDK calls); speech comes
from structured transcripts, never screen scrapes; `partyline/static/` is built, not edited.

| DO | DO NOT |
| --- | --- |
| Post media and service links as host-relative paths (`/api/media/<id>/slim`) or the LAN host | Post `0.0.0.0`, `127.0.0.1`, or `localhost` URLs; people reach this over LAN or HTTPS |

**Gates before every commit** (`docs/agent-rules.md`, Gates): `uv run --locked ruff check .`,
`./scripts/capped-test` (never the suite uncapped), coverage ≥90%, `./check-code-lines`
(≤300 lines per production file), `cd frontend && npm run verify && npm run build` and commit
the bundle. Tests get their own database automatically; never point one at a real database.

**Ship:** one-line Conventional Commit, semver bump in `partyline/__init__.py` in the same
commit (feat → minor, fix → patch; none for docs/test/chore), branch + PR, CI green. Schema
changes are new idempotent entries in `partyline/db_schema.py`.

**Read next:** adapters `docs/adapters.md` + `skills/add-process-adapter/`; frontend
`docs/frontend.md`; captains and lines `docs/hierarchy.md`; restarting the copy you are
running inside `docs/restart.md`; lessons from incidents `docs/lessons.md`; reviews
`skills/adversarial-review/`; visual changes `skills/verify-visual-change/`.

**Child-line reviews:** review the child's reported SHA in a Partyline-managed review
worktree. With Git mirrors, refs are private per line (shared by its processes); the
captain sees accepted refs, so newer commits can appear as uncommitted files in the
shared worktree. Do not use that view to judge the child's progress.

**Kill by pid** (`ss -ltnp | grep 864x`), never by matching the word partyline across
command lines — that matches the room you are standing in.
