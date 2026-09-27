"""The process-overview read: a line plus its descendants' live processes."""

import os
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.hierarchy import set_lead, set_parent
from partyline.process_overview import read_rss_bytes, register_process_overview_route
from partyline.runtime import ChatRuntime


class Proc:
    def __init__(self, pid):
        self.pid = pid


class Adapter:
    def __init__(self, att, pid=None):
        self.att = att
        self.proc = Proc(pid) if pid is not None else None


class Presence:
    def __init__(self, phases):
        self.phases = phases

    def phase(self, att_id):
        return self.phases.get(att_id, "idle")


class ProcessOverviewTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        for conv_id, name in (
            ("line", "Line"), ("sub", "Sub"), ("sub2", "Grand"), ("other", "Other"),
        ):
            self.db.create_conversation(conv_id, name)
        set_parent(self.db, "sub", "line")
        set_parent(self.db, "sub2", "sub")
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_process_overview_route(app, self.runtime)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.human = self._bearer(self._user_token())

    def _bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _user_token(self):
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        return auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])

    def add_live(self, ident, name, conv_id, *, pid=None, lead=False):
        owner = f"owner-{ident}"
        self.db.add_attachment(
            ident, conv_id, name, "raw", ["sh"], self.directory.name, owner)
        self.db.set_attachment_status(ident, "running", owner)
        adapter = Adapter(
            {"id": ident, "name": name, "adapter": "raw", "runtime_owner": owner}, pid=pid)
        self.runtime.live[ident] = adapter
        if lead:
            set_lead(self.db, conv_id, ident)
        return adapter

    def token_for(self, ident):
        return self._bearer(auth_store.ensure_api_token(self.db, ident))

    def overview(self, conv_id, headers):
        return self.client.get(
            f"/api/conversations/{conv_id}/process-overview", headers=headers)

    def test_a_person_sees_the_line_and_every_descendant_with_its_processes(self):
        self.add_live("lead", "lead", "line", pid=os.getpid(), lead=True)
        self.add_live("work", "worker", "sub", pid=os.getpid())
        self.db._exec("UPDATE conversations SET goal=? WHERE id=?", ("ship it", "line"))
        self.db._exec("UPDATE conversations SET accepted_sha=? WHERE id=?", ("a" * 40, "sub"))
        self.runtime.presence = Presence({"work": "working"})

        response = self.overview("line", self.human)

        self.assertEqual(response.status_code, 200)
        lines = response.json()["lines"]
        self.assertEqual([line["id"] for line in lines], ["line", "sub", "sub2"])
        self.assertTrue(lines[0]["goal_set"])
        self.assertIsNone(lines[0]["accepted_sha"])
        self.assertEqual(lines[1]["accepted_sha"], "a" * 40)
        self.assertFalse(lines[2]["goal_set"])
        self.assertEqual(lines[2]["attachments"], [])
        [lead] = lines[0]["attachments"]
        self.assertEqual(lead["handle"], "lead")
        self.assertEqual(lead["adapter"], "raw")
        self.assertEqual(lead["pid"], os.getpid())
        self.assertEqual(lead["phase"], "idle")
        self.assertIsNotNone(lead["rss_bytes"])
        self.assertGreater(lead["rss_bytes"], 0)
        self.assertGreater(read_rss_bytes(os.getpid()), 0)
        [work] = lines[1]["attachments"]
        self.assertEqual(work["handle"], "worker")
        self.assertEqual(work["phase"], "working")

    def test_a_worker_outside_the_subtree_is_refused(self):
        self.add_live("other", "otherproc", "other")

        response = self.overview("line", self.token_for("other"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.overview("other", self.token_for("other")).status_code, 200)

    def test_a_captain_reads_its_own_subtree_and_nothing_above_it(self):
        self.add_live("lead", "lead", "line", lead=True)
        self.add_live("work", "worker", "sub")

        response = self.overview("line", self.token_for("lead"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [att["handle"] for line in response.json()["lines"] for att in line["attachments"]],
            ["lead", "worker"],
        )
        self.assertEqual(self.overview("other", self.token_for("lead")).status_code, 403)

    def test_rss_degrades_to_null_without_failing_the_read(self):
        self.add_live("dead", "deadproc", "line", pid=2**31 - 1)
        self.add_live("noproc", "noproc", "line", pid=None)

        response = self.overview("line", self.human)

        self.assertEqual(response.status_code, 200)
        by_handle = {att["handle"]: att for att in response.json()["lines"][0]["attachments"]}
        self.assertIsNone(by_handle["deadproc"]["rss_bytes"])
        self.assertIsNone(by_handle["noproc"]["rss_bytes"])
        self.assertIsNone(by_handle["noproc"]["pid"])

    def test_rss_is_null_off_linux(self):
        with mock.patch("partyline.process_overview.sys.platform", "win32"):
            self.assertIsNone(read_rss_bytes(os.getpid()))

    def test_an_unknown_line_is_404(self):
        self.assertEqual(self.overview("nope", self.human).status_code, 404)
