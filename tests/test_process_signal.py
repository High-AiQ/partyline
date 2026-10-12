"""One runaway descendant, stopped by pid — never by a pkill (5.10)."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.process_signal import resolve_descendant, signal_router
from partyline.runtime import ChatRuntime


class ResolveDescendantTest(unittest.TestCase):
    def test_a_real_child_resolves_and_the_agent_itself_never_does(self):
        child = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (child.kill(), child.wait()))
        me = os.getpid()
        self.assertEqual(resolve_descendant(me, child.pid), child.pid)
        self.assertIsNone(resolve_descendant(me, me))  # the agent is never a target
        self.assertIsNone(resolve_descendant(me, 1))  # not a descendant
        self.assertIsNone(resolve_descendant(me, 999999))

    def test_the_match_is_on_the_callers_namespace_view(self):
        # A synthetic table: the agent is host7, its child is host11 speaking
        # as pid3 in its own namespace. A request for pid3 resolves; pid11
        # (the host view) does not — the caller never sees that number.
        snapshot = ({7: 1, 11: 7}, {7: 100, 11: 200})
        with patch("partyline.process_signal.namespace_pid",
                   side_effect=lambda pid: {7: 1, 11: 3}[pid]):
            self.assertEqual(resolve_descendant(7, 3, snapshot=snapshot), 11)
            self.assertIsNone(resolve_descendant(7, 11, snapshot=snapshot))
            self.assertIsNone(resolve_descendant(7, 1, snapshot=snapshot))


class SignalRouteTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(signal_router(self.runtime))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("other", "Other")
        for att_id, name, conv in (("worker", "sol", "line"),
                                   ("cap", "astra", "line"),
                                   ("outsider", "dig", "other")):
            self.db.add_attachment(att_id, conv, name, "raw", ["raw"], "/tmp", att_id)
            self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (att_id,))
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='cap'")
        # The agent is this test process; its child is the runaway build.
        self.child = subprocess.Popen(["sleep", "60"])
        self.addCleanup(self._reap, self.child)
        self.runtime.live["worker"] = type("A", (), {
            "proc": type("P", (), {"pid": os.getpid()})})()

    @staticmethod
    def _reap(process):
        process.kill()
        process.wait()

    def token(self, att_id):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def signal(self, att_id, pid, kind="TERM", headers=None):
        return self.client.post(f"/api/attachments/{att_id}/signal",
                                json={"pid": pid, "signal": kind},
                                headers=headers or self.token(att_id))

    def test_the_process_itself_stops_its_own_descendant(self):
        made = self.signal("worker", self.child.pid, "KILL")
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json(), {"ok": True, "pid": self.child.pid, "signal": "KILL"})
        self.assertEqual(self.child.wait(timeout=10), -9)  # SIGKILL, reaped

    def test_the_lines_captain_may_signal_a_workers_descendant(self):
        made = self.signal("worker", self.child.pid, headers=self.token("cap"))
        self.assertEqual(made.status_code, 200, made.text)

    def test_a_stranger_and_a_cousin_cannot(self):
        # A worker on another line, and (below) a same-line non-captain.
        stranger = self.signal("worker", self.child.pid, headers=self.token("outsider"))
        self.assertEqual(stranger.status_code, 403)
        self.db.add_attachment("peer", "line", "gem", "raw", ["raw"], "/tmp", "peer")
        peer = self.signal("worker", self.child.pid, headers=self.token("peer"))
        self.assertEqual(peer.status_code, 403)

    def test_the_agent_itself_and_non_descendants_are_refused(self):
        self.assertIsNone(resolve_descendant(os.getpid(), os.getpid()))
        own = self.signal("worker", os.getpid())
        self.assertEqual(own.status_code, 422)
        self.assertIn("not a descendant", own.json()["detail"])
        foreign = self.signal("worker", 1)
        self.assertEqual(foreign.status_code, 422)

    def test_an_attachment_with_no_live_process_is409(self):
        self.runtime.live.pop("worker")
        made = self.signal("worker", self.child.pid)
        self.assertEqual(made.status_code, 409)


if __name__ == "__main__":
    unittest.main()
