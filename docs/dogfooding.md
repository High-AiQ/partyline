# Dogfooding Partyline


| DO | DO NOT |
| --- | --- |
| Run the cockpit from its own clone and edit the workbench | Host the conversation from the checkout being edited |
| Deploy only through `scripts.cockpit check` → `deploy` → `plan` → `arm` | Restart without deploying, or use any restart trigger other than `arm` |
| Arm only after green preflight, explicit clears from every planned participant, and zero known findings | Let anyone be mid-turn when the restart lands — including the agent that arms it |
| Prove recovery afterwards: identity, continuation receipts, `/api/running` snapshots, consumed plan | Announce success without recorded evidence |
| Find the pid that owns the port and kill that pid | Ever run `pkill -f partyline` — it matches the room you are standing in |

Partyline can improve and restart the cockpit instance it is using to coordinate the work. This is
**recursive self-improvement**: agents use their own judgment to deploy a reviewed change, recover
the planned line, and continue without a required button, browser refresh, or human in the loop.

This is an operational procedure for contributors. Read [AGENTS.md](../AGENTS.md) before using it —
that file is the authoritative safety contract; the failure modes that shaped this procedure are
recorded in [lessons.md](lessons.md).

> **Platform requirement:** Partyline itself supports Linux and macOS, but the automated
> `scripts.cockpit arm` procedure requires Linux with a working systemd **user** session. It uses a
> user transient unit to survive the triggering agent's turn and to make the scheduled restart
> inspectable.

## The boundary

The instance hosting a conversation must run from a separate **cockpit** checkout. Edit and test in
the **workbench** checkout, then advance the cockpit deliberately. Restarting a cockpit without
deploying merely starts the old code again.

```bash
uv run python -m scripts.cockpit check
uv run python -m scripts.cockpit deploy
uv run python -m scripts.cockpit plan "partyline refactoring" --all \
  --debrief "Continue from the committed handoff."
# After every planned participant has explicitly cleared:
uv run python -m scripts.cockpit arm --pid NNNNN --database ~/.partyline-lan.db
```

`check`, `deploy`, and `plan` do not restart anything. `check` refuses a dirty or unpushed
workbench, a stale frontend bundle, a live `/api/version` that does not match
the cockpit tree, a mismatched adapter source/runtime checkout, a failed trigger,
or an automatic plan that has remained unclaimed long enough to show that its trigger never fired.
`deploy` fast-forwards the cockpit, runs `uv sync --locked` in its venv, and
verifies that the tree matches the workbench. A matching commit with a stale
venv is how v0.32.0 left the line down.

`plan` is automatic by default and persists the exact resumable attachments plus a continuation
debrief; use `--manual-offer` only when a human should explicitly accept the plan. Planning is
authorization, not a restart.

The named line always *owns* the plan — it is where a manual offer appears and where a failure is
reported. `--all` widens which processes the plan recovers, not which line owns it: every live
resumable process on every unarchived line, in owner-first order. A shutdown stops every attached
process on every line, so on an instance hosting more than one live line, `--all` is the normal
choice. A manual offer is shown to one tab and stays line-scoped; `--all` requires an automatic plan.

Recovery then reads each process's own line: its pending messages, its readiness notices, and its
failures are posted where that process lives, and every covered line hears the start banner and the
closing summary.

### The one restart that cannot be planned fleet-wide

The first upgrade onto fleet planning is a bootstrap: the server still running is the one that does
not understand `--all`, so it would persist a line-scoped plan while reporting success, and arming
would then refuse it with no way forward. `plan --all` therefore checks the live `/api/version` and
refuses first, naming this procedure.

For that one restart:

1. `plan` the cockpit line alone — a line-scoped plan is all the running server can write.
2. Close every other line's processes deliberately, with the close control. These are exactly the
   processes the arm refusal would otherwise name; closing them is the decision, made once, in the
   open, with each line checkpointed first.
3. `arm`. Coverage now holds, because nothing else is live.
4. Reattach the closed lines afterwards and prove each continuation receipt.

From the next restart on, `--all` covers everything and none of this is needed.

## Machine planning and hierarchy

An authenticated machine may plan its own line on loopback. Fleet planning also
requires its manager authority over every line with starting or running
attachments; unrelated dormant lines do not contribute recovery work. The fleet
selection itself is never narrowed. If an unrelated live line exists, use an
authorized human operator for the instance plan. The arm and delayed-trigger
coverage checks remain instance-wide.

