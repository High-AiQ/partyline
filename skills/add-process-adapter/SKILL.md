---
name: add-process-adapter
description: Create, package, import, reload, test, or review a Partyline adapter for an interactive process. Use when adding a built-in process adapter, publishing an external adapter repository, or diagnosing adapter discovery and lifecycle behavior.
---

# Add a process adapter

Read `docs/adapters.md` before implementation. Use one package per process, and the same
`adapters/<adapter-id>/` layout at the root of external adapter repositories:

```
partyline/adapters/bundled/<adapter-id>/
  adapter.toml
  adapter.py
```

| DO | DO NOT |
| --- | --- |
| Keep the directory id lowercase, stable, and URL-safe | — |

## Define the manifest

Create `adapter.toml`. The package id (directory name) may differ from the executable name
(adapter id `cursor` runs executable `agent`); `requires` lists the executables that must be
on `PATH`.

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
compact_paste = "/compact"
```

| DO | DO NOT |
| --- | --- |
| Use an argv array for `command` | Use a shell string |
| Bake the CLI's real non-interactive and skip-prompt flags into the default `command` (e.g. `--yolo --trust`), probing the real CLI so unattended attach never hangs on trust, sandbox, or approval prompts | Guess the flags |
| Set `resume = true` only if re-attaching genuinely reopens the previous session | — |
| Set `turn_end = "receipt"` when the adapter reports turn boundaries from transcript events | — |
| Provide `update_command` as an argv the host runs before a fresh attach when the operator ticks "update CLI first" | Guess an update command for another vendor; omit it when the process has no updater |
| Live-probe `compact_paste` in the real TUI, record the probed CLI version beside the field, and re-probe after `update_command` — unknown slash commands can fuzzy-match a different action (OpenCode 1.18.21 turned `/compact` into `/review`) instead of failing closed | Ship an unprobed compact command; omit the field when the TUI exposes no verified one |
| Include an embedded newline in `compact_paste` only when a live probe proves the slash menu needs it to select the item | — |
| Point `entrypoint` at a file inside the package; the exported class defaults to `PartylineAdapter` (override with `class = "..."`) | — |
| Use `env_unset` only for inherited variables that would interfere with a child process (a trailing `*` clears every variable with that prefix) | Put secrets or machine-specific paths in the manifest |

## Implement lifecycle behavior

Export the adapter class from `adapter.py`, subclassing the framework adapter base, and use
the attachment working directory and inherited environment.

| DO | DO NOT |
| --- | --- |
| Start the actual interactive executable in the supplied pty | Substitute a headless mode or an SDK call |
| Send chat input through the inherited bracketed-paste-plus-Enter path | — |
| Drain terminal output continuously so the child cannot block | — |
| Post assistant replies from structured transcripts or logs | Turn a terminal screen into chat messages |
| Report turn boundaries as receipts: `BEGAN` (`UserPromptSubmit`) when user input is recorded, `ENDED` (`Stop`) when turns finish — including aborted turns, so badges clear | — |
| On positive vendor evidence that a pasted digest was skipped, retain that delivery's integer message ids and call `await repool(message_ids)` when `repool = self.att.get("repool_message_ids")` is present — the host persists the exact batch across restarts and replays it ordered and deduplicated | Rewind `last_seen`, rescan mentions, or copy message bodies into adapter-owned retry state |
| Let a manifest `compact_paste` ride the host's idle gate (idle pastes immediately; mid-turn occupies one latest-wins slot fired on a real `ENDED`) | Intercept a chat mention or add a second queue for compaction |
| Identify the vendor's structured compaction record or transcript rewrite, filter summaries from assistant speech, and follow session-id rotation | Replay the replacement snapshot |
| Start observing output after this attachment starts; snapshot existing records on open as seen when records carry no timestamps, and survive rewrites or compactions by re-anchoring on the record sequence | Use timestamp-based `_fresh` on records that carry no timestamps; replay prior records after a resume |
| Pass a session id or directory you chose when the CLI accepts one — the path is then exact and nothing else can occupy it | — |
| When falling back to cwd/start-time matching: *claim* the resolved file, skip files another attachment claimed, and serialize discovery — two copies of one CLI started in one directory seconds apart are otherwise indistinguishable, and the second tails the first's transcript and reposts its messages under the wrong handle | Let two attachments resolve at once |
| Tail the exact transcript file when a session UUID is known (e.g. `<uuid>/<uuid>.jsonl`) | Use broad globs that could mistake sibling or subagent files for main turns |
| Report meaningful lifecycle status and cleanly stop background tasks | Edit shell profiles or persist credentials |
| Document a needed credential's variable name | Document its value |

## Ship tests with the adapter

An adapter package owns its own tests: Partyline's suite covers the adapter *contract* (pty
runtime, manifest loader, registry), not your transcript format, and it will not install your
process to try. External repositories put a test file beside the package; bundled adapters
use `tests/test_<adapter_id>_adapter.py`.

| DO | DO NOT |
| --- | --- |
| Build the adapter object directly, hand it fakes for its two callbacks (one collecting posted messages, one collecting status changes), point it at a fixture file in a temporary directory, and assert on what the collectors received — no server, pty, or process required | — |
| Assert on parsing: feed a hand-written fixture transcript and check which messages come out, that partial and malformed records are survived, and that records predating the attachment are not replayed after a resume | — |
| Assert the claiming rule: two attachments in one working directory, the second refuses the first's transcript | — |
| Assert that terminal-screen contents never become chat messages | — |
| Add a fixture for the vendor's compaction shape and prove its summary never posts as agent speech; test transcript rewrites and session rotation | — |
| Drive async conditions explicitly — a counted stub for the wait, a flag the loop checks | Sleep and hope; a flaky adapter test is worse than none |
| — | Invoke the real executable, reach the network, or assert the vendor's CLI writes a particular file — those fail on machines without the tool and break on someone else's release schedule |

## Test locally

Run partyline with a throwaway database and port. Test start, mention delivery, output
posting, exit, terminal peek, and stop.

```bash
curl -X POST http://127.0.0.1:8643/api/adapters/import \
  -H 'content-type: application/json' \
  -d '{"repository":"https://github.com/example/partyline-adapters.git"}'
curl -X POST http://127.0.0.1:8643/api/adapters/reload
curl http://127.0.0.1:8643/api/adapters
```

| DO | DO NOT |
| --- | --- |
| Validate missing manifest fields, duplicate ids, an invalid entrypoint, and a process that exits before producing output | — |
| Review imported source before executing it | — |
