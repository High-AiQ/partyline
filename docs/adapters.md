# Adapter packages


| DO | DO NOT |
| --- | --- |
| Locate and claim exactly one transcript, by structured content the CLI itself records (a conversation id read back, a session id, a claim token you pasted) | Guess identity from timing, directory scan order, mtimes, or any identifier that outlives the activation |
| Post chat speech from structured transcript records | Turn terminal screen contents into chat messages |
| Declare manifest capabilities honestly (`resume`, `turn_end`, `transcript`, `immediate_mentions`) — routing and presence enforce against them | Mark a screen-scraped adapter as a transcript adapter, or forget `transcript = true` on a tailing one |
| Leave `immediate_mentions` unset unless the harness ingests mid-turn, and publish a preflight when that depends on the host | Treat a successful pty write as immediate delivery, or reach immediacy by cancelling the running turn |
| Give every pasted wake content that proves which activation sent it | Assume the process you spawned is still the process that runs — CLIs self-update and re-exec |
| Ship the adapter's own tests with fixture transcripts and negative controls | Run the vendor's CLI in tests, or trust a green suite whose controls were never failed on purpose |

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
| `capabilities` | table; `resume = true` only if re-attaching genuinely reopens the previous session; `immediate_mentions = true` only if a mention reaches a turn that is *already running* (below) |
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

### Immediate mentions

Most harnesses read their composer only at a turn boundary. Bytes written into a pty are
therefore *queued*, not delivered: the mention sits behind however long the current turn takes,
which on a busy agent is minutes, and behind a blocked subagent it can be indefinite. That is a
property of the CLI, not of partyline, so it is declared per adapter.

```toml
capabilities = { immediate_mentions = true }
```

The claim is that a mention arrives at a turn **already in progress**. It is `false` for every
adapter that does not say otherwise, because the failure mode of guessing is a room that believes
a message landed while it is still waiting.

Two conditions, deliberately kept apart:

| | question | source |
|---|---|---|
| **supported** | does this harness ingest mid-turn at all? | the manifest |
| **effective** | does it on *this host*, right now? | the adapter's optional preflight |

`partyline.adapter_capabilities.immediate_mentions(kind, env)` resolves both and returns the
reason. An adapter whose harness needs nothing from the host is effective as soon as it claims
support. One whose behaviour depends on user configuration publishes a static method on its
class:

```python
class PartylineAdapter(Adapter):
    immediate_mentions_preflight = staticmethod(my_preflight)  # (env) -> (bool, detail)
```

The preflight must **read only**. A capability check that edits a user's CLI configuration to
make itself true is not a check. Return the remedy in `detail`: an operator told only "not
immediate" has to rediscover the setting, the file, and whether a restart is needed.

Immediacy must also be *non-destructive*. Several CLIs offer an interrupt chord that delivers at
once by cancelling the running turn; that discards in-flight tool results and is not what this
capability means. If the only way to reach a running turn is to stop it, declare `false`.

**Antigravity (`agy`)** does *not* declare it, and the reason is worth recording because the
harness looks superficially similar. It queues a mid-turn message and tells the agent that "a
user-queued message is ready to be dequeued", and 1.1.27 carries a per-message delivery strategy
internally (`MESSAGE_DELIVERY_STRATEGY_{UNSPECIFIED,WHEN_IDLE,NEXT_INVOCATION}`, a
`queued_message_delivery_strategy` field, a `GetQueuedMessageDeliveryStrategy` call). But nothing
exposes that choice: no flag in `agy --help`, no key its `settings.json` accepts, no slash
command, nothing in `agy changelog`. Its only user-facing mid-turn keys are `Esc` and `Ctrl+C`,
both documented as interrupts that cancel the running operation. Since the capability forbids
reaching a turn by stopping it, Antigravity stays `false` until Google exposes the strategy.
Whether its dequeue prompt causes the *model* to pick a message up before the turn ends is an
empirical question about model behaviour, not a guarantee the harness offers, and a capability
must not rest on it.

**Grok Build** is the first implementation. It queues mid-turn follow-ups by default and holds
them entirely while blocked on a subagent or background task; `[ui] follow_up_behavior = "steer"`
in `$GROK_HOME/config.toml` (default `~/.grok/config.toml`) makes it inject at the next tool or
model safe gap instead, leaving in-flight tools alone. There is no environment variable for the
key and project-scoped config does not carry `[ui]`, so it is a user-wide preference that
partyline reads and never writes. A running Grok does not reload it — the leader process owns
config reload and is off by default — so the setting applies to processes started or **resumed**
afterwards. `partyline/adapters/bundled/grok/steering.py` implements the preflight and cites the
CLI's own documentation.

### Interrupt and send (`@!name`)

An ordinary mention waits for a turn boundary. `@!name` asks the process to stop what it is doing
and read the message now. It is the deliberate exception, and every constraint on it exists
because interrupting is expensive: whatever tool was in flight produces no result, and the model
is left continuing a task whose output never arrived.

