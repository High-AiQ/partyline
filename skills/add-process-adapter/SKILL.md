---
name: add-process-adapter
description: Create, package, import, reload, test, or review a Partyline adapter for an interactive process. Use when adding a built-in process adapter, publishing an external adapter repository, or diagnosing adapter discovery and lifecycle behavior.
---

# Add a process adapter

Read `docs/adapters.md` before implementation. Use one package per process:

```
partyline/adapters/bundled/<adapter-id>/
  adapter.toml
  adapter.py
```

Use the same `adapters/<adapter-id>/` layout at the root of external adapter repositories. Keep
the directory id lowercase, stable, and URL-safe.

## Define the manifest

Create `adapter.toml`:

```toml
[adapter]
name = "Example Process"
version = "0.1.0"
description = "Interactive adapter for Example Process."
entrypoint = "adapter.py"
command = ["example-process", "--yolo"]
requires = ["example-process"]
env_unset = []
capabilities = { resume = false, turn_end = "receipt" }
update_command = ["example-process", "update"]
```

Use an argv array for `command`, not a shell string. The adapter package id (directory name)
may differ from the underlying executable binary name (for example, adapter id `cursor` with
executable `agent`). `requires` lists the actual executables that must be on `PATH`. For
unattended attach, bake the CLI's real non-interactive and skip-prompt flags into default
`command` (e.g. `--yolo --trust`); probe the real CLI rather than guessing to ensure it never
hangs on trust, sandbox, or approval prompts. `capabilities` is a table; set `resume = true` only
if re-attaching genuinely reopens the process's previous session, and set `turn_end = "receipt"`
when the adapter reports turn boundaries from transcript events. `update_command` is an optional
argv the host runs before a fresh attach when the operator ticks “update CLI first”; omit it when
the process has no updater. Do not guess an update command for another vendor. `entrypoint` must
name a file inside the package directory, and the class it exports defaults to `PartylineAdapter`
— override with `class = "..."` if you need a different name. Keep secrets and machine-specific
paths out of the manifest. Use `env_unset` only for inherited variables that would interfere with
a child process; an entry ending in `*` clears every variable with that prefix.

## Implement lifecycle behavior

Export a `PartylineAdapter` class from `adapter.py`, subclassing the framework adapter base.
Implement the interactive argv and any transcript or log tailing needed by the process. Preserve
these invariants:

- Start the actual interactive executable in the supplied pty; do not substitute a headless
  mode or an SDK call.
- Send chat input through the inherited bracketed-paste-plus-Enter path.
- Drain terminal output continuously so the child cannot block.
- Prefer structured transcripts or logs for assistant replies. Do not turn a terminal screen
  into chat messages.
- Report turn boundaries as receipts: post `BEGAN` (`UserPromptSubmit`) when user input is
  recorded, and `ENDED` (`Stop`) when turns finish (including aborted turns, so badges clear).
- Receipt adapters are idle-gated by the host: a mention arriving during an open turn is held and
  flushed only on a real `ENDED`. Plain chatter does not trigger a paste. If the vendor provides
  positive evidence that a previously pasted digest was skipped, retain that delivery's integer
  message ids and, when `repool = self.att.get("repool_message_ids")` is present, call
  `await repool(message_ids)`. The host persists the exact batch across a restart and replays it
  ordered and deduplicated; never rewind `last_seen`, rescan mentions, or copy message bodies into
  adapter-owned retry state.
- Start observing output after this attachment starts, and avoid replaying prior records after
  a resume. Notice that `_fresh` is timestamp-based: if transcript records carry no timestamps,
  do not use `_fresh`. Instead, snapshot existing records on open as seen to prevent replaying
  past turns, and survive file rewrites or compactions by re-anchoring on the record sequence.
- **Locate the transcript unambiguously.** If the CLI accepts a session id or a session
  directory, pass one you chose — then the path is exact and nothing else can occupy it. If you
  must fall back to matching on working directory and start time, you also have to *claim* the
  file you resolve and skip files another attachment already claimed, and serialize discovery so
  two attachments cannot resolve at once. Two copies of the same CLI started in one directory
  seconds apart are otherwise indistinguishable, and the second one will tail the first one's
  transcript and repost its messages under the wrong handle. When a session UUID is known, tail
  that exact transcript file only (e.g. `<uuid>/<uuid>.jsonl`) rather than broad globs that could
  mistake sibling or subagent files for main turns.
- Report meaningful lifecycle status and cleanly stop background tasks.

Use the attachment working directory and inherited environment. Do not edit shell profiles or
persist credentials. If a process needs credentials, document its variable name without a value.

## Ship tests with the adapter

An adapter package owns its own tests. Partyline's own suite covers the adapter *contract* — the
pty runtime, the manifest loader, the registry — but it cannot cover your adapter's transcript
format, and it will not install your process to try. For external repositories, put a test file
beside the package. For bundled adapters in Partyline core, tests live in
`tests/test_<adapter_id>_adapter.py`.

Test your logic, never the vendor's product:

- **Do** assert on parsing: feed a fixture transcript file you wrote by hand and check which
  messages come out, that partial and malformed records are survived, and that records predating
  this attachment are not replayed after a resume.
- **Do** assert the claiming rule: construct two attachments in one working directory and check
  the second refuses the first one's transcript.
- **Do** assert that terminal-screen contents never become chat messages.
- **Do not** invoke the real executable, reach the network, or assert that the vendor's CLI
  writes a particular file. Those tests fail on a machine without the tool installed, and break
  on someone else's release schedule.
- **Do not** sleep and hope. If a test needs a background loop to advance, drive the condition
  explicitly — a counted stub for the wait, a flag the loop checks — rather than a real delay
  tuned to the machine you happened to write it on. A flaky adapter test is worse than none.

A useful shape, portable to any harness: build the adapter object directly, hand it fakes for the
two callbacks it takes (one collecting posted messages, one collecting status changes), point it
at a fixture file in a temporary directory, and assert on what the collectors received. That
works because the adapter is constructed with its effects passed in — no server, no pty, no
process required.

## Test locally

Run partyline with a throwaway database and port. Test start, mention delivery, output posting,
exit, terminal peek, and stop. Exercise import and reload:

```bash
curl -X POST http://127.0.0.1:8643/api/adapters/import \
  -H 'content-type: application/json' \
  -d '{"repository":"https://github.com/example/partyline-adapters.git"}'
curl -X POST http://127.0.0.1:8643/api/adapters/reload
curl http://127.0.0.1:8643/api/adapters
```

Validate missing manifest fields, duplicate ids, an invalid entrypoint, and a process that exits
before producing output. Review imported source before executing it.
