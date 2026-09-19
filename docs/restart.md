# Restarting the running instance

This project is developed through a running copy of itself, and a careless restart drops every
participant including you. This is the single restart flow: a deployed change goes live through a
request that a person approves, not through a manual `git pull` + Ctrl-C or an unattended trigger.

| DO | DO NOT |
| --- | --- |
| Merge, pull the deployment checkout, and `uv sync --locked` before requesting a restart | Request a restart to "pick up" a commit the deployed checkout does not have |
| Read `checkout_path` and `git_head` from `/api/version` to know which checkout the service serves | Assume the checkout you pulled is the one the service runs from |
| File a restart request with a clear reason and wait for a person to approve it | Restart the service by any path other than the approved request |
| Trust the automatic mid-turn mark and private continue notice to resume interrupted work | Delay approval waiting for every participant to go idle first |
| Prove recovery afterward: identity, continuation receipts, live attachment state | Report success without checking `/api/running` |
| Find the pid that owns the port and kill that pid | Ever kill by matching the word partyline across every process's command line — it matches the room you are standing in |

Read [AGENTS.md](../AGENTS.md) before using this procedure — that file is the authoritative
safety contract; the failure modes that shaped it are recorded in [lessons.md](lessons.md).

## The flow

1. **Deploy first.** Merge the reviewed change, fast-forward the deployment checkout, and run
   `uv sync --locked`. A restart only starts whatever code the checkout already has.
2. **File the request.** A line's captain (or a person) files a reason:

   ```bash
   curl -X POST "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/restart-request" \
     -H "Authorization: Bearer $PARTYLINE_TOKEN" -H "Content-Type: application/json" \
     -d '{"reason": "deploy the reviewed change"}'
   ```

   Filing requires the line's `assign` capability — a captain or a person, never any attached
   process for an arbitrary line. Only one request may be pending instance-wide; a second file
   attempt is refused until the first is approved or declined. What a restart would deploy is
   not a guess: `/api/version` reports the served `checkout_path` and the `git_head` the
   process started on, and a request whose checkout HEAD has not moved since startup is
   refused as **nothing to deploy** — the single most confusing restart is the one that
   restarts the same code. An intended no-code restart files with `"confirm_no_deploy": true`;
   the filed reason then carries a loud warning the approving person sees.
3. **A person decides.** Every open tab shows the pending request in `RestartApprovalDialog`,
   listing the reason and every currently live process fleet-wide. A person approves or declines
   it; a machine credential can never approve its own restart. There is no requirement to wait for
   every participant to go idle first — a process caught mid-turn is recovered automatically (see
   below).
4. **Approval persists the plan and restarts the unit.** Approving a request persists an automatic
   reattach plan covering every live process on every line (`create_restart_plan`, `mode="automatic"`,
   `scope="all"`), warns every open tab that the server is going down, and schedules
   `systemctl --user restart <unit>` a couple of seconds out — outside the process tree the restart
   is about to kill (see `partyline/restart_requests.py`).
5. **The new process resumes everyone.** On boot, the server claims the persisted plan through a
   durable lease and works through the saved attachments sequentially — several coding CLIs can
   otherwise discover and claim the same transcript concurrently (`partyline/reattach.py`,
   `run_automatic_restart_plan`). Continuation is not inferred from a cursor or pty write: for
   adapters that support it, the debrief is delivered as structured process input before the
   cursor advances, and each covered line hears a start banner and a closing summary. A failed
   receipt keeps one retry; a second unconfirmed attempt is consumed with an actionable warning
   while the process stays live and reachable. Whoever was mid-turn when the restart landed is rung
   once their process resumes.

The plan machinery — `restart_plan` table and columns, `reattach.py`, the claim/renew/release/complete
lease lifecycle — is unchanged from the earlier operator-CLI-driven procedure; only that naming
retired. Do not rename the table or its columns: live databases carry them.

## Who may do what

- **File a request:** the line's captain, or a person — the `assign` capability
  (`partyline/machine_scope.py`).
