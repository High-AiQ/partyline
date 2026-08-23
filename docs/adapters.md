# Adapter packages

An adapter connects partyline to one interactive process: it says how to start the program, and
how to turn what the program says into chat messages. Adapters ship with partyline or live in a
git repository you import.

The layout is the same wherever a package comes from:

```
<adapter-id>/
  adapter.toml   # manifest
  adapter.py     # entrypoint, defines PartylineAdapter
```

Bundled packages live in `partyline/adapters/bundled/<adapter-id>/`. An importable repository is
either a single package (`adapter.toml` at the repository root) or a collection:

```
adapters/
  example-process/
    adapter.toml
    adapter.py
```

The directory name is the stable adapter id. Use lowercase letters, digits, hyphens.

## Manifest

```toml
[adapter]
name = "Example Process"
version = "0.1.0"
description = "Interactive adapter for Example Process."
entrypoint = "adapter.py"
command = ["example-process"]
requires = ["example-process"]
env_unset = []
capabilities = { resume = false }
update_command = ["example-process", "update"]
```

| key | meaning |
|---|---|
| `name`, `version`, `description` | shown in the UI and in `GET /api/adapters` |
| `entrypoint` | file inside the package directory to execute; must define the adapter class |
| `class` | optional, defaults to `PartylineAdapter` |
| `command` | default argv when the attach form leaves the command blank — an array, never a shell string |
| `requires` | executables that must be on `PATH` |
| `env_unset` | inherited variables to drop before spawning; a trailing `*` clears a whole prefix |
| `capabilities` | table; `resume = true` only if re-attaching genuinely reopens the previous session |
| `update_command` | optional argv to check/install CLI updates before a fresh attach; omit or `[]` if the process has no updater. Never a shell string. A pipe install belongs in one `bash -lc` argument. |

Never put secrets or machine-specific paths in a manifest.

## Entrypoint

```python
from partyline.adapters import Adapter


class PartylineAdapter(Adapter):
    kind = "example-process"

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["example-process"]
        return cmd + ["--session-id", self.att["id"]]

    async def _run(self):
        await asyncio.sleep(4.0)
        if not self.resume:
            await self.send_keys(self.briefing())
        # ...locate this process's transcript, then:
        await self._tail_jsonl(path, handle)
```

What the base class gives you: pty spawn and drain, bracketed-paste input (`send_keys`), the
join briefing (`briefing()`), screen rendering for peek, `_tail_jsonl(path, handle)`, and
`_fresh(timestamp)` for filtering replayed history after a resume. What you supply: the argv, and
a `_run()` that finds this process's transcript and posts assistant text with
`self.post(self.att["name"], "agent", body)`.

Rules that hold for every adapter:

- Start the real interactive executable in the supplied pty. Never substitute a headless mode or
  an SDK call — it is a different program with different behaviour and different auth.
- Keep the drain running so the child never blocks on a full pty buffer.
- Prefer the process's own structured transcript. Screen scraping is a last resort; the `raw`
  adapter's quiescence flush exists for line-oriented programs with no transcript at all.
- Don't replay history after a resume, and cancel background tasks on stop.

### Resume continuation delivery

`running`, pty-writable, transcript-ready, and continuation-received are separate lifecycle
states. A resumed TUI can silently discard bracketed paste during startup, so partyline never
advances an attachment's message cursor merely because bytes were written.

If the interactive CLI accepts an initial prompt, override
`stage_startup_delivery(messages) -> bool` and put `format_digest(messages)` into the real
resume command's argv. Then call `mark_startup_delivery_received()` only when the claimed
structured transcript records that exact digest as user input. The coordinator awaits
`wait_startup_delivery_received()` before advancing the cursor. Do not implement this boundary
with a sleep or screen scraping.

Adapters without an argv prompt keep the default `False` result. The coordinator waits for
their normal `wait_ready()` signal before calling `deliver()`, and advances the cursor only
after that call returns successfully.

The same evidence boundary applies after startup. A CLI may accept bracketed-paste bytes while
an open turn is still running but defer ingesting them until that turn ends. Such an adapter must
return an uncredited delivery result, suppress duplicate writes of the same outstanding ids, and
confirm those ids through the host callback only after a newer structured user-input record
contains the exact digest. Automatic reattachment waits for that receipt outside the pty ownership
lock. A later cumulative digest may cover swallowed predecessors only when it contains every one
of their message ids; a disjoint batch cannot jump the cursor. Never infer acceptance from a hook,
terminal echo, or elapsed time.

