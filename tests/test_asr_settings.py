"""Speech presets in settings: CRUD, auth, config+database merge, live rebuild, secrets.

No network and no model: OpenAI calls go through a patched ``urlopen`` and the
recognizers are tiny commands or fakes.
"""

import io
import json
import logging
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import asr_presets, asr_store
from partyline.asr_backends import OpenAICompatible
from partyline.asr_settings_routes import asr_settings_router
from partyline.auth_guard import install_auth_guard
from partyline.auth_store import create_user, ensure_api_token
from partyline.auth_tokens import create_access_token, hash_password, signing_secret
from partyline.db import Db
from partyline.runtime import ChatRuntime
from partyline.transcribe_routes import transcribe_router
from partyline.transcript import TakeFailed, TranscriberUnavailable

SENTINEL = "sk-SENTINEL-never-leaves-0123456789"
PRINT_HI = [sys.executable, "-c", "print('{\"text\": \"hi there\", \"language\": \"en\"}')"]
CONFIG = {"asr": [
    {"name": "local", "kind": "command", "argv": PRINT_HI},
    {"name": "cloud", "kind": "openai-compatible", "base_url": "https://api.example.test",
     "model": "whisper-1",
     "api_key_env": "ASR_TEST_KEY"},
]}


class AsrSettingsBase(unittest.TestCase):
    config = CONFIG

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.events = []

        async def broadcast_all(event):
            self.events.append(event.type)

        self.runtime.broadcast_all = broadcast_all
        self.ticks = iter([10.0, 10.25])
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(asr_settings_router(self.runtime, clock=lambda: next(self.ticks)))
        app.include_router(transcribe_router(self.runtime, lambda: asr_presets.shared_registry(self.db)))
        self.client = TestClient(app)
        user = create_user(self.db, "test@example.com", "tester", hash_password("hunter2222"))
        self.headers = {"Authorization": "Bearer " + create_access_token(signing_secret(self.db), user["id"])}
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("machine", "line", "worker", "fake", ["run"], "/tmp")
        self.machine = {"Authorization": "Bearer " + ensure_api_token(self.db, "machine")}
        self.env = mock.patch.dict(os.environ, {"ASR_TEST_KEY": SENTINEL})
        self.env.start()
        asr_presets.install(self.config, os.environ)

    def tearDown(self):
        self.env.stop()
        asr_presets.install({}, {})
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def create(self, name, kind="command", **fields):
        return self.client.post("/api/settings/asr/presets", headers=self.headers,
                                json={"name": name, "kind": kind, "fields": fields})

    def names(self, listing):
        return [preset["name"] for preset in listing["presets"]]

    def mic(self):
        return self.client.get("/api/transcribe/presets", headers=self.machine).json()