When upgrading existing projects to scoped credentials, preview and apply the
explicit parent/manager mapping in [hierarchy.md](hierarchy.md) before resuming
managers. This makes their first resumed briefing reflect the intended roles.

## Arming a restart

Only arm after preflight is green, every planned participant has explicitly cleared, and no known
finding remains. Any participant may block the restart.

Arming also refuses while any live process is missing from the plan, naming each one with its line.
The restart stops every attached process but recovery resumes only what the plan names, so an
unaccounted process comes back detached and silent — the same shape of failure that let two broken
triggers go unnoticed for hours. Re-plan with `--all`, or deliberately close the processes you do
not intend to bring back. Each name carries its adapter, because a process whose adapter cannot
resume can never appear in a plan however many times you re-plan: it has to be stopped explicitly,
or knowingly lost, and that is somebody's decision rather than a side effect.

Coverage is checked twice, because arming and restarting are up to 90 seconds apart. The trigger
re-reads the plan and the live processes from the outgoing server's *own* database — resolved from
that server's environment snapshot, since a transient systemd unit inherits neither `PARTYLINE_DB`
nor the interactive user's `HOME`, and a relative `PARTYLINE_DB` means relative to the server's
own working directory — and refuses before signalling if anything attached in the meantime.

Every way of *not knowing* is a refusal: a database path that is still relative, or a database
that is missing, unreadable, without the schema, or no longer holding the plan, stops the restart.
A relative path is rejected before any filesystem read, because a same-named database in the
trigger's own directory would answer for the wrong instance — and if that one happened to be fully
covered, it would wave the restart through. None of those is an instance with nothing
to lose; each is either the wrong path or an instance something else has already changed, and the
only question at that moment is whether SIGTERM is about to strand a process.

The arming side reads `$PARTYLINE_DB`, falling back to `~/.partyline.db`. When the instance runs
on another database — this one is `~/.partyline-lan.db` — pass `--database` so the plan and the
live set are read from the same instance. The trigger does not need the flag: it takes the path
from the outgoing server itself.

Every option in the scheduled argv is passed as `--option=value`. A plan's report token is a
`secrets.token_urlsafe` value whose alphabet includes `-`, and the separated form let the trigger's
parser read a dashed token as an option — see `docs/lessons.md`.

`arm` is the only supported trigger. It schedules a reviewed Python executable through systemd,
then reads back the timer and complete service argv before reporting success. It identifies the old
server by PID **and** process-generation start time, waits for that exact generation to exit, and
then launches the deployed cockpit.

When the replacement must use a durable bind or instance label, pass an explicit config through the
trigger rather than relying on the cockpit checkout's current directory:

```bash
uv run python -m scripts.cockpit arm --pid NNNNN \
  --server-config ~/.config/partyline/cockpit.toml
```

The arm preflight resolves that file and records its absolute path in the verified service argv.
An explicit config owns the bind: the outgoing process's `--host`/`--port`/`--instance-name`
flags are dropped rather than preserved (preserving them once made a loopback cockpit unable to
migrate — the CLI flags outrank any config). The trigger still resolves the config against the
outgoing environment before it signals anything, and refuses if environment overrides would
change the config's result rather than returning on an unexpected address.

When the outgoing service runs from a *different* checkout than the one being deployed — the
first move of a workbench-hosted instance onto its own cockpit clone — name the executable the
live pid is actually running:

```bash
uv run python -m scripts.cockpit arm --pid NNNNN --cockpit ~/partyline-lan \
  --source-server ~/code/partyline/.venv/bin/partyline
```

The trigger anchors the preserved server flags on that console script instead of the
replacement's, which the old command line never contains. Arming preflights that the file exists
and that the pid's command line runs it; the trigger re-checks the same anchor before signalling,
and the generation, environment, and replacement-import guards are unchanged.

The replacement receives an environment snapshot from the verified outgoing process. This is
load-bearing: a transient systemd unit does not inherit the interactive user's `PATH`, and attached
CLIs may live in a user-local directory. If the old environment cannot be read, the trigger refuses
before signalling the server rather than launching with systemd defaults.

## Automatic recovery