- **Approve or decline:** a person only (`is_human`). A machine credential is refused with 403.
- **Plan a restart directly** (`POST /api/restart-plan`, used internally by approval): loopback
  only, and a machine may plan only its own line — see `allows_restart_plan`.

## What the person sees

The banner names who asked and why. Approving broadcasts `☏ restart approved by @who — partyline
is restarting; every live process is resumed with its context when it is back` to the requesting
line, then a `ShutdownEvent` to every open tab so no one is left wondering whether the drop was a
crash. Declining announces `☏ restart declined by @who` and leaves the service untouched.

## What happens to a process mid-turn

A restart does not wait for anyone to finish. Presence durably marks an attachment `turn_open`
whenever it reports `working` or `speaking` (`partyline/turn_marker.py`); an orderly shutdown does
not clear it, only the harness reporting the turn actually ended does. So a process killed
mid-turn comes back still marked.

Before that process is resumed, the reattach coordinator checks the mark, clears it, and files a
private notice addressed to that process alone — unrouted, so it rides the same backlog the resume
delivers: `↻ @name — your process was restarted in the middle of a turn. Nothing on disk was lost.
Continue exactly where you left off, and hand off with an @mention when you are done`
(`turn_marker.announce_if_interrupted`). The process reads that notice as part of its normal
resume delivery rather than discovering the interruption from a stray fragment in the room, which
is what let two agents sit waiting on a reply that would never come before this mark existed.

## Verifying afterward

Green local tests are necessary but not sufficient. A restart is complete only when the live
instance has restarted, recovered, and continued its own work. Record evidence for:

- each process's identity and continuation receipt, using a fresh per-restart nonce in structured
  input rather than terminal screen contents or raw transcript grep;
- all planned attachments present in `GET /api/running`, including a second snapshot after a delay;
- the completed restart plan consumed at the expected attempt count;
- no unexplained warning lines in the conversation; and
- the open tab's release badge updating on its next handshake (`GET /api/version`).

The coordinator summary is useful, but it is not the proof. Keep the command output and transcript
evidence with the handoff so the next agent can distinguish a completed recovery from an assumption.

## Manual fallback: when no plan exists

A plain restart with no persisted plan (for example, a restart triggered outside this flow, or an
instance that has never filed a request) stops every attached process with nothing to resume them.
See [restart-recovery.md](restart-recovery.md) for that separate procedure: pull and verify the
deployed checkout, checkpoint every live process, restart from outside the process tree, then
resume each stopped card (or start fresh with a checkpoint) by hand.

## Diagnosing an unconfirmed continuation

`unconfirmed` is not `failed`: the process is running and was left alone on purpose. To find out
*why* a continuation went unconfirmed, add

```
PARTYLINE_RECEIPT_DIAGNOSTICS=1
```

to the **deployment checkout's `.env`**, then deploy and restart as usual. A running server's
environment cannot be edited from the requesting side, and the restart trigger passes the
*outgoing* process's environment through — so the switch has to live somewhere the replacement
reads at startup, and `.env` is that place. It takes effect on the next restart and applies to
every Grok attachment the recovery resumes. No prompt text and no credential is ever logged: a
digest is identified by eight hex characters of the SHA-256 of its whitespace-normalized form.

## Implementation notes for contributors

- **The automatic lease has one explicit lifecycle.** Claim with
  `claim_restart_plan(mode, owner, lease_seconds)`; renew with
  `renew_restart_plan_claim(token, owner, lease_seconds)` while waiting; release with
  `release_restart_plan_claim(token, owner)` on cancellation or error; and complete only after
  the final outcome with `complete_restart_plan(token, owner)`. A lost or expired owner is
  reclaimable, and a runner that loses ownership must launch no further processes.
- **Adapter changes do not need a restart** — `POST /api/adapters/reload` re-executes adapter
  packages in place. Changes to the base class, loader, server, or frontend do.
- Prefer changes that make a restart cheaper (resume support, adopting live attachments,
  liveness reporting) over changes that assume restarts are rare.
