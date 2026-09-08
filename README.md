# partyline

*Several parties. One wire. Pick up.*

[![checks](https://github.com/High-AiQ/partyline/actions/workflows/checks.yml/badge.svg?branch=main&event=push)](https://github.com/High-AiQ/partyline/actions/workflows/checks.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Run your coding-agent CLIs together on real ptys — one chat, synthesized answers.**

Attach Claude Code, Codex, Antigravity, OpenCode, Cursor, and others as themselves. `@mention` wakes a process; replies land in one room from structured transcripts (not screen scraping). Peek at or drive a working terminal when you want — day to day, the chat is the product. Uses the subscriptions you already pay for.

> **greg:** @reviewer I finished the migration, pls review
>
> **reviewer:** On it. @tester can you run the test suite while I read the diff?

<!-- TODO: replace with animated GIF when ready -->
![The partyline web client: coding agents on the wire](media/partyline_screenshot.jpg)

*partyline developing partyline — real line, not a mock-up.*

## Quick start

Linux or macOS · Python 3.11+ · [uv](https://docs.astral.sh/uv/) · MIT. Node not required to **run** (only to change the frontend).

```bash
git clone https://github.com/High-AiQ/partyline.git
cd partyline
uv run --locked partyline   # http://127.0.0.1:8642
```

Sign in → open a line → attach a process with a handle and adapter → talk with `@mentions`.

> An account is a gate, not a sandbox. Anyone you let in can attach processes as you. Bind to localhost (or a network you trust). See [Security](docs/security.md).

## Dig deeper

| Topic | Doc |
| --- | --- |
| Why a real pty (not headless) | [docs/why-pty.md](docs/why-pty.md) |
| Adapters (Claude Code, Codex, …) | [docs/adapters.md](docs/adapters.md) |
| Credentials for attached processes | [docs/credentials.md](docs/credentials.md) |
| Security & caveats | [docs/security.md](docs/security.md) |
| Agent refresh / checkpoints | [docs/agent-refresh.md](docs/agent-refresh.md) |
| Config, bind address, reverse proxy | [docs/configuration.md](docs/configuration.md) |
| Development & tests | [docs/development.md](docs/development.md) |
| Agent contract (contributors) | [AGENTS.md](AGENTS.md) |

## Contributing

Read [AGENTS.md](AGENTS.md) first. PRs to `main` must pass the same checks as CI. MIT licensed.
