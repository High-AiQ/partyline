"""Persist content-free workflow events, idempotency and restart recovery."""

import hashlib
import hmac
import json
import time

from .auth_tokens import signing_secret

ACTIVE = ("running", "awaiting_confirmation", "stopping")
PUBLIC = ("id", "workflow", "revision", "state", "total_steps", "verified_steps", "current_step", "outcome")


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
    return result


def recover(db):
    db._exec(
        "UPDATE screen_workflow_runs SET state='stopped', finished_at=?, outcome=CASE WHEN EXISTS "
        "(SELECT 1 FROM screen_workflow_events WHERE run_id=screen_workflow_runs.id "
        "AND step=current_step AND event='dispatch') AND NOT EXISTS "
        "(SELECT 1 FROM screen_workflow_events WHERE run_id=screen_workflow_runs.id "
        "AND step=current_step AND event='verified') THEN 'server restarted, input outcome uncertain' "
        "ELSE 'server restarted' END WHERE state IN (?,?,?)",
        (time.time(), *ACTIVE),
    )


def event(run, kind, *, request_id=None, actor_id=None, outcome=None):
    run.db._exec(
        "INSERT INTO screen_workflow_events"
        "(run_id,created_at,step,source,event,request_id,actor_user_id,outcome) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (run.id, time.time(), run.step_id, run.source, kind, request_id, actor_id, outcome),
    )


def change(run, state, outcome=None):
    run.db._exec(
        "UPDATE screen_workflow_runs SET state=?, verified_steps=?, current_step=?, outcome=?, "
        "finished_at=? WHERE id=?",
        (state, run.verified, run.step_id, outcome, None if state in ACTIVE else time.time(), run.id),
    )
