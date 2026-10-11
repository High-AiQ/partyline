"""Shared-resource leases and the host-resource rider (finding 2.10)."""

import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.lease_schema import MIGRATIONS as LEASE_MIGRATIONS
from partyline.resource_leases import (
    LeaseError,
    active_lease_report,
    register_lease_routes,
    release_attachment_leases,
    request_lease,
)
from partyline.role_delivery import RoleState, bind_role_delivery
from partyline.runtime import ChatRuntime
from partyline.staffing import staffing_line


class LeaseLogicTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("assets", "world-assets")
        self.db.create_conversation("effects", "effects")
        self.db.add_attachment("sonnet", "assets", "sonnet", "raw", ["raw"], "/tmp")
        self.db.add_attachment("luna", "effects", "luna", "raw", ["raw"], "/tmp")

    def take(self, holder, name="godot", mode="exclusive", ttl_s=900):
        att = self.db.get_attachment(holder)
        return request_lease(self.db, holder, att["name"], att["conv_id"],
                             name, mode, ttl_s)

    def test_an_exclusive_lease_blocks_and_queues_a_second(self):
        first = self.take("sonnet")
        self.assertTrue(first["granted"])
        self.assertEqual(first["queue_position"], 0)
        second = self.take("luna")
        self.assertFalse(second["granted"])
        self.assertEqual(second["holder"], {"handle": "sonnet", "line": "assets"})
        self.assertEqual(second["queue_position"], 1)

    def test_shared_leases_coexist_but_not_with_an_exclusive_one(self):
        self.assertTrue(self.take("sonnet", mode="shared")["granted"])
        self.assertTrue(self.take("luna", mode="shared")["granted"])
        exclusive = self.take("sonnet", name="shader", mode="exclusive")
        self.assertTrue(exclusive["granted"])  # a different name is free
        blocked = self.take("luna", mode="exclusive")  # godot is held shared
        self.assertFalse(blocked["granted"])
        self.assertEqual(blocked["queue_position"], 2)  # behind both shared holders

    def test_a_ttl_expiry_frees_the_lease(self):
        self.take("sonnet", ttl_s=900)
        # the lease ages past its TTL: the next request finds the slot free
        self.db._exec("UPDATE resource_leases SET expires_at=1 WHERE name='godot'")
        second = self.take("luna")
        self.assertTrue(second["granted"], second)

    def test_posting_again_renews_and_release_frees_the_slot(self):
        first = self.take("sonnet", ttl_s=900)
        renewed = self.take("sonnet", ttl_s=1800)
        self.assertTrue(renewed["granted"])
        self.assertGreater(renewed["expires_at"], first["expires_at"])
        self.assertEqual(release_attachment_leases(self.db, "sonnet"), 1)
        self.assertTrue(self.take("luna")["granted"])

    def test_malformed_requests_are_refused(self):
        for kwargs in ({"name": ""}, {"name": "has space"}, {"mode": "maybe"},
                       {"ttl_s": 0}, {"ttl_s": 4 * 3600 + 1}):
            with self.assertRaises(LeaseError):
                self.take("sonnet", **kwargs)

    def test_the_schema_migration_runs_twice(self):

        for _ in range(2):
            for migration in LEASE_MIGRATIONS:
                self.db._exec(migration)
        self.assertTrue(self.take("sonnet")["granted"])

    def test_the_report_lists_holders_and_queue_counts(self):
        self.take("sonnet", mode="shared")
        self.take("luna", mode="shared")
        report = active_lease_report(self.db)
        godot = next(entry for entry in report if entry["name"] == "godot")
        self.assertEqual(godot["mode"], "shared")
        self.assertEqual(godot["queued"], 0)
        self.assertEqual(len(godot["holders"]), 2)


class LeaseApiTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_lease_routes(app, self.runtime)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("assets", "world-assets")
        self.db.add_attachment("sonnet", "assets", "sonnet", "raw", ["raw"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='sonnet'")
        token = auth_store.ensure_api_token(self.db, "sonnet")
        self.sonnet = {"Authorization": "Bearer " + token}

    def test_the_api_grants_lists_and_releases(self):
        made = self.client.post("/api/leases", json={"name": "godot", "ttl_s": 900},
                                headers=self.sonnet)
        self.assertEqual(made.status_code, 200, made.text)
        self.assertTrue(made.json()["granted"])
        listed = self.client.get("/api/leases", headers=self.sonnet)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["leases"][0]["name"], "godot")
        dropped = self.client.delete("/api/leases/godot", headers=self.sonnet)
        self.assertEqual(dropped.status_code, 200, dropped.text)
        self.assertEqual(self.client.get("/api/leases",
                                         headers=self.sonnet).json()["leases"], [])
        self.assertEqual(self.client.delete("/api/leases/godot",
                                            headers=self.sonnet).status_code, 404)

    def test_a_malformed_lease_is_refused(self):
        made = self.client.post("/api/leases", json={"name": "nope nope"},
                                headers=self.sonnet)
        self.assertEqual(made.status_code, 422, made.text)


class LeaseHooksTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("godot-user", "line", "sonnet", "raw", ["raw"],
                               self.directory.name, "owner-1")
        self.db.set_attachment_status("godot-user", "running", "owner-1")

    def test_process_exit_releases_the_lease(self):
        from partyline.memory_contracts import ProcessExit
        from partyline.process_incidents import record_exit

        def count():
            return self.db._exec(
                "SELECT COUNT(*) AS n FROM resource_leases").fetchone()["n"]

        request_lease(self.db, "godot-user", "sonnet", "line", "godot", "exclusive", 900)
        self.assertEqual(count(), 1)
        att = self.db.get_attachment("godot-user")
        evidence = ProcessExit(code=0, reason="exit", limit_bytes=1)
        asyncio.run(record_exit(self.runtime, att, evidence))
        self.assertEqual(count(), 0)

    def test_detach_releases_the_lease(self):
        from partyline.line_process_routes import detach_attachment
        from partyline.resource_leases import request_lease

        request_lease(self.db, "godot-user", "sonnet", "line", "godot", "exclusive", 900)
        live = SimpleNamespace(att=self.db.get_attachment("godot-user"), stopped=False)
        on_status = self.runtime.status_callback("godot-user", "line", "owner-1")

        async def stop():
            live.stopped = True
            await on_status("exited")

        live.stop = stop
        self.runtime.live["godot-user"] = live
        asyncio.run(detach_attachment(self.runtime, "godot-user"))
        self.assertEqual(
            self.db._exec("SELECT COUNT(*) AS n FROM resource_leases").fetchone()["n"], 0)


class StaffingLeaseTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "partyline.db"))
        self.addCleanup(self.db.close)
        self.db.create_conversation("root", "Root")
        self.db.create_conversation("assets", "world-assets")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='assets'")
        self.db.save_preset("sonnet", "sonnet", "sonnet", "raw", "raw --x",
                            can_manage=False, implements=True)
        self.db.add_attachment("a1", "assets", "sonnet", "raw", ["raw", "--x"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='a1'")
        from partyline.resource_leases import request_lease

        request_lease(self.db, "a1", "sonnet", "assets", "godot", "exclusive", 900)
        self.db.create_conversation("wait", "Waiter")
        self.db.add_attachment("w1", "wait", "luna", "raw", ["raw"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='w1'")
        request_lease(self.db, "w1", "luna", "wait", "godot", "exclusive", 900)
        line = staffing_line(self.db, "root", runtime=None)
        self.assertIn(
            "leases: godot (exclusive) @sonnet «world-assets», 1 queued", line)
        # nothing held: no segment at all
        self.db._exec("DELETE FROM resource_leases")
        self.assertNotIn("leases:", staffing_line(self.db, "root", runtime=None))


class ResourceRiderTest(unittest.TestCase):
    def test_the_host_rider_rides_once_per_interval_for_captains(self):
        now = {"value": 1000.0}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db = Db(os.path.join(directory.name, "partyline.db"))
        self.addCleanup(db.close)
        db.create_conversation("line", "Line")
        manager = RoleState("lead", "line", None, ("assign", "create_child"))
        att = {"id": "cap", "digest_rider": lambda: "board"}
        with patch("partyline.role_delivery.current_role", return_value=manager), \
                patch("partyline.role_delivery.time", Mock(time=lambda: now["value"])), \
                patch("partyline.role_delivery.host_resource_line",
                      return_value="(host: 32 cores, 40.0 GB free, load 0.31)"):
            bind_role_delivery(db, att)
            first = att["digest_rider"]()
            second = att["digest_rider"]()  # ten minutes have not passed
            now["value"] = 1700.0
            third = att["digest_rider"]()  # the interval has passed
        self.assertIn("(host: 32 cores, 40.0 GB free, load 0.31)", first)
        self.assertNotIn("(host:", second)
        self.assertIn("(host: 32 cores", third)


if __name__ == "__main__":
    unittest.main()

