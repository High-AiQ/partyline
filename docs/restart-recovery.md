# Recovering a plain instance after a restart

Partyline can run as a **plain service**: a server process with no restart continuation plan.
Restarting such an instance stops every attached process, and nothing resumes them for you. That
is a different situation from the cockpit, whose planned restart persists a plan and recovers its
attachments ([dogfooding.md](dogfooding.md)).

Use [agent-refresh.md](agent-refresh.md) to bring a single process back with context; this file
covers refreshing and recovering the whole plain instance.

| DO | DO NOT |
| --- | --- |
| Pull the deployed checkout and `uv sync --locked` first | Restart to "pick up" a commit the checkout does not have |
| Write a checkpoint for every process that is mid-work | Restart while a turn's outcome is unknown |
| Schedule the restart outside the process tree it kills | Trigger a restart from a process the restart will kill |
| Resume each stopped card, or Start fresh with a checkpoint | Assume the server resumes attachments — there is no plan |
| Prove identity and a continuation receipt afterward | Report success from the new `/api/version` alone |

## Refresh

```bash
git -C /path/to/deployed/checkout pull --ff-only
cd /path/to/deployed/checkout && uv sync --locked
# Prove the deployed tree boots before you stop the running server:
PARTYLINE_DB=/tmp/smoke.db PARTYLINE_MEDIA_DIR=/tmp/smoke-media \
  .venv/bin/partyline --host 127.0.0.1 --port 8099   # GET /api/version, then stop it
```

## Checkpoint each live worker

Follow [agent-refresh.md](agent-refresh.md): write a compact checkpoint with the task, artifacts,
acceptance state, pending work, next action, and the last message id it incorporated. A process
that was not mid-turn does not need one — Resume restores its session as-is.

## Restart

A restart triggered from a conversation is a restart triggered from inside the process tree it
kills, so schedule it through the service manager, outside that tree, with enough delay to end
your own turn:

```bash
systemd-run --user --on-active=30 systemctl --user restart <your-service>.service
```

The server marks every `starting`/`running` attachment `exited` on boot. Chat history, tasks, and
media are untouched.

## Recover

For each stopped card choose **Resume** to reopen the same session with its context (the default
for a process that was mid-work), or **Start fresh** to mint a new identity and pass the
checkpoint path plus its last incorporated message id. Mention a resumed process to deliver the
messages it missed; its first reply is delivered from structured input, not screen scraping, and
is the receipt that recovery worked. Confirm with `GET /api/running` that only the processes you
resumed are live.
