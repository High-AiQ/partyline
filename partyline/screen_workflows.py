"""Manage screen workflow jobs and keep authorization tied to their starting line."""

import asyncio
import secrets
import time
import uuid
from contextlib import suppress
from dataclasses import replace

from fastapi import HTTPException

from . import screen_workflow_audit as audit
from .screen_file_input import resolve_files
from .screen_workflow_access import machine_can_see, machine_listing, machine_run_participant
from .screen_workflow_evidence import StopWorkflow, WindowScreen, authorized_window
from .screen_workflow_bundle import load_bundle
from .screen_workflow_events import WorkflowRunsChanged
from .screen_workflow_files import checkout
from .screen_workflow_resume import RecentInputs, plan_for, plan_hash, resume
from .screen_workflow_run import Run, configured_directory
from .screen_workflow_skills import SkillDirectory


class Workflows:
    def __init__(self, hub, *, screen=None, clock=None, timeout_at=asyncio.timeout_at):
        self.hub = hub
        self.db = hub.runtime.db
        self.screen = screen or WindowScreen(hub)
        self.clock = clock or (lambda: asyncio.get_running_loop().time())
        self.timeout_at = timeout_at
        self.runs = {}
        self.by_grant = {}
        self.tasks = set()
        self.skills = SkillDirectory(self)
        self.recent_inputs = RecentInputs()

    def placement(self, conv_id):
        line = self.db.get_conversation(conv_id)
        if line is None:
            raise HTTPException(404, "line not found")
        if line.get("archived_at"):
            raise HTTPException(409, "line is archived")
        if line.get("cwd"):
            return line, None
        # Older lines can have their own attachment placement only. Do not inherit a parent checkout.
        placements = [
            att
            for att in self.db.list_attachments(conv_id)
            if att.get("cwd") and att["status"] in ("starting", "running")
        ]
        if len({att["cwd"] for att in placements}) != 1:
            raise HTTPException(409, "assign an unambiguous working directory to this line")
        return line, placements[0]

    def directory(self, conv_id):
        return configured_directory(*self.placement(conv_id))

    async def checkout(self, conv_id):
        try:
            return await asyncio.to_thread(checkout, self.directory(conv_id))
        except (ValueError, OSError) as exc:
            raise HTTPException(409, "line workflow checkout unavailable") from exc

    async def revision(self, conv_id, name):
        directory = self.directory(conv_id)
        space = await self.checkout(conv_id)
        try:
            revision = await asyncio.to_thread(load_bundle, space, name)
        except FileNotFoundError as exc:
            raise HTTPException(404, "workflow not found") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        if directory != self.directory(conv_id):
            raise HTTPException(409, "line working directory changed")
        return revision

    def row(self, conv_id, run_id):
        return self.db._exec(
            "SELECT * FROM screen_workflow_runs WHERE id=? AND conv_id=?", (run_id, conv_id)
        ).fetchone()

    def get(self, principal, conv_id, run_id, *, grant_access=False):
        row = self.row(conv_id, run_id)
        if not row:
            raise HTTPException(404, "workflow run not found")
        if principal.kind == "machine":
            visible = (
                machine_can_see(self, principal, row) if grant_access
                else machine_run_participant(principal, row)
            )
            if not visible:
                raise HTTPException(404, "workflow run not found")
        if principal.kind == "user" and principal.user_id not in (row["owner_id"], row["actor_user_id"]):
            raise HTTPException(403, "run is available to its initiator and window owner")
        return row

    def status(self, principal, conv_id, run_id):
        return self.run_view(principal, self.get(principal, conv_id, run_id, grant_access=True))

    def run_view(self, principal, row):
        run_id = row["id"]
        result = audit.view(row)
        result["needs_parameters"] = result["resumable"] and (
            run_id not in self.recent_inputs.values
            or (principal.kind == "machine" and principal.attachment_id != row["attachment_id"])
        )
        run = self.runs.get(run_id)
        if run and principal.kind == "user" and principal.user_id == row["owner_id"]:
            if confirmation := run.confirmation_view():
                result["confirmation"] = confirmation
        return result

    def stop(self, principal, conv_id, run_id):
        self.get(principal, conv_id, run_id)
        if run := self.runs.get(run_id):
            run.stop("stopped by request", principal.user_id)
        return self.status(principal, conv_id, run_id)

    def decide(self, principal, conv_id, run_id, body):
        row = self.get(principal, conv_id, run_id)
        if principal.user_id != row["owner_id"]:
            raise HTTPException(403, "only the computer's owner can confirm an action")
        run = self.runs.get(run_id)
        if run is None:
            raise HTTPException(409, "run is no longer active")
        try:
            run.decide(body.token, body.allow, principal.user_id)
        except StopWorkflow as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True}

    def start_identity(self, principal, conv_id):
        if principal.kind == "user":
            return f"user:{principal.user_id}", None
        if principal.conv_id != conv_id:
            raise HTTPException(403, "start a workflow on your own line")
        att = self.db.get_attachment(principal.attachment_id)
        if not att or att["status"] not in ("starting", "running"):
            raise HTTPException(403, "starting attachment ended")
        return principal.attachment_id, att

    async def start(self, principal, conv_id, body):
        actor, att = self.start_identity(principal, conv_id)
        key = audit.fingerprint(self.db, body.client_key)
        fingerprint = audit.fingerprint(self.db, [conv_id, body.model_dump(exclude={"client_key"})])

        def original():
            existing = audit.prior_run(self.db, actor, key)
            if existing and not secrets.compare_digest(existing["request_hash"], fingerprint):
                raise HTTPException(409, "client key was already used for a different request")
            return audit.view(existing) if existing else None

        if existing := original():
            return existing
        revision = await self.revision(conv_id, body.workflow)
        if existing := original():
            return existing
        if not audit.approval(self.db, revision):
            raise HTTPException(403, "a person must approve this exact workflow revision")
        plan = plan_for(revision, body.parameters)
        run_id = str(uuid.uuid4())
        run, grant = self.prepare(principal, conv_id, att, run_id, body.window, plan, revision)
        self.validate_remaining(principal, run.grant_id, plan)
        self.db._exec(
            "INSERT INTO screen_workflow_runs(id,conv_id,attachment_id,actor,actor_user_id,owner_id,"
            "client_key_hash,request_hash,project,path,workflow,revision,grant_id,started_at,state,"
            "total_steps,plan_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                conv_id,
                actor,
                principal.name,
                principal.user_id,
                grant["owner_id"],
                key,
                fingerprint,
                revision.project,
                revision.path,
                body.workflow,
                revision.digest,
                body.window,
                time.time(),
                "running",
                len(plan),
                plan_hash(self.db, revision, body.parameters, plan),
            ),
        )
        return self.launch(run, body.parameters)

    def prepare(self, principal, conv_id, att, run_id, window, plan, revision):
        grant, device = authorized_window(self.hub, principal, window, conv_id)
        if window in self.by_grant:
            raise HTTPException(409, "a workflow is already running on this grant")
        activation = (self.directory(conv_id), *((att["runtime_owner"], att["api_token"]) if att else ()))
        runner = replace(principal, conv_id=conv_id) if principal.kind == "user" else principal
        run = Run(self, run_id, runner, conv_id, grant, device, activation, plan, revision)
        try:
            run.authorize()
            run.require_current()
        except StopWorkflow as exc:
            raise HTTPException(409, str(exc)) from exc
        return run, grant

    def validate_remaining(self, principal, grant_id, plan):
        if len(plan) > self.hub.window_grants.remaining_actions(grant_id):
            raise HTTPException(409, "window grant has too few remaining actions for the expanded plan")
        for _, step in plan:
            if step.inputs.files:
                resolve_files(self.hub, principal, step.inputs.files)

    def launch(self, run, parameters):
        self.recent_inputs.remember(run.id, parameters)
        self.runs[run.id] = run
        self.by_grant[run.grant_id] = run
        run.task = asyncio.create_task(run.execute())
        self.tasks.add(run.task)
        run.task.add_done_callback(self.tasks.discard)
        return audit.view(self.row(run.conv_id, run.id))

    async def resume(self, principal, conv_id, run_id, parameters):
        return await resume(self, principal, conv_id, run_id, parameters)

    async def push_changed(self, run):
        with suppress(TimeoutError):
            async with asyncio.timeout(2):
                event = WorkflowRunsChanged(conversation_id=run.conv_id)
                await self.hub.runtime.broadcast(run.conv_id, event)

    def list_runs(self, principal, conv_id):
        if principal.kind == "machine":
            clause, args = machine_listing(self, principal, conv_id)
        else:
            clause, args = "(owner_id=? OR actor_user_id=?)", (principal.user_id, principal.user_id)
        rows = self.db._exec(
            f"SELECT * FROM screen_workflow_runs WHERE conv_id=? AND {clause} "
            "ORDER BY finished_at IS NOT NULL, started_at DESC LIMIT 20",
            (conv_id, *args),
        ).fetchall()
        return [self.run_view(principal, row) for row in rows]

    def changed(self, grant_id):
        if run := self.by_grant.get(grant_id):
            run.changes.notify()

    def ended(self, grant_id):
        if run := self.by_grant.get(grant_id):
            run.stop("window grant ended")

    def interrupt(self, attachment_id):
        for run in list(self.runs.values()):
            if run.principal.attachment_id == attachment_id:
                run.stop("starting attachment interrupted")

    def release(self, run):
        self.runs.pop(run.id, None)
        self.by_grant.pop(run.grant_id, None)

    async def close(self):
        for run in list(self.runs.values()):
            run.stop("server stopped")
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.skills.close()
