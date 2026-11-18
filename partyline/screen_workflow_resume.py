"""Resume the same approved input plan at its first uncommitted action."""

import json
import secrets
from collections import OrderedDict

from fastapi import HTTPException

from . import screen_workflow_audit as audit
from .screen_workflow_access import require_run_window

MAX_PARAMETER_BYTES = 512 * 1024
RECENT_RUN_INPUTS = 16


class RecentInputs:
    """Keep repeat submissions convenient without writing parameter values to the audit."""

    def __init__(self):
        self.values = OrderedDict()

    def remember(self, run_id, parameters):
        self.values[run_id] = parameters
        self.values.move_to_end(run_id)
        if len(self.values) > RECENT_RUN_INPUTS:
            self.values.popitem(last=False)

    def parameters(self, run_id, supplied):
        if supplied is not None:
            return supplied
        if run_id not in self.values:
            raise HTTPException(422, "supply the original workflow parameters to resume")
        return self.values[run_id]


def plan_for(revision, parameters):
    if len(json.dumps(parameters, ensure_ascii=True, separators=(",", ":"))) > MAX_PARAMETER_BYTES:
        raise HTTPException(422, "workflow parameters exceed their size limit")
    try:
        return revision.plan(parameters)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


def plan_hash(db, revision, parameters, plan):
    return audit.fingerprint(
        db, ["screen-workflow-plan", revision.digest, parameters, [
            (step_id, step.model_dump(mode="json")) for step_id, step in plan
        ]]
    )


async def resume(service, principal, conv_id, run_id, supplied):
    _, att = service.start_identity(principal, conv_id)
    if principal.kind == "machine":
        row = service.row(conv_id, run_id)
        if row is None:
            raise HTTPException(404, "workflow run not found")
        require_run_window(service, principal, row)
    else:
        row = service.get(principal, conv_id, run_id)
    if not audit.view(row)["resumable"]:
        raise HTTPException(409, "workflow run cannot be resumed")
    if supplied is None and principal.kind == "machine" and principal.attachment_id != row["attachment_id"]:
        raise HTTPException(422, "supply the original workflow parameters to resume")
    parameters = service.recent_inputs.parameters(run_id, supplied)
    revision = await service.revision(conv_id, row["workflow"])
    if (revision.digest, revision.path, revision.project) != (row["revision"], row["path"], row["project"]):
        raise HTTPException(409, "resume requires the original approved workflow bundle")
    if not audit.approval(service.db, revision):
        raise HTTPException(403, "a person must approve this exact workflow revision")
    plan = plan_for(revision, parameters)
    if not secrets.compare_digest(row["plan_hash"], plan_hash(service.db, revision, parameters, plan)):
        raise HTTPException(409, "resume requires the original parameters and expanded plan")
    current = service.row(conv_id, run_id)
    if current is None or any(
        current[key] != row[key] for key in ("state", "finished_at", "verified_steps", "input_pending")
    ):
        raise HTTPException(409, "workflow run changed during resume")
    run, grant = service.prepare(principal, conv_id, att, run_id, row["grant_id"], plan, revision)
    if grant["owner_id"] != row["owner_id"]:
        raise HTTPException(409, "resume requires the original window grant")
    run.verified = row["verified_steps"]
    service.validate_remaining(principal, run.grant_id, plan[run.verified:])
    run.step_id = plan[run.verified][0]
    run.window_hash = row["window_hash"]
    run.intent = bool(row["input_pending"])
    run.resuming = True
    audit.resume_requested(run)
    return service.launch(run, parameters)