class CrudTest(AsrSettingsBase):
    def test_config_presets_are_read_only_and_listed_first_without_rows(self):
        listing = self.client.get("/api/settings/asr", headers=self.headers).json()
        self.assertEqual(["local", "cloud"], self.names(listing))
        self.assertEqual("local", listing["default"])
        cloud = listing["presets"][1]
        self.assertEqual(("config", False, True), (cloud["source"], cloud["editable"], cloud["key_set"]))
        self.assertEqual("ASR_TEST_KEY", cloud["key_env"])
        self.assertEqual(404, self.client.delete("/api/settings/asr/presets/local", headers=self.headers)
                         .status_code)

    def test_create_edit_reorder_default_delete_apply_live(self):
        created = self.create("wx", argv=PRINT_HI, timeout=30)
        self.assertEqual(201, created.status_code, created.text)
        self.assertEqual(["wx", "local", "cloud"], self.names(created.json()))
        self.assertIn("wx", self.names(self.mic()))  # the composer sees it without a restart
        self.assertEqual(409, self.create("wx", argv=PRINT_HI).status_code)
        self.create("second", argv=PRINT_HI)
        edited = self.client.put("/api/settings/asr/presets/wx", headers=self.headers,
                                 json={"kind": "command", "fields": {"argv": PRINT_HI, "timeout": 5}})
        self.assertEqual(5, edited.json()["presets"][0]["fields"]["timeout"])
        ordered = self.client.put("/api/settings/asr/order", headers=self.headers,
                                  json={"names": ["second", "wx"]})
        self.assertEqual(["second", "wx", "local", "cloud"], self.names(ordered.json()))
        self.assertEqual(422, self.client.put("/api/settings/asr/order", headers=self.headers,
                                              json={"names": ["wx"]}).status_code)
        made = self.client.put("/api/settings/asr/default", headers=self.headers, json={"name": "wx"})
        self.assertEqual("wx", made.json()["default"])
        self.assertEqual("wx", self.mic()["default"])
        removed = self.client.delete("/api/settings/asr/presets/wx", headers=self.headers)
        self.assertEqual(("local", ["second", "local", "cloud"]),
                         (removed.json()["default"], self.names(removed.json())))
        self.assertEqual(["asr_presets_changed"] * 6, self.events)

    def test_default_rules_for_config_presets(self):
        self.create("wx", argv=PRINT_HI)
        self.client.put("/api/settings/asr/default", headers=self.headers, json={"name": "wx"})
        back = self.client.put("/api/settings/asr/default", headers=self.headers, json={"name": "local"})
        self.assertEqual("local", back.json()["default"])  # the config default clears the flag
        refused = self.client.put("/api/settings/asr/default", headers=self.headers, json={"name": "cloud"})
        self.assertEqual(409, refused.status_code)
        self.assertEqual(404, self.client.put("/api/settings/asr/default", headers=self.headers,
                                              json={"name": "nope"}).status_code)
        self.assertEqual(404, self.client.put("/api/settings/asr/presets/nope", headers=self.headers,
                                              json={"kind": "command",
                                                    "fields": {"argv": ["x"]}}).status_code)

    def test_invalid_presets_are_refused_inline(self):
        cases = [
            ({"kind": "command", "fields": {}}, "argv"),
            ({"kind": "command", "fields": {"argv": ["x"], "timeout": -1}}, "timeout"),
            ({"kind": "openai-compatible", "fields": {"model": "m"}}, "base_url"),
            ({"kind": "openai-compatible", "fields": {"base_url": "ftp://x", "model": "m"}}, "http"),
        ]
        for body, word in cases:
            answer = self.client.post("/api/settings/asr/presets", headers=self.headers,
                                      json={"name": "bad", **body})
            self.assertEqual(422, answer.status_code, body)
            self.assertIn(word, answer.json()["detail"])
        self.assertEqual(422, self.create("bad name!", argv=["x"]).status_code)
        self.assertEqual(422, self.create("tpu", kind="tpu").status_code)


class AuthTest(AsrSettingsBase):
    def test_processes_and_strangers_are_refused_everywhere(self):
        self.create("wx", argv=PRINT_HI)
        calls = [
            ("get", "/api/settings/asr", None),
            ("post", "/api/settings/asr/presets",
             {"name": "m", "kind": "command", "fields": {"argv": ["x"]}}),
            ("put", "/api/settings/asr/presets/wx", {"kind": "command", "fields": {"argv": ["x"]}}),
            ("delete", "/api/settings/asr/presets/wx", None),
            ("put", "/api/settings/asr/default", {"name": "wx"}),
            ("put", "/api/settings/asr/order", {"names": ["wx"]}),
            ("post", "/api/settings/asr/presets/wx/test", None),
        ]
        for method, path, body in calls:
            kwargs = {} if body is None else {"json": body}
            self.assertEqual(401, getattr(self.client, method)(path, **kwargs).status_code, path)
            refused = getattr(self.client, method)(path, headers=self.machine, **kwargs)
            self.assertEqual(403, refused.status_code, path)
        self.assertEqual(PRINT_HI, asr_store.get_preset(self.db, "wx")["config"]["argv"])


