"""Global admission counts and serializes starting attachment reservations."""

import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.auth_guard import Principal
from partyline.db import Db
from partyline.resource_budget import (
    GIB, Host, claim_resume, clear_stale_restart_rows, defaults, format_limit,
    host_resources, lease_bytes, refusal, reserve_new_attachment, snapshot,
    validate_settings,
)
from partyline.resource_routes import register_resource_routes
from partyline.role_delivery import RoleState, _instructions
from tests import PINNED_TEST_HOST, REAL_HOST_RESOURCES


class ResourceBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.tmp.name}/partyline.db")
        self.db.create_conversation("root", "root line")
        self.db.create_conversation("child", "child line")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='child'")
        self.host = Host(cpus=10, ram_bytes=8 * GIB)
        self.patch_host = patch("partyline.resource_budget.host_resources", return_value=self.host)
        self.patch_host.start()
        self.addCleanup(self.patch_host.stop)

    async def asyncTearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def attach(self, ident, line="root", memory="256M", status="running"):
        att = self.db.add_attachment(ident, line, ident, "raw", ["cat"], self.tmp.name, ident)
        self.db._exec("UPDATE attachments SET status=?,memory_limit=? WHERE id=?", (status, memory, ident))
        return att

    def test_runtime_defaults_follow_injected_host_resources(self):
        values = defaults(self.host)
        self.assertEqual(values["max_live_processes"], 20)
        self.assertEqual(values["memory_reserve_bytes"], 2 * GIB)
        self.assertEqual(values["default_process_memory_bytes"], 2 * GIB)
        self.assertEqual(values["memory_reservation_bytes"], GIB)

    def test_ordinary_tests_use_the_pinned_host_budget(self):
        self.assertEqual(host_resources(), PINNED_TEST_HOST)

    def test_host_resources_falls_back_to_one_cpu(self):
        with patch("partyline.resource_budget.os.cpu_count", return_value=None), patch(
            "partyline.resource_budget.host_memory_bytes", return_value=12 * GIB
        ):
            self.assertEqual(REAL_HOST_RESOURCES(), Host(cpus=1, ram_bytes=12 * GIB))

    def test_format_and_invalid_attachment_leases(self):
        self.assertEqual(format_limit(4 * GIB), "4G")
        self.assertEqual(format_limit(256 * 1024**2), "256M")
        self.assertEqual(
            lease_bytes({"memory_limit": "bad"}, {
                "default_process_memory_bytes": 4 * GIB, "memory_reservation_bytes": GIB,
            }),
            GIB,
        )

    def test_snapshot_counts_all_lines_and_uses_the_largest_line(self):
        self.attach("one", "root")
        self.attach("two", "child")
        self.attach("three", "child")
        view = snapshot(self.db, self.host)
        self.assertEqual(view["live_processes"], 3)
        self.assertEqual(view["memory_reserved_bytes"], 3 * 256 * 1024**2)
        self.assertEqual(view["memory_cap_bytes"], 3 * 256 * 1024**2)
        self.assertEqual(view["busiest_line"], "child line")

    def test_root_captain_briefing_reports_current_capacity(self):
        self.db.set_setting("max_live_processes", "24")
        self.attach("captain", memory="4G")
        state = RoleState("lead", "root", None, (), 0, False, True)
        briefing = _instructions(state, self.db)
        self.assertIn("Instance capacity: 1/24 processes", briefing)
        self.assertIn("1 of 6 GB reserved (4 GB cap)", briefing)

    async def test_simultaneous_final_slot_admissions_allow_only_one(self):
        self.db.set_setting("max_live_processes", "4")
        for ident in ("one", "two", "three"):
            self.attach(ident)

        async def admit(ident):
            return await reserve_new_attachment(
                self.db, att_id=ident, conv_id="root", name=ident, adapter="raw",
                command=["cat"], cwd=self.tmp.name, runtime_owner=ident,
            )

        outcomes = await asyncio.gather(admit("four"), admit("five"), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, dict) for result in outcomes), 1)
        refused = next(result for result in outcomes if isinstance(result, HTTPException))
        self.assertEqual(refused.status_code, 409)
        self.assertIn("4 of 4 live processes", refused.detail)
        new_rows = [self.db.get_attachment(ident) for ident in ("four", "five")]
        self.assertEqual(sum(row is not None for row in new_rows), 1)
        admitted = next(row for row in new_rows if row is not None)
        self.assertEqual(admitted["memory_limit"], "2G")

    async def test_resume_persists_the_default_lease_for_this_activation(self):
        self.attach("one", memory=None, status="exited")
        self.assertTrue(await claim_resume(self.db, "one", "one-owner", 2 * GIB))
        self.assertEqual(self.db.get_attachment("one")["memory_limit"], "2G")

    async def test_resume_claim_loss_precedes_capacity_refusal(self):
        self.db.set_setting("max_live_processes", "4")
        for ident in ("one", "two", "three", "four"):
            self.attach(ident, status="running")
        self.assertFalse(await claim_resume(self.db, "one", "new-owner", 4 * GIB))
        self.assertEqual(self.db.get_attachment("one")["runtime_owner"], "one")

    async def test_restart_clears_stale_rows_but_keeps_a_current_live_process(self):
        self.attach("stale", status="running")
        self.attach("live", "child", status="running")
        runtime = SimpleNamespace(db=self.db, live={"live": object()}, broadcast_attachment=AsyncMock())
        await clear_stale_restart_rows(runtime, ["stale", "live", "missing"])
        self.assertEqual(self.db.get_attachment("stale")["status"], "exited")
        self.assertEqual(self.db.get_attachment("live")["status"], "running")
        runtime.broadcast_attachment.assert_awaited_once_with("root", "stale")

    async def test_restart_grandfathers_each_plan_member_over_the_memory_budget(self):
        self.attach("first", status="running")
        self.attach("second", "child", status="running")
        self.db._exec("UPDATE attachments SET memory_limit='4G'")
        runtime = SimpleNamespace(db=self.db, live={}, broadcast_attachment=AsyncMock())
        await clear_stale_restart_rows(runtime, ["first", "second"])
        self.assertTrue(await claim_resume(
            self.db, "first", "first-owner", 4 * GIB, grandfathered=True
        ))
        self.assertTrue(await claim_resume(
            self.db, "second", "second-owner", 4 * GIB, grandfathered=True
        ))
        self.assertEqual(self.db.get_attachment("first")["status"], "starting")
        self.assertEqual(self.db.get_attachment("second")["status"], "starting")

    def test_settings_reject_reserve_that_leaves_less_than_one_reservation(self):
        with self.assertRaisesRegex(ValueError, "at least one default process reservation"):
            validate_settings({
                "max_live_processes": 4,
                "memory_reserve_bytes": 72 * GIB // 10,
                "default_process_memory_bytes": 4 * GIB,
                "memory_reservation_bytes": GIB,
            }, self.host)

    def test_settings_reject_all_out_of_range_values(self):
        valid = {
            "max_live_processes": 4,
            "memory_reserve_bytes": GIB,
            "default_process_memory_bytes": 4 * GIB,
            "memory_reservation_bytes": GIB,
        }
        for key, value, message in (
            ("max_live_processes", 3, "between 4 and 32"),
            ("memory_reserve_bytes", 8 * GIB, "at most 90%"),
            ("default_process_memory_bytes", 128 * 1024**2, "between 256 MB"),
            ("default_process_memory_bytes", 9 * GIB, "process ceiling"),
            ("memory_reservation_bytes", 128 * 1024**2, "between 256 MB"),
            ("memory_reservation_bytes", 5 * GIB, "default process lease"),
        ):
            with self.subTest(key=key, value=value):
                invalid = {**valid, key: value}
                with self.assertRaisesRegex(ValueError, message):
                    validate_settings(invalid, self.host)

    def test_admission_can_exclude_the_row_being_restarted(self):
        self.attach("one")
        self.assertIsNone(refusal(self.db, 4 * GIB, exclude_id="one", host=self.host))

    def test_memory_refusal_names_the_reservation_that_is_full(self):
        self.db.set_setting("max_live_processes", "8")
        self.db.set_setting("memory_reserve_bytes", str(2 * GIB))
        self.db.set_setting("memory_reservation_bytes", str(GIB))
        for ident in ("one", "two", "three", "four", "five", "six"):
            self.attach(ident, memory="4G")
        message = refusal(self.db, 4 * GIB, host=self.host)
        self.assertIn("7 of 6 GB would be reserved", message or "")
        self.assertIn("1G reservation per process", message or "")

    def test_scaled_cap_defaults_and_generic_host_table(self):
        # Generic 8/16/32/64/128 GB host classes, with representative detected RAM.
        expected = ((7, 5, 2), (15, 13, 2), (30, 27, 3.75),
                    (60, 54, 4), (120, 108, 4))
        for ram_gib, count, cap_gib in expected:
            host = Host(cpus=10, ram_bytes=ram_gib * GIB)
            config = defaults(host)
            capacity = (host.ram_bytes - config["memory_reserve_bytes"]) // GIB
            self.assertEqual(config["memory_reservation_bytes"], GIB)
            self.assertEqual(capacity, count)
            self.assertEqual(config["default_process_memory_bytes"] / GIB, cap_gib)

    def test_machine_can_read_resources_but_only_people_can_edit_settings(self):
        app = FastAPI()

        @app.middleware("http")
        async def identify(request, call_next):
            kind = request.headers.get("x-kind", "machine")
            request.state.principal = Principal(kind=kind, name="caller")
            return await call_next(request)

        register_resource_routes(app, SimpleNamespace(db=self.db))
        with patch("partyline.resource_budget.host_resources", return_value=self.host):
            client = TestClient(app)
            readable = client.get("/api/resources")
            settings_read = client.get("/api/settings/resources", headers={"x-kind": "user"})
            denied = client.put("/api/settings/resources", headers={"x-kind": "machine"}, json={
                "max_live_processes": 8,
                "memory_reserve_bytes": GIB,
                "default_process_memory_bytes": 4 * GIB,
                "memory_reservation_bytes": GIB,
            })
            saved = client.put("/api/settings/resources", headers={"x-kind": "user"}, json={
                "max_live_processes": 8,
                "memory_reserve_bytes": GIB,
                "default_process_memory_bytes": 4 * GIB,
                "memory_reservation_bytes": GIB,
                "memory_warn_percent": 75,
                "memory_captain_ceiling_bytes": 6 * GIB,
            })
            invalid_warning = client.put("/api/settings/resources", headers={"x-kind": "user"}, json={
                "max_live_processes": 8,
                "memory_reserve_bytes": GIB,
                "default_process_memory_bytes": 4 * GIB,
                "memory_reservation_bytes": GIB,
                "memory_warn_percent": 49,
                "memory_captain_ceiling_bytes": 6 * GIB,
            })
            reset_denied = client.post("/api/settings/resources/reset")
            reset = client.post("/api/settings/resources/reset", headers={"x-kind": "user"})
        self.assertEqual(readable.status_code, 200)
        self.assertEqual(readable.json()["max_live_processes"], 20)
        self.assertEqual(settings_read.status_code, 200)
        self.assertEqual(settings_read.json()["max_live_processes"], 20)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["max_live_processes"], 8)
        self.assertEqual(saved.json()["memory_warn_percent"], 75)
        self.assertEqual(saved.json()["memory_captain_ceiling_bytes"], 6 * GIB)
        self.assertEqual(invalid_warning.status_code, 422)
        self.assertEqual(saved.json()["computed_defaults"]["default_process_memory_bytes"], 2 * GIB)
        self.assertEqual(reset_denied.status_code, 403)
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()["default_process_memory_bytes"], 2 * GIB)
        self.assertIsNone(self.db.get_setting("max_live_processes"))
