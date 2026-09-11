# Refreshing and recovering the LAN instance

The LAN instance (`partyline-lan.service`, port 8643, `~/.partyline-lan.db`) is **not** the
cockpit. It has no restart continuation plan and no automatic recovery: restarting it stops
every attached process, and nothing resumes them for you. Use
[agent-refresh.md](agent-refresh.md) to bring a single process back; use this file for the
whole-instance refresh.

The cockpit's planned restart and automatic recovery are the different procedure in
[dogfooding.md](dogfooding.md); do not use either file's steps on the other instance.

| DO | DO NOT |
| --- | --- |
| Pull and `uv sync --locked` before restarting | Restart to "pick up" a commit the checkout does not have |
| Write a checkpoint for every process that is mid-work | Restart while a turn's outcome is unknown |
| Schedule the restart outside the service cgroup | Trigger a restart from a process the restart will kill |
| Resume each stopped card, or Start fresh with a checkpoint | Assume the server resumes LAN attachments — there is no plan |
| Prove identity and a continuation receipt afterward | Report success from the new `/api/version` alone |

## Refresh

```bash
git -C ~/partyline-lan-cockpit pull --ff-only
cd ~/partyline-lan-cockpit && uv sync --locked
# Prove the deployed tree boots before you kill the running one:
PARTYLINE_DB=/tmp/lan-smoke.db PARTYLINE_MEDIA_DIR=/tmp/lan-smoke-media \
  .venv/bin/partyline --host 127.0.0.1 --port 8655 &  # check /api/version, then kill it
```

## Checkpoint each live worker

Follow [agent-refresh.md](agent-refresh.md): write
`docs/agent-checkpoints/<project>/<task>.md` with the task, artifacts, acceptance state,
pending work, next action, and the last message id it incorporated. A process that was not
mid-turn does not need one — Resume restores its session as-is.

## Restart

A restart triggered from this conversation is a restart triggered from inside the thing it
kills, so schedule it through systemd, outside the service cgroup, with enough delay to end
your own turn:

```bash
systemd-run --user --on-active=30 systemctl --user restart partyline-lan.service
```

The server marks every `starting`/`running` row `exited` on boot. Chat history, tasks, and
media are untouched.

## Recover

For each stopped card, choose **Resume** to reopen the same session with its context (the
default for processes that were mid-work), or **Start fresh** to mint a new identity and pass
the checkpoint path plus its last incorporated message id. Mention a resumed process to
deliver the messages it missed; its first reply is delivered from structured input, not screen
scraping, and is the receipt that recovery worked. Confirm with `GET /api/running` that only
the processes you resumed are live.
