"""Persist content-free workflow events, idempotency and restart recovery."""

import hashlib
import hmac
import json
import time

from .auth_tokens import signing_secret

ACTIVE = ("running", "awaiting_confirmation", "stopping")
PUBLIC = ("id", "workflow", "revision", "state", "total_steps", "verified_steps", "current_step", "outcome")
RESUMABLE = ("failed", "stopped", "paused")
MAX_STEP_DISPATCHES = 3
MAX_RUN_RETRIES = 32


def fingerprint(db, data):
    key = signing_secret(db)
    if isinstance(key, str):
        key = key.encode()
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def prior_run(db, actor_scope, key):
    return db._exec(
        "SELECT * FROM screen_workflow_runs WHERE attachment_id=? AND client_key_hash=?", (actor_scope, key)
    ).fetchone()


def approval(db, revision):
    return db._exec(
        "SELECT * FROM screen_workflow_approvals WHERE project=? AND checkout=? AND path=? "
        "AND revision=? AND stamp=?",
        (revision.project, revision.checkout, revision.path, revision.digest, revision.stamp),
    ).fetchone()


def approve(db, revision, user_id):
    db._exec(
        "INSERT INTO screen_workflow_approvals VALUES(?,?,?,?,?,?,?) ON CONFLICT(project,checkout,path) "
        "DO UPDATE SET revision=excluded.revision,stamp=excluded.stamp,user_id=excluded.user_id,"
        "approved_at=excluded.approved_at",
        (
            revision.project,
            revision.checkout,
            revision.path,
            revision.digest,
            revision.stamp,
            user_id,
            time.time(),
        ),
    )


def view(row):
    result = {key: row[key] for key in PUBLIC}
    result["run_id"] = result.pop("id")
    result["resumable"] = bool(
        row["plan_hash"] and row["state"] in RESUMABLE and row["verified_steps"] < row["total_steps"]
    )
    return result


def recover(db):
    db._exec(
        "UPDATE screen_workflow_runs SET state=CASE WHEN verified_steps=total_steps "
        "THEN 'completed' ELSE 'stopped' END, finished_at=?, "
        "current_step=CASE WHEN verified_steps=total_steps THEN NULL ELSE current_step END, "
        "outcome=CASE WHEN verified_steps=total_steps THEN 'all steps verified' WHEN EXISTS "
        "(SELECT 1 FROM screen_workflow_events WHERE run_id=screen_workflow_runs.id "
        "AND step=current_step AND event='dispatch') AND (input_pending=1 OR "
        "(plan_hash IS NULL AND NOT EXISTS "
        "(SELECT 1 FROM screen_workflow_events WHERE run_id=screen_workflow_runs.id "
        "AND step=current_step AND event='verified'))) THEN 'server restarted, input outcome uncertain' "
        "ELSE 'server restarted' END WHERE state IN (?,?,?)",
        (time.time(), *ACTIVE),
    )


def event(run, kind, *, request_id=None, actor_id=None, attachment_id=None, outcome=None):
    sql = (
        "INSERT INTO screen_workflow_events(run_id,created_at,step,source,event,request_id,"
        "actor_user_id,actor_attachment_id,outcome,step_index) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)"
    )
    index = run.verified + 1 if run.step_id else None
    args = (
        run.id, time.time(), run.step_id, run.source, kind, request_id,
        actor_id, attachment_id, outcome, index
    )
    run.db._exec(sql, args)


def journal(run, kind, *, request_id=None):
    """Keep the dispatch marker and committed plan cursor atomic with their events."""
    index = run.verified + 1
    verified = index if kind == "verified" else run.verified
    next_step = run.plan[verified][0] if verified < len(run.plan) else None
    with run.db.lock, run.db.conn:
        outcome = None
        if kind == "dispatch":
            from .screen_workflow_evidence import StopWorkflow

            row = run.db.conn.execute(
                "SELECT total_steps, verified_steps, current_step FROM screen_workflow_runs WHERE id=?",
                (run.id,),
            ).fetchone()
            if (index > row[0] or row[1] != run.verified or row[2] != run.step_id
                    or run.plan[index - 1][0] != run.step_id):
                raise StopWorkflow("workflow dispatch does not match the resume cursor", "stopped")
            counts = run.db.conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT step_index), "
                "COUNT(CASE WHEN step_index=? THEN 1 END) FROM screen_workflow_events "
                "WHERE run_id=? AND event='dispatch'", (index, run.id)
            ).fetchone()
            used, distinct, step_used = counts
            retries = used - distinct
            allowance = min(row[0], MAX_RUN_RETRIES)
            if step_used:
                if not run.resuming:
                    raise StopWorkflow("workflow retry requires a resume", "stopped")
                if step_used >= MAX_STEP_DISPATCHES:
                    raise StopWorkflow("workflow per-step retry cap reached", "stopped")
                if retries >= allowance:
                    raise StopWorkflow("workflow run retry allowance exhausted", "stopped")
                outcome = f"retry; {allowance - retries - 1} run retries remaining"
            if used >= row[0] + allowance:
                raise StopWorkflow("workflow run action budget exhausted", "stopped")
        run.db.conn.execute(
            "UPDATE screen_workflow_runs SET verified_steps=?, current_step=?, input_pending=? WHERE id=?",
            (verified, next_step, int(kind == "dispatch"), run.id),
        )
        run.db.conn.execute(
            "INSERT INTO screen_workflow_events(run_id,created_at,step,step_index,source,event,"
            "request_id,outcome)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (run.id, time.time(), run.step_id, index, run.source, kind, request_id, outcome),
        )
    run.verified = verified
    run.intent = kind == "dispatch"
    if kind == "dispatch":
        run.resuming = False


def change(run, state, outcome=None):
    run.db._exec(
        "UPDATE screen_workflow_runs SET state=?, verified_steps=?, current_step=?, outcome=?, "
        "finished_at=? WHERE id=?",
        (state, run.verified, run.step_id, outcome, None if state in ACTIVE else time.time(), run.id),
    )


def resume_requested(run):
    principal = run.principal
    event(run, "resume_requested", actor_id=principal.user_id, attachment_id=principal.attachment_id)
    run.db._exec(
        "UPDATE screen_workflow_runs SET state='running', current_step=?, outcome=NULL, finished_at=NULL, "
        "resume_attachment_id=? WHERE id=?",
        (run.step_id, principal.attachment_id, run.id),
    )
