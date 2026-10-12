"""A line asks for write-set scope; only a person may approve or decline it."""

import asyncio
import os
import subprocess
import tempfile
import unittest
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
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(write_set_router(self.runtime))
        register_write_set_request_routes(app, self.runtime, self._resume)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line")
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

    def test_a_worker_files_a_request_a_stranger_cannot_and_the_line_hears_it(self):
        self.db.create_conversation("stranger", "Stranger")
        self.db.add_attachment("other", "stranger", "other", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='other'")
        stranger = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "other")}
        self.assertEqual(self.file(stranger).status_code, 403)
        filed = self.file(self.worker)
        self.assertEqual(filed.status_code, 200, filed.text)
        notice = self.db.list_messages("line")[-1]
        self.assertIn("asks a person to grant write-set scope", notice["body"])
        self.assertEqual(self.file(self.worker).status_code, 409)

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
        request_id = self.file(self.worker).json()["id"]
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
        self.db.create_conversation("child", "Child")
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
        self.db.create_conversation("port", "Port")
        self.db._exec("UPDATE conversations SET parent_id='line', cwd=? WHERE id='port'",
                      (port,))
        with open(os.path.join(repo, "f.txt"), "w") as fh:
            fh.write("portable work\n")
        _git("add", "-A", cwd=repo)
        _identity("commit", "-q", "-m", "portable work", cwd=repo)
        return repo, _git("rev-parse", "HEAD", cwd=repo).stdout.strip()

    def test_a_request_can_name_a_review_worktree_by_repository_and_sha(self):
        repo, sha = self._subtree_repo_with_commit()
        made = self.client.post("/api/conversations/line/write-set",
                                json={"repository": repo, "sha": sha},
                                headers=self.worker)
        self.assertEqual(made.status_code, 200, made.text)
        pending = self.client.get("/api/conversations/line/write-set/request",
                                  headers=self.captain).json()["request"]
        self.assertEqual(pending["path"], os.path.join(repo, ".review", sha))

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
        self.db.create_conversation("kid", "Kid")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='kid'")
        self.db.add_attachment("kid-worker", "kid", "digger", "raw", ["raw"], "/tmp")
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='kid-worker'")
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
        return self.client.post("/api/conversations/kid/write-set",
                                json={"path": path or self.target},
                                headers=self.kid_worker)

    def test_an_ancestor_captain_approves_inside_its_own_grant(self):
        shared = self._seed_subtree()
        self.grant_on("line", shared)
        inner = os.path.join(shared, "inner", "file.txt")
        self.file_on_kid(inner)
        request_id = self.db._exec(
            "SELECT id FROM conversation_write_grant_requests").fetchone()["id"]
        approved = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/approve",
            headers=self.captain)
        self.assertEqual(approved.status_code, 200, approved.text)
        grants = [g["path"] for g in list_write_grants(self.db, "kid")]
        self.assertIn(os.path.realpath(inner), grants)

    def test_docker_access_is_a_grant_only_a_person_approves(self):
        self._seed_subtree()
        self.grant_on("line", "/run/docker.sock")  # the captain even holds it
        filed = self.file_on_kid("/var/run/docker.sock")  # through the symlinked parent
        self.assertEqual(filed.status_code, 200, filed.text)
        request_id = filed.json()["id"]
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
        self.db.create_conversation("mid", "Mid")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='mid'")
        self.db.add_attachment("mid-worker", "mid", "leafy", "raw", ["raw"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET status='detached' WHERE id='mid-worker'")
        mid_worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "mid-worker")}
        other = os.path.join(self.repo, "other")
        os.makedirs(other, exist_ok=True)
        # the captain's home line holds the grant; the request is on mid
        self.grant_on("line", other)
        self.client.post("/api/conversations/mid/write-set",
                         json={"path": os.path.join(other, "inner")},
                         headers=mid_worker)
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
        withdrawn = self.client.post(
            f"/api/conversations/kid/write-set/request/{request_id}/withdraw",
            headers=self.kid_worker)
        self.assertEqual(withdrawn.status_code, 200, withdrawn.text)
        self.assertEqual(
            self.db._exec("SELECT COUNT(*) AS n FROM conversation_write_grant_requests"
                          ).fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()
