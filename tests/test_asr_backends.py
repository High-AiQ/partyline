"""Pluggable speech recognition: presets, HTTP and command backends, VTT.

Everything is faked: a local HTTP server stands in for a speech service and
tiny scripts stand in for a recognizer. No model is loaded.
"""

import glob
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from partyline.asr_backends import Command, OpenAICompatible, parse_payload
from partyline.asr_presets import build_registry
from partyline.transcript import (
    TakeFailed, Transcript, TranscriberUnavailable, WhisperRetired, segments_to_vtt,
)
from partyline.transcriber import Transcriber


class VttTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(segments_to_vtt([]), "WEBVTT\n")

    def test_cues_and_hours(self):
        out = segments_to_vtt([
            {"start": 0, "end": 1.5, "text": "hi"},
            {"start": 3599.9996, "end": 3725.042, "text": "late\n\nwords --> here"},
        ])
        self.assertEqual(out, (
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nhi\n\n"
            "01:00:00.000 --> 01:02:05.042\nlate\nwords -> here\n"))


class Handler(BaseHTTPRequestHandler):
    seen = []
    answer = None

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Handler.seen.append((self.path, self.headers.get("Authorization"), body))
        code, payload = Handler.answer
        self.send_response(code)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class OpenAITest(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 0.5
        self.addCleanup(self.server.server_close)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        Handler.seen = []

    @contextmanager
    def answer(self, code, payload):
        Handler.answer = (code, payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        worker = threading.Thread(target=self.server.handle_request, daemon=True)
        worker.start()
        try:
            yield
        finally:
            worker.join(timeout=0.6)
            self.assertFalse(worker.is_alive())

    @contextmanager
    def redirect_openai(self):
        urlopen = urllib.request.urlopen

        def redirect(request, *, timeout):
            self.assertEqual(request.full_url, "https://api.openai.com/v1/audio/transcriptions")
            local = urllib.request.Request(self.base + request.selector, request.data, request.headers,
                                           method=request.method)
            return urlopen(local, timeout=timeout)

        with mock.patch("partyline.asr_backends.urllib.request.urlopen", redirect):
            yield

    def test_posts_audio_with_key_from_env(self):
        backend = OpenAICompatible(self.base + "/", "whisper-1", "KEY_VAR", timeout=0.5)
        self.assertIn("KEY_VAR", backend.status()["reason"])
        with self.assertRaises(TranscriberUnavailable):
            backend.transcribe(b"audio")
        with self.answer(200, {"text": " hi ", "language": "en", "duration": 2.0,
                               "segments": [{"start": 0, "end": 2, "text": "hi"}]}), \
                mock.patch.dict(os.environ, {"KEY_VAR": "sekret"}):
            out = backend.transcribe(b"audio-bytes", "audio/webm;codecs=opus")
        path, auth, body = Handler.seen[0]
        self.assertEqual((path, auth), ("/v1/audio/transcriptions", "Bearer sekret"))
        self.assertIn(b"audio-bytes", body)
        self.assertIn(b"whisper-1", body)
        self.assertIn(b'name="response_format"\r\n\r\nverbose_json\r\n', body)
        self.assertEqual((out.text, out.language, out.duration), ("hi", "en", 2.0))
        self.assertEqual(out.segments[0]["end"], 2.0)

    def test_errors_are_unavailable(self):
        backend = OpenAICompatible(self.base, "m", timeout=0.5)
        with self.answer(500, b"nope"), self.assertRaisesRegex(TakeFailed, "500"):
            backend.transcribe(b"explode")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")), \
                self.assertRaisesRegex(TakeFailed, "could not reach"):
            backend.transcribe(b"x")

    def test_gpt_transcribe_posts_json_and_language_array(self):
        backend = OpenAICompatible("https://api.openai.com", "gpt-transcribe", timeout=0.5,
                                   language="en", prompt="Partyline recording")
        with self.answer(200, {"text": " Salut ", "languages": [{"code": "fr"}]}), self.redirect_openai():
            result = backend.transcribe(b"audio-bytes", "audio/wav")
        self.assertEqual(result, Transcript("Salut", "fr", 0.0))
        path, _, body = Handler.seen[0]
        self.assertEqual(path, "/v1/audio/transcriptions")
        for field, value in (("model", "gpt-transcribe"), ("response_format", "json"),
                             ("languages[]", "en"), ("prompt", "Partyline recording")):
            self.assertIn(f'name="{field}"\r\n\r\n{value}\r\n'.encode(), body)
        self.assertNotIn(b'name="language"', body)
        self.assertIn(b'name="file"; filename="take.wav"\r\nContent-Type: audio/wav\r\n\r\naudio-bytes', body)

    def test_openai_whisper_retirement_has_actionable_detail(self):
        backend = OpenAICompatible("https://api.openai.com", "whisper-1", timeout=0.5)
        cases = [(400, {"code": "model_deprecated"}), (410, {}),
                 (404, {"code": "model_not_found", "message": "The whisper-1 model has been retired"})]
        for status, error in cases:
            with self.subTest(status=status), self.answer(status, {"error": error}), self.redirect_openai(), \
                    self.assertRaises(WhisperRetired) as caught:
                backend.transcribe(b"audio")
            self.assertEqual(caught.exception.status, 502)
            self.assertEqual(
                str(caught.exception),
                "model whisper-1 is retired; switch the preset to gpt-transcribe in Settings → Voice")

    def test_whisper_retirement_detail_is_specific_to_openai(self):
        retired = {"error": {"code": "model_deprecated", "message": "whisper-1 retired by this provider"}}
        backend = OpenAICompatible(self.base, "whisper-1", timeout=0.5)
        with self.answer(400, retired), self.assertRaisesRegex(TakeFailed, "retired by this provider"):
            backend.transcribe(b"audio")
        unavailable = {"error": {"code": "model_not_found", "message": "No access to model whisper-1"}}
        backend = OpenAICompatible("https://api.openai.com", "whisper-1", timeout=0.5)
        with self.answer(404, unavailable), self.redirect_openai(), \
                self.assertRaisesRegex(TakeFailed, "No access to model whisper-1"):
            backend.transcribe(b"audio")


class CommandTest(unittest.TestCase):
    def script(self, body):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = os.path.join(d.name, "asr.py")
        with open(path, "w") as f:
            f.write(body)
        return [sys.executable, path, "{audio}"]

    def leftovers(self):
        return glob.glob(os.path.join(tempfile.gettempdir(), "partyline-asr-*"))

    def test_json_from_stdout_and_temp_removed(self):
        argv = self.script(
            "import sys,json,os\n"
            "assert os.path.exists(sys.argv[1]) and sys.argv[1].endswith('.webm')\n"
            "assert open(sys.argv[1],'rb').read()==b'raw'\n"
            "print(json.dumps({'text':'ok','segments':[{'start':0,'end':4,'text':'ok'}]}))\n")
        before = set(self.leftovers())
        out = Command(argv).transcribe(b"raw", "audio/webm")
        self.assertEqual((out.text, out.language, out.duration), ("ok", "", 4.0))
        self.assertEqual(set(self.leftovers()), before)

    def test_failures_and_cleanup(self):
        before = set(self.leftovers())
        cases = {
            "import sys; sys.stderr.write('boom\\n'); sys.exit(3)": "exited 3: boom",
            "print('not json')": "valid JSON",
            "print('[1]')": "JSON object",
        }
        for code, message in cases.items():
            cmd = Command(self.script(code), timeout=1)
            with self.assertRaisesRegex(TakeFailed, message):
                cmd.transcribe(b"x")
        self.assertEqual(set(self.leftovers()), before)

    def test_timeout_is_a_failed_take(self):
        import subprocess

        before = set(self.leftovers())
        expired = subprocess.TimeoutExpired(["asr"], 3)
        with mock.patch("subprocess.run", side_effect=expired):
            with self.assertRaisesRegex(TakeFailed, "timed out after 3s"):
                Command([sys.executable, "{audio}"], timeout=3).transcribe(b"x")
        self.assertEqual(set(self.leftovers()), before)

    def test_missing_command(self):
        for exe in ("definitely-not-installed", "/no/such/tool"):
            cmd = Command([exe, "{audio}"])
            self.assertFalse(cmd.status()["available"])
            with self.assertRaises(TranscriberUnavailable):
                cmd.transcribe(b"x")
        broken = Command([sys.executable])
        with mock.patch("subprocess.run", side_effect=OSError("denied")):
            with self.assertRaisesRegex(TranscriberUnavailable, "denied"):
                broken.transcribe(b"x")


class PayloadTest(unittest.TestCase):
    def test_silence_and_confidence_filtering(self):
        for phrase in ("YOU!", "Thank you.", "Thanks for watching!", "Bye."):
            out = parse_payload({"text": phrase, "segments": [{"start": 0, "end": 2, "text": phrase}]})
            self.assertEqual((out.text, out.segments), ("", ()))
        segments = [
            {"start": 0, "end": 1, "text": "noise", "no_speech_prob": 0.9, "avg_logprob": -1.5},
            {"start": 1, "end": 2, "text": "thank you for helping", "no_speech_prob": 0.9,
             "avg_logprob": -0.2},
        ]
        out = parse_payload({"text": "noise thank you for helping", "segments": segments})
        self.assertEqual(out.text, "thank you for helping")
        self.assertEqual(len(out.segments), 1)
        self.assertEqual(parse_payload({"text": "Thank you for helping"}).text, "Thank you for helping")
        self.assertEqual(parse_payload({"text": "Thanks for watching!", "languages": []}).text, "")

    def test_tolerant_parse(self):
        out = parse_payload({"text": "a", "language": 3, "duration": None,
                             "segments": [{"start": 0, "end": 2, "text": " b "}]}, "xx")
        self.assertEqual((out.language, out.duration, len(out.segments)), ("xx", 2.0, 1))

    def test_malformed_shapes_fail_the_take(self):
        bad = [
            {"text": "a", "segments": 42},
            {"text": "a", "segments": "x"},
            {"text": "a", "segments": [1]},
            {"text": "a", "segments": [{"start": 1}]},
            {"text": "a", "segments": [{"start": "x", "end": 2}]},
            {"text": "a", "segments": [{"start": float("nan"), "end": 2}]},
            {"text": "a", "segments": [{"start": 0, "end": float("inf")}]},
            {"text": "a", "duration": float("nan")},
            {"text": "a", "duration": "long"},
        ]
        for payload in bad:
            with self.assertRaises(TakeFailed, msg=str(payload)) as ctx:
                parse_payload(payload)
            self.assertEqual(ctx.exception.status, 502)

    def test_command_with_nan_json_is_a_failed_take(self):
        argv = [sys.executable, "-c",
                "print('{\"text\":\"a\",\"segments\":[{\"start\":NaN,\"end\":1}]}')"]
        with self.assertRaises(TakeFailed):
            Command(argv).transcribe(b"x")


class RegistryTest(unittest.TestCase):
    def test_default_from_env_is_local_whisper(self):
        reg = build_registry({}, {"PARTYLINE_TRANSCRIBE_MAX_BYTES": "5"})
        self.assertIsInstance(reg.get(None), Transcriber)
        self.assertEqual((reg.default, reg.max_bytes), ("faster-whisper", 5))

    def test_configured_presets_in_order(self):
        reg = build_registry({"asr": [
            {"name": "gpu", "kind": "faster-whisper", "model": "tiny", "device": "cpu",
             "compute_type": "int8"},
            {"name": "cloud", "kind": "openai-compatible", "base_url": "http://x", "model": "m",
             "api_key_env": "NOPE_KEY_ENV", "timeout": 5},
            {"name": "wx", "kind": "command", "argv": ["no-such-bin", "{audio}"]},
        ]}, {})
        self.assertEqual(reg.default, "gpu")
        listing = {p["name"]: p for p in reg.listing()["presets"]}
        self.assertEqual(listing["gpu"]["kind"], "faster-whisper")
        self.assertIn("NOPE_KEY_ENV", listing["cloud"]["reason"])
        self.assertIn("not found", listing["wx"]["reason"])
        self.assertEqual(reg.get("gpu").settings.compute_type, "int8")
        with self.assertRaises(KeyError):
            reg.get("missing")
        reg.release()

    def test_bad_config_is_refused(self):
        bad = [
            {"asr": "x"}, {"asr": ["x"]}, {"asr": [{"kind": "command"}]},
            {"asr": [{"name": "a", "kind": "tpu"}]},
            {"asr": [{"name": "a", "kind": "command", "argv": []}]},
            {"asr": [{"name": "a", "kind": "command", "argv": ["x"], "timeout": -1}]},
            {"asr": [{"name": "a", "kind": "openai-compatible", "model": "m"}]},
            {"asr": [{"name": "a", "kind": "command", "argv": ["x"]},
                     {"name": "a", "kind": "command", "argv": ["x"]}]},
        ]
        for config in bad:
            with self.assertRaises(ValueError, msg=str(config)):
                build_registry(config, {})