| rule | why |
|---|---|
| **Humans only.** An agent-written `@!name` is delivered as a plain mention | an agent's reply wakes other agents, so an agent-authored bang lets a busy room cancel its own work in a loop |
| **One pending interruption per process.** A second bang while the first is unresolved is dropped, not stacked | repeated `Esc` produced six consecutive interrupt/empty-response cycles in real Antigravity transcripts |
| **The message is always delivered** — confirmed, refused, or unsupported | the interrupt is best effort; delivery is not |
| **`@!all` is not interruptible** — it rings the room like `@all` | stopping every process at once is a blast radius nobody asked for |
| **Confirmation comes from the harness**, never from the keystroke | a successful pty write is not a successful CLI submission |

An adapter opts in by publishing `async def interrupt(self)`, returning one of three statuses.
Two would not be enough — a process with no turn running is neither a success nor a failure:

| status | meaning |
|---|---|
| `interrupted` | the harness itself confirmed a running turn was stopped |
| `idle` | there was no turn to stop, so nothing was attempted and nothing needs confirming |
| `unconfirmed` | it was attempted and the harness never proved it worked |

`idle` must be answered **without touching the pty**. On 2026-09-09 a live `@!` landed two
seconds after its target's turn had already closed: `Esc` cancelled nothing, no notice was ever
written, and the message was held for the full ten-second confirmation timeout before delivery.
The fast path is only taken on a *positive* "closed" — an adapter that does not track turn state
is unknown, not idle, and still gets the keystroke, because assuming idle would silently decline
to interrupt a process that was working.

Absence of the method means unsupported, and the room is told so by name:

```
⚠ @sol cannot be interrupted — the codex adapter has no supported interrupt,
  so the message was delivered as an ordinary mention
```

**Antigravity** implements it, and needs *two* boundaries rather than one:

1. `Esc` cancels the active operation and the CLI records a `SYSTEM`/`ERROR_MESSAGE` step reading
   *"Error: The stream was interrupted. Please continue the task you were working on."* Nothing
   else stands in for it — no `PLANNER_RESPONSE` in 28 transcripts (~8,300 steps, read
   2026-09-09) ever carried a cancelled, aborted, or failed status. The record must also be
   **newer than the keystroke**, compared exactly — Antigravity writes the transcript on the same
   host that presses `Esc`, so there is one clock and no skew to absorb, and any backward
   tolerance is precisely the window in which the *previous* interruption's notice confirms this
   one. A record with no usable timestamp confirms nothing, because it cannot be placed on either
   side of that boundary. A notice that has already confirmed an interruption is also spent and
   cannot confirm another, which closes the same hole from the other side: a stale notice is
   rejected whether it arrives before this `Esc` (already used) or after it (older than the
   boundary), and neither check depends on how far behind the tail is running.
2. The turn must then actually **close**. Confirming the notice alone would report success while
   the composer was still mid-turn, and Antigravity accepts a mid-turn submission and silently
   drops it — that is how two mentions were lost on 2026-08-24.

Even with both, an interrupt does not *guarantee* the next paste is ingested, and nothing here
claims it does. Delivery keeps its existing contract: a wake settles only against a transcript
`USER_INPUT` record, and an unsettled wake repools for redelivery once the CLI is idle. The
interrupt improves the odds; settlement is what makes the message safe.

Note the difference from [immediate mentions](#immediate-mentions): that capability requires
reaching a running turn *without* stopping it, and an adapter must not claim it by interrupting.
The two are opposites, and an adapter can support either, both, or neither.

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

If the CLI will not take a caller-chosen id, pin something else it *does* emit — Antigravity's
`--log-file` per attachment, then the `Created conversation` line in that file. Resume may still
pass `--conversation` so the CLI can try to reopen context, but the tailed transcript is the id
this activation's log actually created after the log was marked. A stored `cli_session` is not
that evidence: `agy` can open a new conversation anyway, and the old transcript then goes silent
while the new one holds the recovery speech.

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

### Antigravity conversation discovery is read out of a log the CLI also echoes into

`agy` takes no caller-chosen conversation id, so the adapter learns which
conversation it is on by reading this attachment's own `--log-file` for a
`Created conversation <uuid>` or `Resuming conversation <uuid>` line written
after the activation marked the file.

Both verbs are required, and reading one was an outage: `build_command` passes
`--conversation` on resume, so a resumed CLI only ever says "Resuming".
Matching "Created" alone worked for the run that created the conversation and
failed on every restart after it — the process ran, accepted input, and relayed
nothing, because discovery timed out before a transcript was ever opened.

The same log carries `HandleUserInput called with text: "…"`, the CLI quoting
its own input back. That input is chat, which anyone on the line can write, so
those lines are skipped: otherwise a message reading `Created conversation
<uuid>` would pin the adapter to a transcript of the sender's choosing. This
was found in a real log, harmless only because no uuid followed the phrase.

| DO | DO NOT |
| --- | --- |
| Keep the echo skip matched to the vendor's exact marker | Loosen it into a heuristic that might skip a real CLI line |
| Re-check that marker when `agy` updates — a reworded log reopens the injection path with these tests still green | Assume a passing suite proves the filter still matches anything |