class MergeTest(AsrSettingsBase):
    def test_database_preset_wins_over_a_config_preset_of_the_same_name(self):
        override = self.create("cloud", kind="openai-compatible", base_url="https://other.test",
                               model="gpt-4o-transcribe", response_format="json", api_key_env="ASR_TEST_KEY")
        presets = {p["name"]: p for p in override.json()["presets"]}
        self.assertEqual(["cloud", "local"], self.names(override.json()))
        cloud = presets["cloud"]
        self.assertEqual(("database", True, "gpt-4o-transcribe"),
                         (cloud["source"], cloud["overrides_config"], cloud["model"]))
        backend = asr_presets.shared_registry(self.db).get("cloud")
        self.assertEqual(("json", "https://other.test/v1/audio/transcriptions"),
                         (backend.response_format, backend.url))
        self.client.delete("/api/settings/asr/presets/cloud", headers=self.headers)
        self.assertEqual("https://api.example.test/v1/audio/transcriptions",
                         asr_presets.shared_registry(self.db).get("cloud").url)

    def test_rebuild_reuses_unchanged_backends_and_releases_dropped_ones(self):
        self.create("wx", argv=PRINT_HI)
        before = asr_presets.shared_registry(self.db)
        self.create("other", argv=PRINT_HI)
        after = asr_presets.shared_registry(self.db)
        self.assertIsNot(before, after)
        self.assertIs(before.get("wx"), after.get("wx"))
        self.assertIs(before.get("local"), after.get("local"))
        dropped = mock.Mock()
        after.entries["wx"] = dropped
        self.client.delete("/api/settings/asr/presets/wx", headers=self.headers)
        dropped.unload_if_idle.assert_called_once_with()

    def test_a_stored_row_that_no_longer_builds_is_listed_unavailable(self):
        asr_store.save_preset(self.db, "stale", {"kind": "command", "argv": []}, create=True)
        with self.assertLogs("partyline.asr_presets", "WARNING") as logs:
            listing = self.client.get("/api/settings/asr", headers=self.headers).json()
        stale = next(p for p in listing["presets"] if p["name"] == "stale")
        self.assertEqual((False, "command"), (stale["available"], stale["kind"]))
        self.assertIn("argv", stale["reason"])
        self.assertIn("stale", logs.output[0])

    def test_no_config_tables_keeps_the_builtin_local_preset(self):
        asr_presets.install({}, {})
        self.create("wx", argv=PRINT_HI)
        listing = self.client.get("/api/settings/asr", headers=self.headers).json()
        self.assertEqual(["wx", "faster-whisper"], self.names(listing))
        self.assertEqual("builtin", listing["presets"][1]["source"])
        self.assertEqual("faster-whisper", listing["default"])


class TestRouteTest(AsrSettingsBase):
    def test_a_test_take_reports_transcript_language_and_latency(self):
        answer = self.client.post("/api/settings/asr/presets/local/test", headers=self.headers,
                                  content=b"audio", params={})
        self.assertEqual(200, answer.status_code, answer.text)
        self.assertEqual({"preset": "local", "text": "hi there", "language": "en", "duration": 0.0,
                          "segments": [], "latency_ms": 250}, answer.json())
        self.assertEqual(404, self.client.post("/api/settings/asr/presets/x/test", headers=self.headers,
                                               content=b"a").status_code)
        self.assertEqual(400, self.client.post("/api/settings/asr/presets/local/test",
                                               headers=self.headers).status_code)

    def test_unavailable_and_failed_takes(self):
        self.create("gone", argv=["/no/such/recognizer"])
        self.assertEqual(503, self.client.post("/api/settings/asr/presets/gone/test", headers=self.headers,
                                               content=b"a").status_code)
        self.create("fails", argv=[sys.executable, "-c", "raise SystemExit(3)"])
        failed = self.client.post("/api/settings/asr/presets/fails/test", headers=self.headers, content=b"a")
        self.assertEqual(502, failed.status_code)
        registry = asr_presets.shared_registry(self.db)
        flaky = mock.Mock(kind="command")
        flaky.status.return_value = {"available": True, "reason": None, "model": None}
        flaky.transcribe.side_effect = TranscriberUnavailable("gpu gone")
        registry.entries["fails"] = flaky
        self.assertEqual(503, self.client.post("/api/settings/asr/presets/fails/test", headers=self.headers,
                                               content=b"a").status_code)


