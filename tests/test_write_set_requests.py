"""A line asks for write-set scope; only a person may approve or decline it."""

import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.adapters import ADAPTER_METADATA
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.reattach import ResumedAttachment
from partyline.runtime import ChatRuntime
from partyline.write_set_decisions import register_write_set_request_routes
from partyline.write_set_requests import resume_line_attachments
from partyline.write_set_routes import list_write_grants, write_set_router
from tests.test_server import FakeAdapter


class Recorder:
    def __init__(self, attachment, *, on_stop=None):
        self.att = attachment
        self.delivered = []
        self.stopped = False
        self._on_stop = on_stop

    async def deliver(self, messages):
        self.delivered.extend(messages)

    async def stop(self):
        self.stopped = True
        if self._on_stop is not None:
            await self._on_stop()


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class WriteSetRequestTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.resumed = []
        metadata = {**ADAPTER_METADATA, "fake": {"capabilities": {"resume": True}}}
        metadata_patch = patch("partyline.write_set_requests.ADAPTER_METADATA", metadata)
        metadata_patch.start()
        self.addCleanup(metadata_patch.stop)
        # These routes exercise detach/resume outcomes, not the production
        # three-second confirmation window for an already-missing adapter.
        timeout_patch = patch("partyline.line_process_routes.DETACH_CONFIRM_TIMEOUT", 0)
        timeout_patch.start()
        self.addCleanup(timeout_patch.stop)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(write_set_router(self.runtime))
        register_write_set_request_routes(app, self.runtime, self._resume)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line", captain_mode="orchestrator")
        # The line works in a real repository, so filings are grantable under
        # the 2.18 rule (a path must sit inside a protected repository root).
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo,
                       check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "root"], cwd=self.repo, check=True, capture_output=True)
        self.db.add_attachment("cap", "line", "astra", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='cap'")
        self.db.add_attachment("wrk", "line", "worker", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='wrk'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "cap")}
        self.worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "wrk")}
        self.target = os.path.join(self.repo, "shared")
        os.makedirs(self.target, exist_ok=True)

    async def _resume(self, att_id, pending=None):
        self.resumed.append(att_id)
        self.runtime.live[att_id] = FakeAdapter()
        return ResumedAttachment(FakeAdapter(), False)

    async def _resume_line(self, runtime, conv_id, resume):
        self.resumed.extend(["cap", "wrk"])
        return ["cap", "wrk"], []

    def file(self, headers, path=None, conv_id="line"):
        return self.client.post(
            f"/api/conversations/{conv_id}/write-set",
            json={"path": path or self.target},
            headers=headers)

    def audience_copies(self, att_id):
        return [m for m in self.db.list_messages("line")
                if m["audience_attachment_id"] == att_id]

    def public_notices(self, phrase):
        return [m for m in self.db.list_messages("line")
                if phrase in m["body"] and m["audience_attachment_id"] is None]

    def go_live(self, att_id):
        att = self.db.get_attachment(att_id)
        owner = att.get("runtime_owner") or f"owner-{att_id}"
        self.db._exec("UPDATE attachments SET runtime_owner=? WHERE id=?", (owner, att_id))
        att = self.db.get_attachment(att_id)

        async def on_stop():
            self.db.set_attachment_status(att_id, "exited", owner)

        recorder = Recorder(att, on_stop=on_stop)
        self.runtime.live[att_id] = recorder
        return recorder

    def test_missing_paths_are_refused_without_recording_or_creating_them(self):
        missing = os.path.join(self.target, "new", "skill")
        for headers in (self.worker, self.human):
            with self.subTest(headers="worker" if headers == self.worker else "human"):
                response = self.file(headers, missing)
                self.assertEqual(response.status_code, 400, response.text)
                detail = response.json()["detail"]
                self.assertIn(f"ancestor directory {os.path.realpath(self.target)} instead", detail)
                self.assertIn("ask a person to create the path first", detail)
                self.assertFalse(os.path.exists(os.path.dirname(missing)))
                self.assertEqual(list_write_grants(self.db, "line"), [])
                pending = self.client.get("/api/conversations/line/write-set/request",
                                          headers=self.human).json()
                self.assertIsNone(pending["request"])

    def test_existing_file_and_symlink_remain_grantable(self):
        target = os.path.join(self.target, "file")
        with open(target, "w") as stream:
            stream.write("existing")
        link = os.path.join(self.target, "link")
        os.symlink(target, link)
        for path in (target, link):
            response = self.file(self.human, path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn(path, [row["path"] for row in response.json()])

    def test_a_worker_files_a_request_a_stranger_cannot_and_the_line_hears_it(self):
        self.db.create_conversation("stranger", "Stranger", captain_mode="orchestrator")
        self.db.add_attachment("other", "stranger", "other", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='other'")
        stranger = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "other")}
        self.assertEqual(self.file(stranger).status_code, 403)
        filed = self.file(self.worker)
        self.assertEqual(filed.status_code, 200, filed.text)
        notice = self.db.list_messages("line")[-1]
        self.assertIn("asks to grant write-set scope", notice["body"])
        first_id = self.file(self.worker).json()["id"]
        merged = self.file(self.worker)
        self.assertEqual(merged.status_code, 200, merged.text)
        self.assertEqual(merged.json()["id"], first_id)

    def test_only_a_person_decides_and_approval_grants_and_resumes_the_line(self):
        request_id = self.file(self.worker).json()["id"]
        self.assertEqual(self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.worker).status_code, 403)
        cap = self.go_live("cap")
        wrk = self.go_live("wrk")
        approved = self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(cap.stopped)
        self.assertTrue(wrk.stopped)
        self.assertEqual(sorted(self.resumed), ["cap", "wrk"])
        grants = list_write_grants(self.db, "line")
        self.assertEqual([row["path"] for row in grants], [self.target])
        self.assertEqual(approved.json()["granted"][0]["path"], self.target)
        self.assertEqual(self.client.get(
            "/api/conversations/line/write-set/request", headers=self.human).json(),
                         {"request": None})

    def test_resume_line_detach_then_resumes_every_live_attachment(self):
        cap = self.go_live("cap")
        wrk = self.go_live("wrk")
        resumed, failed = asyncio.run(
            resume_line_attachments(self.runtime, "line", self._resume))
        self.assertEqual(resumed, ["cap", "wrk"])
        self.assertEqual(failed, [])
        self.assertTrue(cap.stopped)
        self.assertTrue(wrk.stopped)

    def test_write_set_resume_preserves_queued_order_during_a_wake(self):
        from partyline.mention_relay import post_private
        from partyline.resume_continuation import drain
        self.go_live("cap")
        self.go_live("wrk")
        old = self.db.add_message("line", "person", "human", "@worker older")
        owner = self.db.get_attachment("wrk")["runtime_owner"]
        self.db.set_last_seen("wrk", old["id"], owner)
        staged, adapters = {}, {}

        async def run():
            await self.db.queue_delivery_ids("wrk", [old["id"]], owner)
            self.db.add_message("line", "person", "human", "@worker newer")
            async def resume(ident, pending):
                att = self.db.get_attachment(ident)
                adapter = FakeAdapter(att=att)
                adapters[ident] = adapter
                staged[ident] = pending
                self.runtime._record_unproved(att, adapter, pending)
                self.db.set_attachment_status(ident, "running", att["runtime_owner"])
                self.runtime.live[ident] = adapter
                if ident == "wrk":
                    await post_private(self.runtime, "line", "captain", "agent", "wake",
                                       audience=ident)
                return ResumedAttachment(adapter, True)
            await resume_line_attachments(self.runtime, "line", resume)
            await drain()

        asyncio.run(run())
        bodies = [m["body"] for batch in [staged["wrk"], *adapters["wrk"].deliveries]
                  for m in batch]
        self.assertEqual(bodies.count("@worker older"), 1)
        self.assertLess(bodies.index("@worker older"), bodies.index("@worker newer"))
        self.assertEqual(bodies.count("wake"), 1)
        self.assertEqual(self.db.queued_delivery_ids("wrk"), [])

    def test_approval_surfaces_a_resume_failure_and_still_resumes_the_rest(self):
        request_id = self.file(self.worker).json()["id"]
        self.go_live("cap")
        self.go_live("wrk")

        async def resume_with_backlog(runtime, att_id, resume, **kwargs):
            if att_id == "wrk":
                raise RuntimeError("resume broke")
            self.resumed.append(att_id)
            self.runtime.live[att_id] = FakeAdapter()
            return ResumedAttachment(FakeAdapter(), False)

        with patch("partyline.write_set_requests.resume_with_backlog", resume_with_backlog):
            approved = self.client.post(
                f"/api/conversations/line/write-set/request/{request_id}/approve",
                headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(self.resumed, ["cap"])
        notice = self.public_notices("approved by @person")[0]["body"]
        self.assertIn("could not resume @worker", notice)
        copies = self.audience_copies("wrk")
        self.assertIn("could not resume @worker", copies[0]["body"])

    def test_non_resumable_live_adapter_keeps_request_pending_without_grant_or_detach(self):
        request_id = self.file(self.worker).json()["id"]
        self.db.set_attachment_status("cap", "exited", None)
        self.db._exec("UPDATE attachments SET adapter='raw' WHERE id='wrk'")
        worker = self.go_live("wrk")
        metadata = {
            "fake": {"capabilities": {"resume": True}},
            "raw": {"capabilities": {"resume": False}},
        }
        with patch("partyline.write_set_requests.ADAPTER_METADATA", metadata):
            response = self.client.post(
                f"/api/conversations/line/write-set/request/{request_id}/approve",
                headers=self.human,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("@worker (raw)", response.json()["detail"])
        self.assertFalse(worker.stopped)
        self.assertEqual(list_write_grants(self.db, "line"), [])
        pending = self.client.get(
            "/api/conversations/line/write-set/request", headers=self.human)
        self.assertEqual(pending.json()["request"]["id"], request_id)

    def test_machine_filed_bad_path_is_400(self):
        response = self.file(self.worker, path="relative/path")
        self.assertEqual(response.status_code, 400, response.text)

    def test_approve_and_decline_of_a_stale_request_id_is_404(self):
        request_id = self.file(self.worker).json()["id"]
        approved = self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.human).status_code, 404)
        self.db.add_attachment("next-worker", "line", "next", "fake", ["fake"], self.repo)
        next_worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "next-worker")}
        next_path = os.path.join(self.repo, "next")
        os.makedirs(next_path)
        filed = self.file(next_worker, next_path)
        self.assertEqual(filed.status_code, 200, filed.text)
        request_id = filed.json()["id"]
        self.assertEqual(self.client.delete(
            f"/api/conversations/line/write-set/request/{request_id}",
            headers=self.human).status_code, 200)
        self.assertEqual(self.client.delete(
            f"/api/conversations/line/write-set/request/{request_id}",
            headers=self.human).status_code, 404)

    def test_approval_privately_rings_the_requester_once(self):
        request_id = self.file(self.worker).json()["id"]
        wrk = self.go_live("wrk")
        self.go_live("cap")
        with patch("partyline.write_set_decisions.resume_line_attachments", self._resume_line):
            approved = self.client.post(
                f"/api/conversations/line/write-set/request/{request_id}/approve",
                headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)

        copies = self.audience_copies("wrk")
        self.assertEqual(len(copies), 1)
        self.assertIn("approved by @person", copies[0]["body"])
        self.assertIsNone(copies[0]["source_attachment_id"])
        backlog_ids = [m["id"] for m in self.db.messages_after("line", 0, "worker", "wrk")]
        self.assertIn(copies[0]["id"], backlog_ids)

        ringed = [m for m in wrk.delivered if m.get("audience_attachment_id") == "wrk"]
        self.assertEqual(len(ringed), 1)
        self.assertEqual(len(self.public_notices("approved by @person")), 1)

    def test_decline_privately_rings_the_requester_once(self):
        request_id = self.file(self.worker).json()["id"]
        wrk = self.go_live("wrk")
        declined = self.client.delete(
            f"/api/conversations/line/write-set/request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200, declined.text)
        copies = self.audience_copies("wrk")
        self.assertEqual(len(copies), 1)
        self.assertIn("declined by @person", copies[0]["body"])
        ringed = [m for m in wrk.delivered if m.get("audience_attachment_id") == "wrk"]
        self.assertEqual(len(ringed), 1)

    def test_outcome_rings_the_filing_attachment_not_an_exited_namesake(self):
        self.db.add_attachment("wrk-old", "line", "worker", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='wrk-old'")
        request_id = self.file(self.worker).json()["id"]
        wrk = self.go_live("wrk")
        declined = self.client.delete(
            f"/api/conversations/line/write-set/request/{request_id}", headers=self.human)
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(self.audience_copies("wrk-old"), [])
        self.assertEqual(len(self.audience_copies("wrk")), 1)
        ringed = [m for m in wrk.delivered if m.get("audience_attachment_id") == "wrk"]
        self.assertEqual(len(ringed), 1)

    def file_on_child(self):
        self.db.create_conversation("child", "Child", captain_mode="orchestrator")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='child'")
        return self.client.post(
            "/api/conversations/child/write-set",
            json={"path": self.target},
            headers=self.captain).json()["id"]

    def test_cross_line_approval_rings_the_requester_on_its_home_line(self):
        request_id = self.file_on_child()
        cap = self.go_live("cap")
        with patch("partyline.write_set_decisions.resume_line_attachments", self._resume_line):
            approved = self.client.post(
                f"/api/conversations/child/write-set/request/{request_id}/approve",
                headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual([m for m in self.db.list_messages("child")
                          if m["audience_attachment_id"]], [])
        self.assertEqual(len(self.audience_copies("cap")), 1)
        ringed = [m for m in cap.delivered if m.get("audience_attachment_id") == "cap"]
        self.assertEqual(len(ringed), 1)

    def _subtree_repo_with_commit(self):
        """A second repository, with a line of the subtree working in it."""
        repo = os.path.join(self.directory.name, "other")
        os.makedirs(repo)
        _git("init", "-q", "-b", "main", cwd=repo)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=repo)
        port = os.path.join(repo, ".partyline-worktrees", "port")
        os.makedirs(port)
        self.db.create_conversation("port", "Port", captain_mode="orchestrator")
        self.db._exec("UPDATE conversations SET parent_id='line', cwd=? WHERE id='port'",
                      (port,))
        with open(os.path.join(repo, "f.txt"), "w") as fh:
            fh.write("portable work\n")
        _git("add", "-A", cwd=repo)
        _identity("commit", "-q", "-m", "portable work", cwd=repo)
        sha = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
        os.makedirs(os.path.join(repo, ".review", sha))
        return repo, sha

    def test_a_request_can_name_a_review_worktree_by_repository_and_sha(self):
        repo, sha = self._subtree_repo_with_commit()
        made = self.client.post("/api/conversations/line/write-set",
                                json={"repository": repo, "sha": sha},
                                headers=self.worker)
        self.assertEqual(made.status_code, 200, made.text)
        pending = self.client.get("/api/conversations/line/write-set/request",
                                  headers=self.captain).json()["request"]
        self.assertEqual(pending["path"], os.path.join(repo, ".review", sha))

    def test_multi_path_request_merges_and_approval_returns_each_grant(self):
        second = os.path.join(self.target, "second")
        os.makedirs(second)
        filed = self.client.post("/api/conversations/line/write-set",
                                 json={"paths": [self.target]}, headers=self.worker)
        self.assertEqual(filed.status_code, 200, filed.text)
        first_id = filed.json()["id"]
        merged = self.client.post("/api/conversations/line/write-set",
                                  json={"paths": [second]}, headers=self.worker)
        self.assertEqual(merged.status_code, 200, merged.text)
        self.assertEqual(merged.json()["id"], first_id)
        request = self.client.get("/api/conversations/line/write-set/request",
                                  headers=self.human).json()["request"]
        self.assertEqual(request["paths"], [self.target, second])
        with patch("partyline.write_set_decisions.resume_line_attachments", self._resume_line):
            approved = self.client.post(
                f"/api/conversations/line/write-set/request/{first_id}/approve",
                headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual([row["path"] for row in approved.json()["granted"]],
                         [self.target, second])
        self.assertEqual(self.resumed, ["cap", "wrk"])

    def test_six_paths_cost_one_approval_filed_together_or_one_by_one(self):
        paths = []
        for index in range(6):
            path = os.path.join(self.target, f"dir{index}")
            os.makedirs(path)
            paths.append(path)
        together = self.client.post("/api/conversations/line/write-set",
                                    json={"paths": paths}, headers=self.worker)
        self.assertEqual(together.status_code, 200, together.text)
        self.assertEqual(together.json()["paths"], paths)
        # Filing them one at a time merges into the same pending request, never a 409.
        for path in paths:
            again = self.client.post("/api/conversations/line/write-set",
                                     json={"path": path}, headers=self.worker)
            self.assertEqual(again.status_code, 200, again.text)
            self.assertEqual(again.json()["id"], together.json()["id"])
        rows = self.db._exec("SELECT id FROM conversation_write_grant_requests").fetchall()
        self.assertEqual(len(rows), 1)
        with patch("partyline.write_set_decisions.resume_line_attachments", self._resume_line):
            approved = self.client.post(
                f"/api/conversations/line/write-set/request/{together.json()['id']}/approve",
                headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual([row["path"] for row in approved.json()["granted"]], paths)
        self.assertEqual(self.resumed, ["cap", "wrk"])  # one resume, not six

    def test_refusals_tell_the_worker_to_file_every_path_at_once(self):
        bad = self.client.post("/api/conversations/line/write-set",
                               json={"paths": ["relative"]}, headers=self.worker)
        self.assertEqual(bad.status_code, 400)
        self.assertIn("every path you will need in the same request", bad.text)
        self.db.create_conversation("stranger", "Stranger", captain_mode="orchestrator")
        denied = self.client.post("/api/conversations/stranger/write-set",
                                  json={"paths": [self.target]}, headers=self.worker)
        self.assertEqual(denied.status_code, 403)
        self.assertIn("every path you will need in one request", denied.text)

    def test_merged_request_uses_the_retained_requester_for_decider_eligibility(self):
        self.db.create_conversation("child", "Child", captain_mode="orchestrator")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='child'")
        self.db.add_attachment("child-wrk", "child", "childworker", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='child-wrk'")
        child_worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "child-wrk")}
        second = os.path.join(self.target, "second")
        os.makedirs(second)

        # A captain's request stays person-decided when a worker merges into it.
        captain_first = self.client.post(
            "/api/conversations/child/write-set", json={"path": self.target},
            headers=self.captain)
        self.assertEqual(captain_first.status_code, 200, captain_first.text)
        request_id = captain_first.json()["id"]
        merged = self.client.post(
            "/api/conversations/child/write-set", json={"path": second},
            headers=child_worker)
        self.assertEqual(merged.status_code, 200, merged.text)
        self.assertTrue(merged.json()["human_only"])
        self.assertEqual(self.client.post(
            f"/api/conversations/child/write-set/request/{request_id}/approve",
            headers=self.captain).status_code, 403)
        self.client.post(f"/api/conversations/child/write-set/request/{request_id}/withdraw",
                         headers=self.captain)

        # A worker's request stays captain-decided when the captain merges.
        worker_first = self.client.post(
            "/api/conversations/child/write-set", json={"path": self.target},
            headers=child_worker)
        self.assertEqual(worker_first.status_code, 200, worker_first.text)
        request_id = worker_first.json()["id"]
        merged = self.client.post(
            "/api/conversations/child/write-set", json={"path": second},
            headers=self.captain)
        self.assertEqual(merged.status_code, 200, merged.text)
        self.assertFalse(merged.json()["human_only"])
        self.assertEqual(merged.json()["decider_name"], "astra")
        with patch("partyline.write_set_decisions.resume_line_attachments", self._resume_line):
            approved = self.client.post(
                f"/api/conversations/child/write-set/request/{request_id}/approve",
                headers=self.captain)
        self.assertEqual(approved.status_code, 200, approved.text)

    def test_request_for_a_granted_parent_is_reported_without_opening_banner(self):
        self.grant_on("line", self.target)
        child = os.path.join(self.target, "child")
        os.makedirs(child)
        response = self.file(self.worker, child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["already_granted"], [child])
        self.assertIn("re-attach or restart", response.json()["message"])
        self.assertIsNone(self.client.get("/api/conversations/line/write-set/request",
                                         headers=self.human).json()["request"])

    def test_mixed_path_request_names_paths_already_granted(self):
        self.grant_on("line", self.target)
        new_path = os.path.join(self.repo, "new")
        os.makedirs(new_path)
        response = self.client.post("/api/conversations/line/write-set",
                                    json={"paths": [self.target, new_path]}, headers=self.worker)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["already_granted"], [self.target])
        self.assertEqual(response.json()["paths"], [new_path])

    def test_request_outside_root_captains_grants_is_person_only_from_filing(self):
        self._seed_subtree()
        other_repo, _sha = self._subtree_repo_with_commit()
        path = os.path.join(other_repo, ".review")
        filed = self.file_on_kid(path)
        self.assertEqual(filed.status_code, 200, filed.text)
        self.assertTrue(filed.json()["human_only"])
        root_notice = self.db.list_messages("line")[-1]["body"]
        self.assertIn("a person decides", root_notice)
        self.assertNotIn("@astra", root_notice)
        self.assertNotIn("approve:", root_notice)
        self.assertIsNone(self.db._exec(
            "SELECT wait_reason FROM task_reviews WHERE conv_id='kid'").fetchone())

    def test_nearest_eligible_ancestor_captain_is_named_for_the_decision(self):
        self._seed_subtree()
        self.db.create_conversation("mid", "Mid", captain_mode="orchestrator")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='mid'")
        self.db._exec("UPDATE conversations SET parent_id='mid' WHERE id='kid'")
        self.db.add_attachment("mid-cap", "mid", "midcaptain", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='mid-cap'")
        mid_recorder = self.go_live("mid-cap")
        mid_captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "mid-cap")}
        other_repo, _sha = self._subtree_repo_with_commit()
        self.grant_on("mid", other_repo)
        path = os.path.join(other_repo, ".review")
        filed = self.file_on_kid(path)
        self.assertEqual(filed.status_code, 200, filed.text)
        self.assertFalse(filed.json()["human_only"])
        self.assertEqual(filed.json()["decider_name"], "midcaptain")
        root_notice = self.db.list_messages("line")[-1]["body"]
        self.assertIn("@midcaptain", root_notice)
        self.assertNotIn("@astra", root_notice)
        mid_notices = [m for m in self.db.list_messages("mid")
                       if "write-set decision needed" in m["body"]]
        self.assertEqual(len(mid_notices), 1)
        self.assertIn("@midcaptain", mid_notices[0]["body"])
        self.assertEqual(len([m for m in mid_recorder.delivered if "write-set decision needed"
                              in m["body"]]), 1)
        approved = self.client.post(
            f"/api/conversations/kid/write-set/request/{filed.json()['id']}/approve",
            headers=mid_captain)
        self.assertEqual(approved.status_code, 200, approved.text)

    def test_invalid_path_list_refuses_every_named_path_with_a_fix(self):
        invalid = os.path.join(self.target, "missing")
        response = self.client.post("/api/conversations/line/write-set",
                                    json={"paths": [self.target, invalid]}, headers=self.worker)
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertIn("none of these paths were filed", detail)
        self.assertIn(invalid, detail)
        self.assertIn("request the nearest existing ancestor", detail)

    def test_deciding_write_request_clears_task_wait_reason(self):
        self._seed_subtree()
        self.db._exec(
            "INSERT INTO task_reviews(conv_id,root_id,implementer_id,implementer_preset,policy,"
            "created_at,wait_reason,wait_until) VALUES('kid','line','kid-worker','fake','captain',"
            "0,'Waiting for write scope',9999999999)")
        filed = self.file_on_kid()
        self.assertEqual(filed.status_code, 200, filed.text)
        request_id = filed.json()["id"]
        approved = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve", headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        row = self.db._exec("SELECT wait_reason,wait_until FROM task_reviews WHERE conv_id='kid'")
        self.assertEqual(dict(row.fetchone()), {"wait_reason": "", "wait_until": None})

    def test_a_person_can_grant_a_review_checkout_by_repository_and_sha(self):
        # the person approving should not type the path either: the pair
        # resolves to the review checkout before the absolute-path check
        repo, sha = self._subtree_repo_with_commit()
        made = self.client.post("/api/conversations/line/write-set",
                                json={"repository": repo, "sha": sha},
                                headers=self.human)
        self.assertEqual(made.status_code, 200, made.text)
        grants = list_write_grants(self.db, "line")
        self.assertEqual([g["path"] for g in grants], [os.path.join(repo, ".review", sha)])
        self.assertEqual(grants[0]["granted_by"], "person")

    def test_review_worktree_grant_names_are_refused_outside_their_shape(self):
        repo, sha = self._subtree_repo_with_commit()
        stranger = os.path.join(self.directory.name, "stranger")
        os.makedirs(stranger)
        cases = [
            ({"path": self.target, "repository": repo, "sha": sha}, 422, "not both"),
            ({}, 422, "name the path"),
            ({"repository": repo}, 422, "both the repository and the sha"),
            ({"sha": sha}, 422, "both the repository and the sha"),
            ({"repository": stranger, "sha": sha}, 403, "subtree"),
            ({"repository": repo, "sha": "deadbeef"}, 400, "no commit deadbeef"),
        ]
        for body, status, phrase in cases:
            made = self.client.post("/api/conversations/line/write-set",
                                    json=body, headers=self.worker)
            self.assertEqual(made.status_code, status, f"{body}: {made.text}")
            self.assertIn(phrase, made.json()["detail"])
        self.assertEqual(self.client.get("/api/conversations/line/write-set/request",
                                         headers=self.captain).json()["request"], None)

    # -- 5.9: an ancestor captain decides inside its own grants -----------------

    def _seed_subtree(self):
        """line (captain) -> kid (worker files there); a shared dir on disk."""
        self.db.create_conversation("kid", "Kid", captain_mode="orchestrator")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='kid'")
        self.db.add_attachment("kid-worker", "kid", "digger", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='kid-worker'")
        self.kid_worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "kid-worker")}
        shared = os.path.join(self.repo, "shared")
        os.makedirs(shared, exist_ok=True)
        return shared

    def grant_on(self, conv_id, path):
        self.db._exec(
            "INSERT OR REPLACE INTO conversation_write_grants"
            "(conv_id,path,granted_by,granted_at) VALUES(?,?, 'greg', 0)",
            (conv_id, path))

    def file_on_kid(self, path=None):
        response = self.client.post("/api/conversations/kid/write-set",
                                    json={"path": path or self.target},
                                    headers=self.kid_worker)
        self.db.set_attachment_status("kid-worker", "detached", None)
        return response

    def test_an_ancestor_captain_approves_inside_its_own_grant(self):
        shared = self._seed_subtree()
        self.grant_on("line", shared)
        inner = os.path.join(shared, "inner", "file.txt")
        os.makedirs(os.path.dirname(inner))
        Path(inner).touch()
        self.file_on_kid(inner)
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        approved = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve",
            headers=self.captain)
        self.assertEqual(approved.status_code, 200, approved.text)
        grants = [g["path"] for g in list_write_grants(self.db, "kid")]
        self.assertIn(os.path.realpath(inner), grants)

    def _approve_on_kid(self, path, *, insert=False):
        self.db._exec("UPDATE attachments SET status='running' WHERE id='kid-worker'")
        if insert:  # a path outside every protected root cannot be filed
            self.db._exec(
                "INSERT INTO conversation_write_grant_requests"
                "(conv_id,id,path,requester,requester_attachment_id,created_at) "
                "VALUES('kid','r1',?,'digger','kid-worker',0)", (path,))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Path(path).touch()
            self.file_on_kid(path)
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        return self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve",
            headers=self.captain)

    def test_a_captain_approves_inside_its_own_checkout_without_a_grant_row(self):
        self._seed_subtree()
        approved = self._approve_on_kid(os.path.join(self.repo, "shared", "new.txt"))
        self.assertEqual(approved.status_code, 200, approved.text)

    def test_a_captain_approves_inside_its_review_and_scratch_directories(self):
        self._seed_subtree()
        for name in (".review", ".scratch"):
            os.makedirs(os.path.join(self.repo, name), exist_ok=True)
            approved = self._approve_on_kid(os.path.join(self.repo, name, "x" * 40))
            self.assertEqual(approved.status_code, 200, approved.text)

    def test_a_captain_still_gets_403_outside_its_grants_and_write_set(self):
        self._seed_subtree()
        outside = os.path.join(self.directory.name, "elsewhere")
        os.makedirs(outside)
        refused = self._approve_on_kid(os.path.join(outside, "file.txt"), insert=True)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("outside your grants", refused.json()["detail"])

    def test_the_decision_check_creates_no_directories(self):
        self._seed_subtree()
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".review")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".scratch")))
        self._approve_on_kid(os.path.join(self.repo, "shared", "new.txt"))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".review")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".scratch")))

    def test_docker_access_is_a_grant_only_a_person_approves(self):
        self._seed_subtree()
        self.grant_on("line", "/run/docker.sock")  # the captain even holds it
        filed = self.file_on_kid("/var/run/docker.sock")  # through the symlinked parent
        self.assertEqual(filed.status_code, 200, filed.text)
        request_id = filed.json()["id"]
        text = " ".join(m["body"] for m in self.db.list_messages("kid"))
        self.assertIn("outside every attachment's memory budget", text)
        refused = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve",
            headers=self.captain)
        self.assertEqual(refused.status_code, 403)
        self.assertIn("root-equivalent", refused.json()["detail"])
        approved = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve",
            headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual([g["path"] for g in list_write_grants(self.db, "kid")],
                         ["/var/run/docker.sock"])

    def test_approving_docker_access_resumes_every_live_process_on_every_line(self):
        self._seed_subtree()
        self.db.add_attachment("kid-live", "kid", "kidlive", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='kid-live'")
        request_id = self.file(self.worker, "/run/docker.sock").json()["id"]
        for att_id in ("cap", "wrk", "kid-live"):
            self.go_live(att_id)
        approved = self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(sorted(self.resumed), ["cap", "kid-live", "wrk"])
        self.assertTrue(self.public_notices(
            "every live process is resumed so other lines cannot reach the relay"))

    def test_a_person_chooses_unrestricted_docker_access_and_it_says_so(self):
        request_id = self.file(self.worker, "/run/docker.sock").json()["id"]
        self.go_live("cap")
        approved = self.client.post(
            f"/api/conversations/line/write-set/request/{request_id}/approve",
            json={"docker_mode": "unrestricted"}, headers=self.human)
        self.assertEqual(approved.status_code, 200, approved.text)
        grant = list_write_grants(self.db, "line")[0]
        self.assertEqual(grant["docker_mode"], "unrestricted")
        self.assertTrue(self.public_notices("UNRESTRICTED docker access (root-equivalent"))

    def test_docker_access_is_managed_by_default_when_approved_or_granted(self):
        self._seed_subtree()
        request_id = self.file(self.worker, "/run/docker.sock").json()["id"]
        self.client.post(f"/api/conversations/line/write-set/request/{request_id}/approve",
                         headers=self.human)
        self.assertEqual(list_write_grants(self.db, "line")[0]["docker_mode"], "managed")
        self.assertTrue(self.public_notices("managed docker access"))
        granted = self.client.post("/api/conversations/kid/write-set",
                                   json={"path": "/run/docker.sock"}, headers=self.human)
        self.assertEqual(granted.status_code, 200, granted.text)
        self.assertEqual(granted.json()[0]["docker_mode"], "managed")
        again = self.client.post("/api/conversations/kid/write-set",
                                 json={"path": "/run/docker.sock", "docker_mode": "unrestricted"},
                                 headers=self.human)
        self.assertEqual(again.json()[0]["docker_mode"], "unrestricted")

    def test_a_process_cannot_choose_a_docker_mode(self):
        refused = self.client.post("/api/conversations/line/write-set",
                                   json={"path": "/run/docker.sock", "docker_mode": "unrestricted"},
                                   headers=self.worker)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(list_write_grants(self.db, "line"), [])

    def test_a_non_ancestor_captain_gets_403_even_with_a_covering_grant(self):
        # the earlier version passed only because the other line held no
        # grant: give the non-ancestor line one covering the path and assert
        # 403 anyway
        self._seed_subtree()
        other = os.path.join(self.repo, "other")
        os.makedirs(other, exist_ok=True)
        self.grant_on("other", other)
        self.file_on_kid()
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        self.db.add_attachment("other-lead", "other", "mo", "raw", ["raw"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET is_lead=1, status='running' WHERE id='other-lead'")
        other_captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "other-lead")}
        refused = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve",
            headers=other_captain)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("outside your grants", refused.json()["detail"])

    def test_a_worker_on_the_ancestor_line_gets_403(self):
        # a grant and a non-lead attachment on the ancestor line: still
        # refused, because the deciding role is the captain's, not any
        # process's
        self._seed_subtree()
        self.grant_on("line", self.target)
        self.db.add_attachment("line-worker", "line", "moo", "raw", ["raw"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET status='running' WHERE id='line-worker'")
        worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "line-worker")}
        self.file_on_kid()
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        refused = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve",
            headers=worker)
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_the_requester_cannot_approve_its_own_request(self):
        shared = self._seed_subtree()
        self.grant_on("line", shared)
        self.db.add_attachment("kid-lead", "kid", "nix", "raw", ["raw"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET is_lead=1, status='running' WHERE id='kid-lead'")
        kid_lead = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "kid-lead")}
        os.makedirs(os.path.join(shared, "inner"))
        made = self.client.post("/api/conversations/kid/write-set",
                                json={"path": os.path.join(shared, "inner")},
                                headers=kid_lead)
        self.assertEqual(made.status_code, 200, made.text)
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        refused = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve",
            headers=kid_lead)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("outside your grants", refused.json()["detail"])

    def test_a_captain_two_levels_up_can_approve_inside_its_grant(self):
        # mid sits between line and the filer: the line's captain is two
        # strict-ancestor levels above the request, and still decides it
        self.db.create_conversation("mid", "Mid", captain_mode="orchestrator")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='mid'")
        self.db.add_attachment("mid-worker", "mid", "leafy", "fake", ["fake"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET status='running' WHERE id='mid-worker'")
        mid_worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "mid-worker")}
        other = os.path.join(self.repo, "other")
        os.makedirs(other, exist_ok=True)
        # the captain's home line holds the grant; the request is on mid
        self.grant_on("line", other)
        os.makedirs(os.path.join(other, "inner"))
        self.client.post("/api/conversations/mid/write-set",
                         json={"path": os.path.join(other, "inner")},
                         headers=mid_worker)
        self.db.set_attachment_status("mid-worker", "detached", None)
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        approved = self.client.post(
            f"/api/conversations/mid/write-set/request/{request_id}/approve",
            headers=self.captain)
        self.assertEqual(approved.status_code, 200, approved.text)
        grants = [g["path"] for g in list_write_grants(self.db, "mid")]
        self.assertIn(os.path.realpath(os.path.join(other, "inner")), grants)

    # -- 5.8: decline with a reason, and withdraw -------------------------------

    def test_deny_posts_the_reason_and_rings_the_requester(self):
        self._seed_subtree()
        self.file_on_kid()
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        denied = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/deny",
            json={"reason": "the budget is spent"}, headers=self.human)
        self.assertEqual(denied.status_code, 200, denied.text)
        notices = [m["body"] for m in self.db.list_messages("kid")
                   if "declined by @person" in m["body"]
                   and m["audience_attachment_id"] is None]
        self.assertEqual(len(notices), 1)
        self.assertIn("the budget is spent", notices[0])
        self.assertEqual(
            self.db._exec("SELECT COUNT(*) AS n FROM conversation_write_grant_requests"
                          ).fetchone()["n"], 0)

    def test_the_requester_can_withdraw_but_a_stranger_cannot(self):
        self._seed_subtree()
        self.file_on_kid()
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        self.db.add_attachment("stranger", "kid", "moo", "raw", ["raw"], "/tmp")
        stranger = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "stranger")}
        refused = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/withdraw",
            headers=stranger)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.db.set_attachment_status("kid-worker", "running", None)
        withdrawn = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/withdraw",
            headers=self.kid_worker)
        self.assertEqual(withdrawn.status_code, 200, withdrawn.text)
        self.assertEqual(
            self.db._exec("SELECT COUNT(*) AS n FROM conversation_write_grant_requests"
                          ).fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()
