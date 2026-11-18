"""Attributed ingestion, nearest-rank percentiles, hierarchy access and expiry."""

import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, tool_telemetry
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.mcp.telemetry import record as telemetry_record
from partyline.storage_cleanup import cleanup
from partyline.tool_telemetry_contracts import ToolCall
from partyline.tool_telemetry_routes import telemetry_router


class RouteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Db(directory.name + "/test.db")
        self.addCleanup(self.db.close)
        for conv in ("home", "child", "grandchild", "other"):
            self.db.create_conversation(conv, conv)
            self.db.add_attachment(conv, conv, conv, "claude", ["fake"], "/tmp")
        for child, parent in (("child", "home"), ("grandchild", "child")):
            self.db._exec("UPDATE conversations SET parent_id=? WHERE id=?", (parent, child))
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(telemetry_router(SimpleNamespace(db=self.db)))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        person = auth_store.create_user(self.db, "person@example.com", "person", "unused")
        self.person = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), person["id"])}
        self.now = time.time()

    def machine(self, name="home"):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, name)}

    def record(self, tokens=1, **extra):
        return {"tool": "screen_elements", "result_bytes": tokens * 4, "result_chars": tokens * 4,
                "estimated_tokens": tokens, "is_error": False, "latency_ms": tokens * 10,
                "timestamp": self.now, **extra}

    def ingest(self, records, name="home", headers=None):
        return self.client.post("/api/telemetry/tool-calls", json={"records": records},
                                headers=headers or self.machine(name))

    def summary(self, conv="home", headers=None, **query):
        return self.client.get("/api/telemetry/tool-calls/summary", params={"conv_id": conv, **query},
                               headers=headers or self.machine())

    def test_phase_timings_persist_without_content_and_reject_unknown_fields(self):
        timing = {"helper_uia_ms": 14, "helper_barrier_stop": "quiet", "server_total_ms": 40}
        self.assertEqual(200, self.ingest([self.record(timing=timing)]).status_code)
        saved = json.loads(self.db._exec("SELECT metrics FROM tool_calls").fetchone()[0])
        self.assertEqual(timing, saved["timing"])
        self.assertEqual(422, self.ingest([self.record(timing={"private title": 1})]).status_code)

    def test_screen_metric_rejects_unstructured_content(self):
        raw = telemetry_record(
            "screen_element_action", {"window": "grant", "action": "set_value", "value": "Private text"},
            "completed", {"status": "completed"}, False, time.perf_counter(),
        )
        metric = ToolCall.model_validate(raw)
        response = self.ingest([metric.model_dump()])
        self.assertEqual(response.status_code, 200, response.text)
        stored = json.loads(self.db._exec("SELECT metrics FROM tool_calls").fetchone()[0])
        self.assertNotIn("Private text", json.dumps(stored))
        self.assertNotIn("arguments", stored)
        self.assertNotIn("observation", stored)
        columns = {row["name"] for row in self.db._exec("PRAGMA table_info(tool_calls)").fetchall()}
        self.assertNotIn("arguments", columns)
        self.assertNotIn("observation", columns)
        tables = {row["name"] for row in self.db._exec(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertNotIn("structured_screen_transcripts", tables)
        self.assertEqual(self.client.post(
            "/api/telemetry/tool-calls",
            json={"records": [metric.model_dump()], "transcripts": [{"arguments": {"x": "y"}}]},
            headers=self.machine(),
        ).status_code, 422)

    def test_percentiles_flags_groups_filters_and_attribution(self):
        records = [self.record(n, is_error=n == 20) for n in range(1, 21)]
        self.assertEqual(self.ingest(records).json(), {"stored": 20})
        row = self.summary().json()["rows"][0]
        self.assertEqual((row["calls"], row["total_estimated_tokens"], row["p50_estimated_tokens"],
                          row["p95_estimated_tokens"], row["max_estimated_tokens"], row["errors"],
                          row["p50_latency_ms"]), (20, 210, 10, 19, 20, 1, 100))
        self.ingest([self.record(5, query=True)])
        self.assertEqual(len(self.summary().json()["rows"]), 2)
        self.assertEqual(len(self.summary(group="tool").json()["rows"]), 1)
        self.assertEqual(self.summary(since=self.now + 1).json()["rows"], [])
        stored = dict(self.db._exec("SELECT * FROM tool_calls LIMIT 1").fetchone())
        self.assertEqual((stored["conv_id"], stored["attachment_id"], stored["adapter"]),
                         ("home", "home", "claude"))
        self.assertEqual(self.summary(group="bad").status_code, 422)
        self.assertEqual(self.summary(since=-1).status_code, 422)

    def test_person_plain_process_descendants_and_unrelated(self):
        for conv in ("home", "child", "grandchild", "other"):
            self.ingest([self.record()], conv)
            self.assertEqual(self.summary(conv, self.person).status_code, 200)
        for conv in ("home", "child", "grandchild"):
            self.assertEqual(self.summary(conv).status_code, 200)
        self.assertEqual(self.summary("other").status_code, 403)
        self.assertEqual(self.summary("home", self.machine("child")).status_code, 403)
        self.assertEqual(self.summary("missing", self.person).status_code, 404)
        self.assertEqual(self.summary(include_descendants=True).json()["rows"][0]["calls"], 3)
        self.assertEqual(self.ingest([], headers=self.person).status_code, 403)
        self.assertEqual(self.client.get("/api/telemetry/tool-calls/summary?conv_id=home").status_code, 401)

    def test_reject_content_and_spoofed_identity_and_clean_invalid_labels(self):
        for extra in ({"body": "secret"}, {"title": "secret"}, {"arguments": {"query": "secret"}},
                      {"attachment_id": "other"}, {"conv_id": "other"}):
            self.assertEqual(self.ingest([self.record(**extra)]).status_code, 422)
        self.assertEqual(self.ingest([self.record(images=[{"width": 2, "height": 3,
            "provider": "claude", "estimated_tokens": 999, "title": "secret"}])]).status_code, 422)
        self.ingest([self.record(tool="secret", sub_op="secret")])
        raw = self.db._exec("SELECT metrics FROM tool_calls").fetchone()["metrics"]
        self.assertNotIn("secret", raw)
        self.assertEqual(json.loads(raw)["tool"], "unknown")
        self.assertEqual(self.ingest([self.record()] * 65).status_code, 422)

    def test_image_cost_derived_from_authenticated_adapter(self):
        image = {"width": 750, "height": 1000, "provider": "unknown", "estimated_tokens": None}
        self.ingest([self.record(images=[image])])
        self.assertEqual(self.summary().json()["rows"][0]["total_estimated_tokens"], 1001)
        self.db._exec("UPDATE attachments SET adapter='codex' WHERE id='child'")
        self.ingest([self.record(images=[image])], "child")
        child = self.summary("child").json()["rows"][0]
        self.assertEqual((child["total_estimated_tokens"], child["unknown_images"]), (1, 1))

    def test_retention_ingest_cleanup_read_and_line_deletion(self):
        self.ingest([self.record(timestamp=self.now - tool_telemetry.RETENTION_SECONDS - 10)])
        self.assertEqual(self.summary().json()["rows"], [])
        self.ingest([self.record(timestamp=self.now + 100)])
        stored = self.db._exec("SELECT timestamp FROM tool_calls").fetchone()["timestamp"]
        self.assertLess(stored, self.now + 100)
        with patch.object(tool_telemetry.time, "time", return_value=self.now + 31 * 86400):
            self.assertEqual(self.summary().json()["rows"], [])
            cleanup(self.db, attachment_id="does-not-exist")
        self.assertEqual(self.db._exec("SELECT COUNT(*) AS n FROM tool_calls").fetchone()["n"], 0)
        self.ingest([self.record()])
        self.db._exec("DELETE FROM conversations WHERE id='home'")
        self.assertEqual(self.db._exec("SELECT COUNT(*) AS n FROM tool_calls").fetchone()["n"], 0)
        # Idempotent migration preserves an already-recorded metric.
        self.ingest([self.record()], "child")
        reopened = Db(self.db.path)
        try:
            self.assertEqual(reopened._exec("SELECT COUNT(*) AS n FROM tool_calls").fetchone()["n"], 1)
        finally:
            reopened.close()

    def test_prune_keeps_boundary(self):
        with patch.object(tool_telemetry.time, "time", return_value=self.now):
            tool_telemetry.store(self.db, self.db.get_attachment("home"), [ToolCall.model_validate(
                self.record(timestamp=self.now - tool_telemetry.RETENTION_SECONDS))])
        tool_telemetry.prune(self.db, self.now)
        self.assertEqual(self.db._exec("SELECT COUNT(*) AS n FROM tool_calls").fetchone()["n"], 1)

    def test_nested_action_groups_and_independent_latency_percentile(self):
        records = [self.record(tokens, tool="extras", sub_op="screen_element_action", action="invoke",
                               latency_ms=latency, then=True)
                   for tokens, latency in ((100, 1), (1, 100), (200, 2))]
        records.append(self.record(50, tool="extras", sub_op="screen_element_action", action="toggle"))
        self.ingest(records)
        rows = self.summary().json()["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["action"], rows[0]["p50_estimated_tokens"], rows[0]["p50_latency_ms"]),
                         ("invoke", 100, 2))
        self.assertEqual(self.summary(group="tool").json()["rows"][0]["calls"], 4)