### Locate the transcript unambiguously

This is the one that bites. If the CLI accepts a session id or a session directory, **pass one
you chose** — the transcript path is then exact and nothing else can occupy it. The bundled `pi`
adapter does this: it pins `--session-id` to the attachment id and `--session-dir` to a directory
of its own, so discovery cannot be wrong.

If the CLI gives you nothing to pin and you have to match on working directory and start time,
then you must also:

- **claim** the file you resolve, and skip any file another attachment has claimed, and
- **serialize** discovery, so two attachments cannot resolve at the same moment.

Two copies of the same CLI started in one directory seconds apart are otherwise
indistinguishable, and the second attachment will tail the first one's transcript and repost its
messages under the wrong handle. This is not hypothetical — it happened, and the symptom is every
message appearing twice under two different names.

## Import and reload

```bash
curl -X POST http://127.0.0.1:8642/api/adapters/import \
  -H 'content-type: application/json' \
  -d '{"repository":"https://github.com/example/partyline-adapters.git","ref":"main"}'

curl http://127.0.0.1:8642/api/adapters            # id, version, capabilities, source
curl -X POST http://127.0.0.1:8642/api/adapters/reload
```

`ref` is optional. The repository is cloned into the adapter store
(`PARTYLINE_ADAPTERS_DIR`, default `~/.partyline/adapters`) and every manifest it contains is
validated and registered.

Reload re-executes the adapter files in place — bundled and imported alike — so editing an
adapter does not need a server restart. Attachments that are already running keep the code they
started with; new attachments get the new code. Changes to partyline itself (the base class, the
loader) still need a restart.

An imported package that shares an id with a bundled one **replaces** it. That is deliberate —
it is how you override a shipped adapter. The loader makes the precedence visible three ways:

- `GET /api/adapters` reports `source` — the literal string `bundled`, or the absolute path of
  the imported package — and `overrides_bundled`, true when an imported id shadows a bundled one;
- the UI shows a small `imported` badge wherever the adapter identifies itself: the attach-form
  picker and the jack in the right rail;
- the server logs a warning naming each shadowed id, on import, on reload, and at startup when a
  previously imported store is re-registered.

The logging matters more than it looks. Precedence used to be recorded only in a `source` field
nobody reads, and an installation was found running seven of its eight adapters from an import
without a single line of output saying so — every fix shipped to the bundled copies was dead code
on that machine. A silent override is how that happens.

### Going back to the bundled copy

The adapter store holds one directory per imported **repository**, not per adapter, so removal is
per checkout:

```bash
ls ~/.partyline/adapters/                       # one directory per imported repository
rm -rf ~/.partyline/adapters/<repository-name>  # or move it anywhere outside the store
curl -X POST http://127.0.0.1:8642/api/adapters/reload
```

Reload re-registers the bundled package for any id whose imported source has gone. If neither
exists the id is dropped and the reload fails loudly rather than leaving a half-registered
adapter behind.

Renaming a checkout to a dot-prefixed name inside the store also disables it: hidden directories
are skipped and the skip is logged. That is a deliberate affordance for turning an import off
without deleting it — and it exists because the obvious gesture used to fail silently, leaving a
"disabled" checkout loading exactly as before.

One thing that looks like it should work and does not: `DELETE /api/adapters/<id>` does **not**
delete anything. It answers with a reminder to remove the checkout yourself, because a checkout
may contain several packages, and removing a whole repository to disable one adapter would be a
surprising thing for a DELETE on a single id to do.

> Importing an adapter executes its code as your user. `adapter.py` runs on import and is not
> sandboxed. Read what you import.

## Testing an adapter

Run a throwaway instance, never a live database:

```bash
PARTYLINE_DB=/tmp/partyline-test.db PARTYLINE_PORT=8643 uv run partyline
```

Check start, mention delivery, reply posting, peek, exit, and stop. Then check the failure modes:
a missing manifest field, a bad entrypoint, a process that exits before producing output, and
**two attachments of the same adapter started in the same working directory at once** — they must
end up with separate transcripts.

Credentials for an attached process come from the environment partyline was started with, so
start the server with them inline:

```bash
EXAMPLE_API_KEY=$(cat ~/.secrets/example) uv run partyline
```

Don't put them in shell profiles, manifests, commands stored as presets, or commits.
