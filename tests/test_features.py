"""Feature flags resolve once, refuse typos, and gate what they name."""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import features
from partyline.bind import apply_server_config, parse_bind_args


class ResolveTest(unittest.TestCase):
    def test_the_default_is_the_registry_and_the_heartbeat_is_off(self):
        resolved = features.resolve({}, {})
        self.assertFalse(resolved.on("heartbeat"))
        [entry] = [row for row in resolved.describe() if row["name"] == "heartbeat"]
        self.assertEqual((entry["enabled"], entry["default"], entry["status"]),
                         (False, False, "deprecated"))

    def test_config_switches_a_flag_and_the_environment_outranks_it(self):
        self.assertTrue(features.resolve({}, {"features": {"heartbeat": True}}).on("heartbeat"))
        self.assertFalse(features.resolve({"PARTYLINE_FEATURE_HEARTBEAT": "off"},
                                          {"features": {"heartbeat": True}}).on("heartbeat"))
        self.assertTrue(features.resolve({"PARTYLINE_FEATURE_HEARTBEAT": "1"}, {}).on("heartbeat"))

    def test_a_typo_is_refused_loudly_rather_than_enabling_nothing(self):
        with self.assertRaisesRegex(ValueError, "no such flag: hearbeat"):
            features.resolve({}, {"features": {"hearbeat": True}})
        with self.assertRaisesRegex(ValueError, "PARTYLINE_FEATURE_HEARBEAT names no such flag"):
            features.resolve({"PARTYLINE_FEATURE_HEARBEAT": "1"}, {})
        with self.assertRaisesRegex(ValueError, "must be true or false"):
            features.resolve({}, {"features": {"heartbeat": "sometimes"}})
        with self.assertRaisesRegex(ValueError, "must be a table"):
            features.resolve({}, {"features": True})
        with self.assertRaises(KeyError):
            features.resolve({}, {}).on("nope")

    def test_startup_installs_the_resolved_flags_next_to_the_bind_address(self):
        before = features.current()
        self.addCleanup(features.install, before)

        class State:
            pass

        apply_server_config(State(), parse_bind_args([]), {}, {"features": {"heartbeat": True}})
        self.assertTrue(features.enabled("heartbeat"))
        apply_server_config(State(), parse_bind_args([]), {}, {})
        self.assertFalse(features.enabled("heartbeat"))


class GateTest(unittest.TestCase):
    def test_require_answers_404_with_the_way_to_switch_it_on(self):
        before = features.current()
        app = FastAPI()

        @app.get("/gated")
        def gated():
            features.require("heartbeat")
            return {"ok": True}

        with TestClient(app) as client:
            with features.overridden(heartbeat=False):
                off = client.get("/gated")
            self.assertEqual(off.status_code, 404)
            self.assertIn("[features] heartbeat = true", off.json()["detail"])
            self.assertIn("PARTYLINE_FEATURE_HEARTBEAT=1", off.json()["detail"])
            with features.overridden(heartbeat=True):
                self.assertEqual(client.get("/gated").status_code, 200)
        # the override is scoped: the process-wide state is whatever it was before
        self.assertEqual(features.current(), before)