class SecretTest(AsrSettingsBase):
    def test_the_key_never_appears_in_any_response_row_or_log(self):
        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger("partyline").debug("probe")
            bodies = [
                self.create("mine", kind="openai-compatible", base_url="https://api.example.test",
                            model="whisper-1", api_key_env="ASR_TEST_KEY").text,
                self.client.get("/api/settings/asr", headers=self.headers).text,
                self.client.get("/api/transcribe/presets", headers=self.headers).text,
            ]
        for body in [*bodies, "\n".join(logs.output)]:
            self.assertNotIn(SENTINEL, body)
        with self.db.lock:
            dump = "\n".join(self.db.conn.iterdump())
        self.assertNotIn(SENTINEL, dump)
        self.assertIn("ASR_TEST_KEY", dump)

    def test_key_shaped_values_are_refused(self):
        attempts = [
            {"api_key": SENTINEL},
            {"api_key_env": SENTINEL},
            {"api_key_env": "gsk_lowercasekeymaterial"},
        ]
        for extra in attempts:
            answer = self.client.post("/api/settings/asr/presets", headers=self.headers, json={
                "name": "leak", "kind": "openai-compatible",
                "fields": {"base_url": "https://api.example.test", "model": "m", **extra}})
            self.assertEqual(422, answer.status_code, extra)
            self.assertNotIn(SENTINEL, answer.text)
        for url in ("https://user:pw@api.example.test", "https://api.example.test/?key=abc"):
            answer = self.create("leak", kind="openai-compatible", base_url=url, model="m")
            self.assertEqual(422, answer.status_code, url)
        self.assertIsNone(asr_store.get_preset(self.db, "leak"))

    def test_unset_key_shows_unset_and_never_a_value(self):
        del os.environ["ASR_TEST_KEY"]
        cloud = self.client.get("/api/settings/asr", headers=self.headers).json()["presets"][1]
        self.assertEqual((False, False), (cloud["key_set"], cloud["available"]))
        self.assertIn("ASR_TEST_KEY", cloud["reason"])


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class OpenAIResponseFormatTest(unittest.TestCase):
    def call(self, backend, answer):
        seen = {}

        def urlopen(request, timeout):
            seen["body"] = request.data.decode("utf-8", "replace")
            seen["auth"] = request.headers.get("Authorization")
            if isinstance(answer, Exception):
                raise answer
            return FakeResponse(json.dumps(answer).encode())

        with mock.patch.dict(os.environ, {"ASR_TEST_KEY": SENTINEL}), \
                mock.patch("partyline.asr_backends.urllib.request.urlopen", urlopen):
            return backend.transcribe(b"audio", "audio/webm"), seen

    def test_json_format_without_segments_and_passed_through_fields(self):
        backend = OpenAICompatible("https://api.example.test", "gpt-4o-transcribe", "ASR_TEST_KEY",
                                   response_format="json", language="de", prompt="Partyline, Svelte")
        result, seen = self.call(backend, {"text": " Hallo Welt ", "usage": {"type": "tokens"}})
        self.assertEqual(("Hallo Welt", "de", 0.0, ()), (result.text, result.language, result.duration,
                                                          result.segments))
        for field, value in (("response_format", "json"), ("language", "de"), ("prompt", "Partyline, Svelte"),
                             ("model", "gpt-4o-transcribe")):
            self.assertIn(f'name="{field}"\r\n\r\n{value}\r\n', seen["body"])
        self.assertEqual("Bearer " + SENTINEL, seen["auth"])

    def test_default_stays_verbose_json_and_omits_unset_fields(self):
        backend = OpenAICompatible("https://api.example.test", "whisper-1")
        result, seen = self.call(backend, {"text": "hi", "language": "english", "duration": 1.5,
                                           "segments": [{"start": 0, "end": 1.5, "text": "hi"}]})
        self.assertIn('name="response_format"\r\n\r\nverbose_json\r\n', seen["body"])
        self.assertNotIn('name="language"', seen["body"])
        self.assertEqual((1, "english"), (len(result.segments), result.language))

    def test_service_errors_explain_without_leaking_the_key(self):
        def http_error(code, message):
            body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
            return urllib.error.HTTPError("u", code, "x", {}, body)

        backend = OpenAICompatible("https://api.example.test", "gpt-4o-transcribe", "ASR_TEST_KEY")
        expectations = [
            (http_error(400, "response_format 'verbose_json' is not compatible. Use 'json' or 'text'"),
             "Use 'json' or 'text'"),
            (http_error(401, f"Incorrect API key provided: {SENTINEL}"), "refused the API key"),
            (http_error(500, f"echo {SENTINEL}"), "[redacted]"),
            (urllib.error.HTTPError("u", 502, "x", {}, io.BytesIO(b"<html>")), "answered 502"),
        ]
        for error, expected in expectations:
            with self.assertRaises(TakeFailed) as ctx:
                self.call(backend, error)
            self.assertIn(expected, str(ctx.exception))
            self.assertNotIn(SENTINEL, str(ctx.exception))

    def test_toml_accepts_the_new_fields(self):
        registry = asr_presets.build_registry({"asr": [
            {"name": "4o", "kind": "openai-compatible", "base_url": "https://api.openai.com",
             "model": "gpt-4o-transcribe", "response_format": "json", "api_key_env": "OPENAI_API_KEY"}]}, {})
        self.assertEqual("json", registry.get("4o").response_format)
        with self.assertRaises(ValueError):
            asr_presets.build_registry({"asr": [
                {"name": "x", "kind": "openai-compatible", "base_url": "https://a.test", "model": "m",
                 "response_format": "text"}]}, {})


if __name__ == "__main__":
    unittest.main()
