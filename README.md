# partyline

*Several parties. One wire. Pick up.*

partyline is a local chatroom where people and interactive processes work together. Attach a
real terminal program to a conversation, give it an `@handle`, and route messages between
participants:

> **greg:** @reviewer I finished the migration; please review it.
> **reviewer:** On it. @tester can you run the test suite while I read the diff?

Processes wake only when mentioned. They run in a real terminal, using the same interactive
experience they have when launched by hand.

## Why a terminal-backed process?

partyline starts the actual interactive executable in a pseudo-terminal (pty). Chat messages
are delivered as bracketed-paste keystrokes followed by Enter. Replies come from the process's
own transcript when an adapter supports one; partyline never turns a terminal screen into chat
output. This preserves a clean conversation while still allowing a person to inspect and answer
an interactive screen when needed.

## Getting started

Requirements: Linux or macOS, Python 3.10+, [uv](https://docs.astral.sh/uv/), and any process
you plan to attach installed and ready for interactive use.

```bash
git clone git@github.com:High-AiQ/partyline.git
cd partyline
uv run partyline
```

Open <http://127.0.0.1:8642>, choose a handle, create a conversation, then attach a process.
The first release includes adapters for **pi**, **opencode**, and **hermes**. Choose a handle,
adapter, command, and working directory; then start talking.

Before attaching a process in a working directory for the first time, start it there manually
once to complete any initial setup it requires.

## Conversation model

- Every message is stored locally and broadcast to the people on the conversation.
- A process receives accumulated unread messages only after an explicit `@handle` mention.
- `@all` rings every running process. Use it sparingly: it starts a turn for each process.
- System notices do not ring processes, but arrive with the next message digest.
- The terminal screen can be viewed from the attachment controls, with a small keypad for
  common interactive responses.

## Adapters

An adapter is a small Python package that tells partyline how to start and communicate with one
interactive process. Built-in adapters live in `partyline/adapters/bundled/<id>/`. An external adapter
repository has this layout:

```
adapters/
  example-process/
    adapter.toml
    adapter.py
```

The manifest supplies the adapter identity, display metadata, entrypoint, and default command.
`adapter.py` exports a `PartylineAdapter` subclass. See [the adapter reference](docs/adapters.md)
and [adapter-authoring skill](skills/add-process-adapter/SKILL.md) for the contract, lifecycle
rules, and test checklist.

### Import an adapter repository

Import a public repository through the local API:

```bash
curl -X POST http://127.0.0.1:8642/api/adapters/import \
  -H 'content-type: application/json' \
  -d '{"repository":"https://github.com/example/partyline-adapters.git","ref":"main"}'
```

The `ref` field is optional. partyline clones the repository into its local adapter store and
discovers `adapters/*/adapter.toml`. Inspect the enabled adapters with:

```bash
curl http://127.0.0.1:8642/api/adapters
```

After changing an installed adapter, reload its definitions without restarting the server:

```bash
curl -X POST http://127.0.0.1:8642/api/adapters/reload
```

Only import code you trust. Imported adapters run as your user and can start local processes.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `PARTYLINE_PORT` | `8642` | HTTP port |
| `PARTYLINE_HOST` | `127.0.0.1` | Bind address |
| `PARTYLINE_DB` | `~/.partyline.db` | Local conversation data |
| `PARTYLINE_ADAPTERS_DIR` | platform-local adapter store | Imported adapter location |

Keep credentials in a local `.env` file when needed by an attached process. `.env` is ignored
by git. Do not add credentials to commands, shell profiles, commits, or adapter manifests.

## Security

partyline has no authentication and binds to localhost by default. Anyone who can reach its
port can interact with processes running as you. Do not expose it directly to a network.

Processes inherit your user account and run in the working directory you select. Treat a shared
conversation as shared terminal access. Review external adapter source before importing it.

## Development

Read [AGENTS.md](AGENTS.md) before contributing. Run throwaway instances while testing:

```bash
PARTYLINE_DB=/tmp/partyline-test.db PARTYLINE_PORT=8643 uv run partyline
```

The project is released under the [MIT License](LICENSE).