On startup, the cockpit claims the persisted automatic plan through a durable lease and resumes the
saved attachments one at a time. The sequence is intentional: several coding CLIs can otherwise
discover and claim the same transcript concurrently. A slow but live attachment remains attached
and is reported as settling; only a genuine exit is a failure.

Continuation delivery is not inferred from a cursor or pty write. For adapters that support it,
the debrief is part of the native startup command and must appear as structured process input before
the cursor advances. A failed receipt preserves one recovery retry; a second unconfirmed attempt is
consumed with an actionable warning while the process remains live.

### When recovery leaves a continuation unconfirmed

`unconfirmed` is not `failed`: the process is running and was left alone on
purpose. Its cursor stays put, and it stays in `runtime.reattaching` so that
*if it later exits*, mentions are held rather than reported unreachable.

Nothing used to clear that flag except "start fresh" and removing the jack's
record — so an operator who detached and resumed kept it for the life of the
server, and once the process did exit the room was told nothing at all. An
explicit resume now clears it, which is what an operator means by resuming.

The retained flag never blocked delivery: `message_routing` consults it only
when there is no live adapter. A process left unconfirmed is still reachable
while it runs.

To find out *why* a continuation went unconfirmed, add

```
PARTYLINE_RECEIPT_DIAGNOSTICS=1
```

to the **cockpit checkout's `.env`**, then deploy and arm as usual. A running
server's environment cannot be edited from the arming shell, and the trigger
passes the *outgoing* process's environment through — so the switch has to be
somewhere the replacement reads at startup, and `.env` is that place. It takes
effect on the next restart and applies to every Grok attachment the recovery
resumes. Grok's receipt tracker then logs, every line tagged with the attachment id and
the activation that owns it: the seeded index, the paste boundary, each
observed record, whether it matched a pending wake, and — separately — whether
the delivery callback then granted or refused the credit. Matching and crediting are different failures with
different fixes, so they are never reported as one.

It is off by default because the server configures only uvicorn's loggers: the
root logger has no handler, so an INFO record from that module is discarded and
an operator sees nothing. A unit test asserting on `assertLogs` cannot show
this, since `assertLogs` installs a handler of its own.

The check runs when a receipt tracker is constructed, not when the module is
imported. `load_dotenv()` runs in `server.py` well after import, so reading the
environment at import time would look before the file that sets it had been
read — the switch would be silently inert.

No prompt text and no credential is ever logged. A digest is identified by
eight hex characters of the SHA-256 of its whitespace-normalized form, which
distinguishes "the same string" from "a different string" and reveals neither.

## Proof after restart

Green local tests are necessary but not sufficient. A dogfood change is complete only when the real
cockpit has deployed, restarted, recovered, and continued its own work. Record evidence for:

- each process's identity and continuation receipt, using a fresh per-restart nonce in structured
  input rather than terminal screen contents or raw transcript grep;
- all planned attachments present in `/api/running`, including a second snapshot after a delay;
- the completed restart plan consumed at the expected attempt count;
- no unexplained warning lines in the conversation;
- reconnect resynchronization, by dropping a socket while state changes and proving catch-up without
  a document reload; and
- when a release changes only Python, the open tab's release badge updating on its next handshake
  while the unchanged frontend build avoids a reload.

The coordinator summary is useful, but it is not the proof. Keep the command output and transcript
evidence with the handoff so the next agent can distinguish a completed recovery from an assumption.

## Implementation notes for contributors

- **The automatic lease has one explicit lifecycle.** Claim with
  `claim_restart_plan(mode, owner, lease_seconds)`; renew with
  `renew_restart_plan_claim(token, owner, lease_seconds)` while waiting; release with
  `release_restart_plan_claim(token, owner)` on cancellation or error; and complete only after
  the final outcome with `complete_restart_plan(token, owner)`. A lost or expired owner is
  reclaimable, and a runner that loses ownership must launch no further processes.
- **Nobody may be mid-turn when the restart lands — including whoever triggers it.** An agent
  killed mid-turn comes back to a CLI that resumes the interrupted turn, so it posts a stray
  fragment into the room on wake. A scheduled trigger's delay has to outlast *your own* turn,
  not just your announcement.
- **Adapter changes do not need a restart** — `POST /api/adapters/reload` re-executes adapter
  packages in place. Changes to the base class, loader, server, or frontend do.
- Prefer changes that make a restart cheaper (resume support, adopting live attachments,
  liveness reporting) over changes that assume restarts are rare.
