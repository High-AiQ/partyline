"""Voice input: the transcriber's lifecycle and its HTTP surface.

No model is ever loaded here; a fake stands in for faster-whisper.
"""

import contextlib
import io
import tempfile
import threading
import unittest
from unittest import mock
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.bind import uvicorn_config
from partyline.db import Db
from partyline.runtime import ChatRuntime
from partyline.transcribe_routes import transcribe_router
from partyline.transcriber import (
    CPU_MODEL, GPU_MODEL, INSTALL_HINT, TranscribeSettings, Transcriber,
    TranscriberUnavailable,
)
from partyline.transcript import TakeFailed, WhisperRetired
from partyline.asr_presets import AsrRegistry


class FakeModel:
    def __init__(self):
        self.busy = 0
        self.peak = 0
        self.calls = 0
        self.gate = None  # an Event a test holds closed to keep a take inside the model
        self.entered = threading.Event()  # set once a take is inside the model

    def transcribe(self, audio, **kwargs):
        self.busy += 1
        self.peak = max(self.peak, self.busy)
        self.calls += 1
        self.entered.set()
        if self.gate is not None:
            self.gate.wait()
        self.busy -= 1
        seg = SimpleNamespace(start=0.0, end=1.234, text=" hello there ")
        return iter([seg]), SimpleNamespace(language="en", duration=1.5)


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def engine(**kw):
    loads = []
    model = FakeModel()

    def factory(name, device, compute, root):
        loads.append((name, device, compute, root))
        return model

    kw.setdefault("installed", lambda: True)
    kw.setdefault("cuda", lambda: False)
    return Transcriber(kw.pop("settings", TranscribeSettings()), factory=factory, **kw), loads, model


class TranscriberTest(unittest.TestCase):
    def test_fake_model_silence_and_confidence(self):
        t, _, model = engine()
        model.transcribe = lambda *a, **k: (iter([
            SimpleNamespace(start=0, end=1, text="noise", no_speech_prob=0.9, avg_logprob=-2),
            SimpleNamespace(start=1, end=2, text="You.", no_speech_prob=0.1, avg_logprob=-0.2),
        ]), SimpleNamespace(language="en", duration=2))
        out = t.transcribe(b"fake")
        self.assertEqual((out.text, out.segments), ("", ()))

    def test_cpu_plan_and_result(self):
        t, loads, _ = engine()
        out = t.transcribe(b"x")
        self.assertEqual((out.text, out.language, out.duration), ("hello there", "en", 1.5))
        self.assertEqual(out.segments[0], {"start": 0.0, "end": 1.234, "text": "hello there"})
        self.assertEqual(loads, [(CPU_MODEL, "cpu", "int8", None)])
        t.unload_if_idle()

    def test_gpu_plan_and_overrides(self):
        t, loads, _ = engine(cuda=lambda: True, settings=TranscribeSettings(model_dir="/m"))
        t.transcribe(b"x")
        t2, loads2, _ = engine(settings=TranscribeSettings(model="tiny", device="cpu"))
        t2.transcribe(b"x")
        self.assertEqual(loads, [(GPU_MODEL, "cuda", "float16", "/m")])
        self.assertEqual(loads2[0][0], "tiny")
        self.assertEqual(t.status()["model"], GPU_MODEL)
        t.unload_if_idle()
        t2.unload_if_idle()

    def test_lazy_load_and_reuse(self):
        t, loads, _ = engine()
        self.assertFalse(t.loaded)
        t.transcribe(b"x")
        t.transcribe(b"x")
        self.assertEqual(len(loads), 1)

    def test_unavailable_paths(self):
        t, _, _ = engine(installed=lambda: False)
        self.assertEqual(t.status(), {"available": False, "reason": INSTALL_HINT, "model": None})
        with self.assertRaises(TranscriberUnavailable):
            t.transcribe(b"x")
        bad, _, _ = engine(settings=TranscribeSettings(device="tpu"))
        self.assertFalse(bad.status()["available"])
        boom = Transcriber(installed=lambda: True, cuda=lambda: False,
                           factory=lambda *a: (_ for _ in ()).throw(OSError("offline")))
        with self.assertRaisesRegex(TranscriberUnavailable, "offline"):
            boom.transcribe(b"x")
        self.assertFalse(boom.loaded)

    def test_decode_failure_is_unavailable(self):
        t, _, model = engine()
        model.transcribe = lambda *a, **k: (_ for _ in ()).throw(ValueError("bad audio"))
        with self.assertRaisesRegex(TakeFailed, "bad audio"):
            t.transcribe(b"x")

    def test_takes_are_serialized(self):
        t, loads, model = engine()
        model.gate = threading.Event()
        attempts = threading.Semaphore(0)
        real = t._lock

        class CountingLock:
            """Signals each time a take reaches for the lock, so no test waits on a clock."""

            def __enter__(self):
                attempts.release()
                real.acquire()

            def __exit__(self, *exc):
                real.release()

            def acquire(self, *args, **kwargs):
                return real.acquire(*args, **kwargs)

            def release(self):
                real.release()

        t._lock = CountingLock()
        threads = [threading.Thread(target=t.transcribe, args=(b"x",)) for _ in range(4)]
        for th in threads:
            th.start()
        for _ in threads:
            self.assertTrue(attempts.acquire(timeout=30))
        self.assertTrue(model.entered.wait(timeout=30))
        # All four have reached the lock while the first is held inside the model.
        self.assertEqual((model.calls, model.peak), (1, 1))
        model.gate.set()
        for th in threads:
            th.join()
        self.assertEqual((model.peak, model.calls, len(loads)), (1, 4, 1))

    def test_idle_unload_by_clock(self):
        clock = Clock()
        t, _, _ = engine(clock=clock, settings=TranscribeSettings(idle_seconds=600))
        t.transcribe(b"x")
        clock.now = 599
        self.assertFalse(t.unload_if_idle())
        self.assertTrue(t.loaded)
        clock.now = 601
        self.assertTrue(t.unload_if_idle())
        self.assertFalse(t.loaded)
        self.assertFalse(t.unload_if_idle())

    def test_idle_unload_by_timer_and_busy_lock(self):
        armed = []

        class FakeTimer:
            def __init__(self, interval, function):
                self.interval, self.function, self.cancelled = interval, function, False
                self.daemon = False
                armed.append(self)

            def start(self):
                pass

            def cancel(self):
                self.cancelled = True

        clock = Clock()
        with mock.patch("partyline.transcriber.threading.Timer", FakeTimer):
            t, _, _ = engine(clock=clock, settings=TranscribeSettings(idle_seconds=600))
            t.transcribe(b"x")
            self.assertEqual((len(armed), armed[0].interval), (1, 600))
            t.transcribe(b"x")
            self.assertTrue(armed[0].cancelled)
            clock.now = 601
            armed[-1].function()
            self.assertFalse(t.loaded)
            t2, _, _ = engine(clock=clock, settings=TranscribeSettings(idle_seconds=600))
            t2.transcribe(b"x")
            clock.now = 2000
            with t2._lock:
                self.assertFalse(t2.unload_if_idle())
            self.assertTrue(t2.loaded)

    def test_settings_from_env(self):
        s = TranscribeSettings.from_env({
            "PARTYLINE_TRANSCRIBE_MODEL": "base", "PARTYLINE_TRANSCRIBE_DEVICE": "CPU",
            "PARTYLINE_TRANSCRIBE_MODEL_DIR": "/m", "PARTYLINE_TRANSCRIBE_IDLE_SECONDS": "30",
            "PARTYLINE_TRANSCRIBE_MAX_BYTES": "nope"})
        self.assertEqual((s.model, s.device, s.model_dir, s.idle_seconds), ("base", "cpu", "/m", 30))
        self.assertEqual(TranscribeSettings.from_env({}).device, "auto")


class TranscribeRouteTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.engine, self.loads, _ = engine(settings=TranscribeSettings(max_bytes=1000))
        app = FastAPI()
        install_auth_guard(app, self.db)
        self.registry = AsrRegistry([("local", self.engine)], max_bytes=1000)
        app.include_router(transcribe_router(self.runtime, lambda: self.registry))
        self.client = TestClient(app)
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("other", "Other")
        user = auth_store.create_user(
            self.db, "a@example.com", "ann", auth_tokens.hash_password("hunter2222"))
        access = auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), user["id"])
        self.human = {"Authorization": f"Bearer {access}"}

    def tearDown(self):
        self.engine.unload_if_idle()
        self.engine._cancel_timer()
        self.db.close()
        self.directory.cleanup()

    def post(self, body=b"audio", conv="line", headers=None):
        return self.client.post(f"/api/conversations/{conv}/transcribe", content=body,
                                headers=headers or self.human)

    def test_transcribes_and_discards(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["text"], "hello there")
        self.assertEqual(r.json()["segments"][0]["end"], 1.234)
        self.assertEqual(self.db._exec("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_logs_one_line_per_take_without_the_words(self):
        # Through the server's real logging setup, not assertLogs, which would enable INFO itself.
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            uvicorn_config(object(), "127.0.0.1", 8642, {})
            self.post()
            self.engine._model = SimpleNamespace(
                transcribe=lambda *a, **k: (iter([]), SimpleNamespace(language="en", duration=2.0)))
            self.post()
            self.engine._model = SimpleNamespace(transcribe=lambda *a, **k: (_ for _ in ()).throw(
                ValueError("failed on: MY PRIVATE\nSPOKEN WORDS")))
            self.post()
            self.engine._model = None
            self.engine._factory = lambda *a: (_ for _ in ()).throw(OSError("no model: SPOKEN\nWORDS"))
            self.post()
        lines = [x for x in (err.getvalue() + out.getvalue()).splitlines() if "transcribe line=" in x]
        self.assertEqual(len(lines), 4)
        for part in ("line=line", "preset=local", "bytes=5", "audio=1.5s", "chars=11"):
            self.assertIn(part, lines[0])
        self.assertIn("chars=0 empty=true", lines[1])
        self.assertIn("error=take-failed status=422", lines[2])
        self.assertIn("error=unavailable", lines[3])
        logged = err.getvalue() + out.getvalue()
        for secret in ("hello", "PRIVATE", "SPOKEN", "WORDS", "no model"):
            self.assertNotIn(secret, logged)

    def test_requires_auth_and_line(self):
        r = self.client.post("/api/conversations/line/transcribe", content=b"x")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.post(conv="missing").status_code, 404)

    def test_retired_whisper_detail_reaches_the_composer_and_server_log(self):
        with mock.patch.object(self.engine, "transcribe", side_effect=WhisperRetired()), \
                self.assertLogs("partyline.transcribe_routes", "WARNING") as log:
            response = self.post()
        detail = "model whisper-1 is retired; switch the preset to gpt-transcribe in Settings → Voice"
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": detail})
        self.assertEqual(len(log.output), 1)
        self.assertIn(detail, log.output[0])

    def test_machine_scope(self):
        self.db.add_attachment("m1", "other", "bot", "fake", ["fake"], "/tmp")
        self.db.set_attachment_status("m1", "running", "owner")
        machine = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "m1")}
        self.assertEqual(self.post(conv="line", headers=machine).status_code, 403)
        self.assertEqual(self.post(conv="other", headers=machine).status_code, 200)

    def test_size_cap(self):
        self.assertEqual(self.post(b"x" * 1001).status_code, 413)
        self.assertEqual(self.post(b"x" * 1000).status_code, 200)

        def chunks():
            yield b"x" * 600
            yield b"x" * 600
        r = self.client.post("/api/conversations/line/transcribe", content=chunks(), headers=self.human)
        self.assertEqual(r.status_code, 413)
        self.assertEqual(self.post(b"").status_code, 400)

    def test_unavailable_is_503_with_reason(self):
        self.engine._installed = lambda: False
        r = self.post()
        self.assertEqual((r.status_code, r.json()["detail"]), (503, INSTALL_HINT))
        row = self.client.get("/api/transcribe/presets", headers=self.human).json()["presets"][0]
        self.assertEqual((row["available"], row["reason"]), (False, INSTALL_HINT))
        self.engine._installed = lambda: True
        self.engine._factory = lambda *a: (_ for _ in ()).throw(OSError("no model"))
        r = self.post()
        self.assertEqual(r.status_code, 503)
        self.assertIn("no model", r.json()["detail"])

    def test_take_failures_are_not_503(self):
        self.engine._model = None
        self.engine._factory = lambda *a: SimpleNamespace(
            transcribe=lambda *a, **k: (_ for _ in ()).throw(ValueError("corrupt")))
        r = self.post()
        self.assertEqual((r.status_code, "corrupt" in r.json()["detail"]), (422, True))
        for status in (422, 502):
            backend = SimpleNamespace(
                kind="command", status=lambda: {"available": True, "reason": None, "model": None},
                transcribe=lambda *a, status=status: (_ for _ in ()).throw(TakeFailed("bad take", status)))
            self.registry.entries["flaky"] = backend
            r = self.client.post("/api/conversations/line/transcribe?preset=flaky", content=b"x",
                                 headers=self.human)
            self.assertEqual((r.status_code, r.json()["detail"]), (status, "bad take"))
        self.assertEqual(self.engine.status()["available"], True)

    def test_presets_listing_and_unknown_preset(self):
        s = self.client.get("/api/transcribe/presets", headers=self.human).json()
        self.assertEqual(s["default"], "local")
        self.assertEqual((s["presets"][0]["available"], s["presets"][0]["model"]), (True, CPU_MODEL))
        r = self.client.post(
            "/api/conversations/line/transcribe?preset=nope", content=b"x", headers=self.human)
        self.assertEqual(r.status_code, 404)

    def test_vtt_format(self):
        r = self.client.post(
            "/api/conversations/line/transcribe?format=vtt", content=b"x", headers=self.human)
        self.assertEqual(r.headers["content-type"].split(";")[0], "text/vtt")
        self.assertEqual(r.text, "WEBVTT\n\n00:00:00.000 --> 00:00:01.234\nhello there\n")
        bad = self.client.post(
            "/api/conversations/line/transcribe?format=srt", content=b"x", headers=self.human)
        self.assertEqual(bad.status_code, 400)
