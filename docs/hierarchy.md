# Managers and child lines

A line can belong to a parent project. Each line has at most one designated
manager attachment. The role belongs to that attachment's identity, not its
handle or model: two processes named `reviewer` on different lines remain
separate participants.

Humans use the line menu's **management** dialog to choose the parent and the
manager. Granting a manager delegates control of work beneath that line. Ordinary
participants keep access to their own line; a manager can create child lines,
attach participants, assign work, and inspect descendant progress. Unrelated
lines remain outside that machine credential's scope. Removing the manager role
changes authorization on the next request.

The manager receives the additional API instructions when the role applies.
Ordinary implementers do not receive the hierarchy playbook. A role change is
reflected in the next wake's instructions; hiding instructions is a context
optimization, while the server's authorization checks enforce the boundary.

## Reporting upward

A child manager can deposit a report in its parent's inbox. Ordinary reports do
not start a parent turn. For completion, a question, or a blocker that needs
attention, an explicit notification can wake the designated parent manager.
Repeated unacknowledged updates coalesce instead of starting another turn for
every update. A stored report with `notified_at:null` has not completed its notification;
retry the escalation after the parent manager becomes available. Ordinary child chatter is never forwarded automatically.

| DO | DO NOT |
| --- | --- |
| Send assignments to a named participant on an explicit child line | Assume a bare mention here reaches the same handle on another line |
| Deposit routine progress; explicitly notify for a result, question, or blocker needing attention | Turn every status update or acknowledgment into a parent wake |
| Keep source line and attachment identity with reports | Infer ownership from a display handle alone |
| Inspect reports and acknowledge the handled notification before moving on | Treat receipt of a report as acceptance of the work |
| Grant manager roles only for the intended project scope | Treat a machine credential as instance-wide administration |

## Recovery

Parent/child relationships do not replace the restart plan. A restart affects
all attached processes, including independent lines. Use the fleet planning and
recovery procedure in [dogfooding.md](dogfooding.md), obtain explicit clearance
from every affected participant, and verify each line's recovery. Book teams
must drain provider calls and reconcile spend before clearing a restart.

Each line keeps its own transcript, tasks, and checkpoints. A shared plan must
resume each process against its own line's pending history.

## Adopting existing projects during an upgrade

A trusted local operator can apply an explicit mapping when the running server
predates hierarchy support. This does not mint or borrow a human API credential.
It uses the operator's existing access to the instance database, like the cockpit
maintenance commands. API callers remain subject to their normal scope checks.

Prepare a JSON file containing `lines`, each with `conversation_id`, nullable
`parent_id`, and nullable `manager_attachment_id`. Use verified attachment IDs;
never derive roles from handles. Preview against the exact instance database:

```bash
uv run --locked python -m scripts.line_management \
  --database /absolute/path/instance.db --file /absolute/path/mapping.json
```

The default command is read-only, including on a pre-hierarchy database. Review
the current and proposed assignments and each manager's resulting scope. After
the code and mapping are reviewed, apply that exact preview:

```bash
uv run --locked python -m scripts.line_management \
  --database /absolute/path/instance.db --file /absolute/path/mapping.json \
  --apply --expected-sha256 SHA_FROM_PREVIEW
```

Apply validates the whole graph before writing, performs a second state check
inside the transaction, and refuses a stale preview. It runs the normal schema
migrations and changes only the mapped parent and manager assignments. It does
not stop, resume, or message any process. Follow the restart clearance procedure
separately before replacing the running server.

## Report acknowledgment contract

Read a report from the parent inbox, then POST
`/api/conversations/<parent-id>/reports/<report-id>/ack` with
`{"revision": N}`, using the revision returned by that read. An intervening child
update makes the acknowledgment return 409 and leaves the update pending; read
and assess it before retrying. Acknowledgment records receipt, not acceptance
of the child's work.

This release scopes machine credentials to their line and explicitly delegated descendants. Existing projects must appoint managers and link child lines before relying on cross-line API access. Human access remains instance-wide.

Start fresh creates a new attachment identity without inheriting the manager role. Appoint the replacement explicitly; resume retains the existing role.
