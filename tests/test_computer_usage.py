"""Computer-use response attribution, screen-call totals, timing and read access."""

import json
import tempfile
import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.computer_usage_routes import computer_usage_router
from partyline.computer_usage_summary import ACTIONS, READS, summary
from partyline.db import Db
from partyline.hierarchy import set_parent
from partyline.mcp.catalog import SCREEN
from partyline.turn_usage import RETENTION_SECONDS


class ComputerUsageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Db(directory.name + "/test.db")
        self.addCleanup(self.db.close)
        for conv in ("line", "child", "other"):
            self.db.create_conversation(conv, conv)
            self.db.add_attachment("att-" + conv, conv, conv, "claude", ["fake"], directory.name)
        set_parent(self.db, "child", "line")
        self.now = time.time()
        self.number = 0

    def turn(self, calls, *, conv="line", tokens=(10, 20, 30, 40), model_ms=1000, timestamp=None):
        self.number += 1
        input_tokens, cache_read, cache_write, output = tokens
        self.db._exec(
            """INSERT INTO turn_usage(conv_id, attachment_id, adapter, response_id, model, input_tokens,
               cache_read_tokens, cache_write_tokens, output_tokens, reasoning_tokens, total_tokens,
               context_tokens, context_window, calls, timestamp, model_ms)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (conv, "att-" + conv, "claude", f"r{self.number}", "model", input_tokens, cache_read,
             cache_write, output, 0, sum(tokens), sum(tokens[:3]), None, json.dumps(calls),
             self.now - 60 if timestamp is None else timestamp, model_ms),
        )

    def call(self, tool, *, sub_op="", conv="line", timestamp=None, latency=100, images=None, error=False,
             outcome="ok", media_source="other"):
        metrics = {"tool": tool, "sub_op": sub_op, "latency_ms": latency, "is_error": error,
                   "outcome": outcome, "media_source": media_source, "images": images or []}
        self.db._exec(
            "INSERT INTO tool_calls(conv_id, attachment_id, adapter, timestamp, metrics) VALUES(?,?,?,?,?)",
            (conv, "att-" + conv, "claude", self.now - 60 if timestamp is None else timestamp,
             json.dumps(metrics)),
        )

    def read(self, **kwargs):
        return summary(self.db, "line", ["line"], 0, now=self.now, **kwargs)

    def test_screen_vocabulary_is_partitioned(self):
        self.assertLessEqual(ACTIONS | READS, SCREEN)
        self.assertEqual(SCREEN - ACTIONS - READS, {"screen_control_request", "screen_attach_window"})

    def test_mixed_responses_count_once_and_screen_calls_include_extras(self):
        self.turn(["Bash", "screen_click", "extras:screen_elements"])
        self.turn(["extras:invoke"], tokens=(1, 2, 3, 4), model_ms=None)
        self.turn(["extras:turn_usage", "Bash"], tokens=(1000, 0, 0, 0))
        self.turn(["screen_window_snapshot"], tokens=(5, 6, 7, 8), model_ms=2000)
        self.turn(["screen_click"], conv="other", tokens=(1000, 0, 0, 0))
        image = {"width": 10, "height": 10, "provider": "claude", "estimated_tokens": 500}
        unknown = {"width": 10, "height": 10, "provider": "unknown", "estimated_tokens": None}
        self.call("screen_click", timestamp=self.now - 50, images=[image], error=True, outcome="error")
        self.call("extras", sub_op="screen_type", timestamp=self.now - 40, latency=200, outcome="failed")
        self.call("screen_key", timestamp=self.now - 20, latency=300, outcome="unconfirmed")
        self.call("extras", sub_op="screen_elements", latency=50, images=[image, unknown])
        self.call("screen_control_request", latency=25, outcome="unknown")
        self.call("get_media", media_source="screen", images=[image], latency=999)
        self.call("get_media", media_source="other", images=[image], latency=999)
        self.call("Bash", latency=999)
        result = self.read()
        self.assertEqual((result.responses, result.total_tokens, result.input_tokens), (3, 136, 16))
        self.assertEqual((result.cache_read_tokens, result.cache_write_tokens, result.output_tokens),
                         (28, 40, 52))
        self.assertEqual((result.model_ms, result.model_time_responses), (3000, 2))
        self.assertEqual((result.calls, result.actions, result.reads, result.other_calls), (5, 3, 1, 1))
        self.assertEqual((result.images, result.image_tokens, result.images_with_unknown_tokens),
                         (4, 1500, 1))
        self.assertEqual((result.tool_ms, result.errors, result.unconfirmed, result.outcome_unknown),
                         (675, 2, 1, 1))
        self.assertEqual((result.action_intervals, result.p50_action_ms, result.p95_action_ms),
                         (2, 10000, 20000))
        self.assertIsNone(result.cost_usd)

    def test_action_intervals_never_cross_processes(self):
        self.call("screen_click", timestamp=self.now - 50)
        self.call("screen_key", conv="child", timestamp=self.now - 40)
        self.call("screen_type", timestamp=self.now - 30)
        result = summary(self.db, "line", ["line", "child"], 0, include_descendants=True, now=self.now)
        self.assertEqual((result.actions, result.action_intervals, result.p50_action_ms), (3, 1, 20000))

    def test_window_retention_and_empty_percentiles(self):
        self.turn(["screen_click"], timestamp=self.now - 7200)
        self.call("screen_click", timestamp=self.now - 7200)
        recent = summary(self.db, "line", ["line"], self.now - 3600, now=self.now)
        self.assertEqual((recent.responses, recent.calls, recent.action_intervals), (0, 0, 0))
        self.assertIsNone(recent.p50_action_ms)
        old = self.now - RETENTION_SECONDS - 1
        self.turn(["screen_click"], timestamp=old)
        self.call("screen_click", timestamp=old)
        expired = self.read()
        self.assertEqual((expired.responses, expired.calls), (1, 1))
        self.assertEqual(expired.since, self.now - RETENTION_SECONDS)


class ComputerUsageRouteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Db(directory.name + "/test.db")
        self.addCleanup(self.db.close)
        for conv in ("line", "child", "other"):
            self.db.create_conversation(conv, conv)
            self.db.add_attachment(conv, conv, conv, "claude", ["fake"], directory.name)
        set_parent(self.db, "child", "line")
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(computer_usage_router(type("Runtime", (), {"db": self.db})()))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        person = auth_store.create_user(self.db, "person@example.com", "person", "unused")
        self.person = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), person["id"])}

    def machine(self, conv="line"):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, conv)}

    def get(self, conv="line", headers=None, **params):
        return self.client.get("/api/telemetry/computer-use/summary", params={"conv_id": conv, **params},
                               headers=headers or self.machine())

    def test_person_process_descendants_and_errors(self):
        for conv in ("line", "child", "other"):
            self.assertEqual(self.get(conv, self.person).status_code, 200)
            self.assertEqual(self.get(conv).status_code, 200 if conv != "other" else 403)
        self.assertEqual(self.get("line", self.machine("child")).status_code, 403)
        self.assertEqual(self.get("missing", self.person).status_code, 404)
        self.assertEqual(self.get(since=-1).status_code, 422)
        self.assertEqual(self.get(since="nan").status_code, 422)
        self.assertEqual(self.get(since="inf").status_code, 422)
        self.assertEqual(self.client.get("/api/telemetry/computer-use/summary?conv_id=line").status_code, 401)
        result = self.get(include_descendants=True).json()
        self.assertTrue(result["include_descendants"])
        self.assertEqual((result["responses"], result["calls"], result["cost_usd"]), (0, 0, None))
