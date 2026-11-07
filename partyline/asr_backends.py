"""Speech-recognition backends that are not the built-in local model.

``openai-compatible`` posts the take to ``{base_url}/v1/audio/transcriptions``
(OpenAI, Groq, or a self-hosted server); the key is read from a named
environment variable and never stored. ``command`` runs a configured argv on a
temporary copy of the audio and reads JSON from stdout. The copy exists only
for the call and is removed on every path.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .transcript import TakeFailed, Transcript, TranscriberUnavailable

_SUFFIX = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/wav": ".wav"}


def _finite(value: Any) -> float:
    number = float(value)  # TypeError/ValueError for anything not number-like
    if not math.isfinite(number):
        raise ValueError("not finite")
    return number


def parse_payload(payload: Any, fallback_language: str = "") -> Transcript:
    """Normalise ``{text, language?, duration?, segments?}`` from any backend.

    A recognizer's output is outside our control, so any wrong shape fails the
    take (``TakeFailed``) rather than surfacing as a server error.
    """
    bad = TakeFailed("the recognizer returned malformed JSON (segments need finite start and end)", 502)
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise TakeFailed("the recognizer did not return a JSON object with text", 502)
    raw = payload.get("segments")
    if raw is not None and not isinstance(raw, list):
        raise bad
    segments = []
    try:
        for seg in raw or []:
            segments.append({"start": round(_finite(seg["start"]), 3), "end": round(_finite(seg["end"]), 3),
                             "text": str(seg.get("text", "")).strip()})
        duration = _finite(payload.get("duration") or 0)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise bad from None
    duration = duration or (max((s["end"] for s in segments), default=0.0))
    language = payload.get("language")
    return Transcript(payload["text"].strip(), language if isinstance(language, str) else fallback_language,
                      round(duration, 2), tuple(segments))


class OpenAICompatible:
    kind = "openai-compatible"

    def __init__(self, base_url: str, model: str, api_key_env: str | None = None, timeout: float = 120.0,
                 response_format: str = "verbose_json", language: str | None = None,
                 prompt: str | None = None):
        self.url = base_url.rstrip("/") + "/v1/audio/transcriptions"
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout
        # whisper-1 answers verbose_json (segments); gpt-4o-*-transcribe refuse it and need json.
        self.response_format = response_format
        self.language = language
        self.prompt = prompt

    def status(self) -> dict[str, Any]:
        if self.api_key_env and not os.environ.get(self.api_key_env):
            return {"available": False, "reason": f"set the {self.api_key_env} environment variable",
                    "model": self.model}
        return {"available": True, "reason": None, "model": self.model}

    def transcribe(self, data: bytes, mime: str = "") -> Transcript:
        state = self.status()
        if not state["available"]:
            raise TranscriberUnavailable(state["reason"])
        boundary = uuid.uuid4().hex
        fields = {"model": self.model, "response_format": self.response_format}
        fields.update({k: v for k, v in (("language", self.language), ("prompt", self.prompt)) if v})
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in fields.items()]
        suffix = _SUFFIX.get(mime.split(";")[0], ".webm")
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="take{suffix}"'
                f'\r\nContent-Type: {mime or "audio/webm"}\r\n\r\n')
        parts.append(head.encode() + data + f"\r\n--{boundary}--\r\n".encode())
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self.api_key_env:
            headers["Authorization"] = f"Bearer {os.environ[self.api_key_env]}"
        req = urllib.request.Request(self.url, b"".join(parts), headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - operator-set URL
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise TakeFailed(_http_failure(exc, headers.get("Authorization", "")), 502) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TakeFailed(f"could not reach the speech service: {exc}", 502) from exc
        return parse_payload(payload, self.language or "")


def _http_failure(exc: urllib.error.HTTPError, secret: str) -> str:
    """The service's own complaint (e.g. "Use 'json' or 'text'"), never anything key-shaped."""
    if exc.code in (401, 403):
        return f"the speech service refused the API key ({exc.code})"
    try:
        body = json.loads(exc.read() or b"null")
        detail = body.get("error", {}).get("message") if isinstance(body, dict) else None
    except (ValueError, OSError, AttributeError):
        detail = None
    if not isinstance(detail, str) or not detail.strip():
        return f"the speech service answered {exc.code}"
    token = secret.removeprefix("Bearer ")
    detail = detail.replace(token, "[redacted]") if token else detail
    return f"the speech service answered {exc.code}: {detail.strip()[:200]}"


class Command:
    kind = "command"

    def __init__(self, argv: list[str], timeout: float = 300.0):
        self.argv = argv
        self.timeout = timeout
        self._lock = threading.Lock()  # a command may hold the GPU: one take at a time

    def status(self) -> dict[str, Any]:
        exe = self.argv[0]
        found = Path(exe).is_file() if os.sep in exe else shutil.which(exe)
        if not found:
            return {"available": False, "reason": f"command not found: {exe}", "model": None}
        return {"available": True, "reason": None, "model": None}

    def transcribe(self, data: bytes, mime: str = "") -> Transcript:
        state = self.status()
        if not state["available"]:
            raise TranscriberUnavailable(state["reason"])
        with self._lock:
            workdir = tempfile.mkdtemp(prefix="partyline-asr-")  # mode 0700
            try:
                audio = Path(workdir) / f"take{_SUFFIX.get(mime.split(';')[0], '.webm')}"
                audio.write_bytes(data)
                argv = [a.replace("{audio}", str(audio)) for a in self.argv]
                try:
                    done = subprocess.run(  # noqa: S603 - argv, never a shell
                        argv, capture_output=True, timeout=self.timeout,
                        stdin=subprocess.DEVNULL, cwd=workdir)
                except subprocess.TimeoutExpired as exc:
                    raise TakeFailed(f"the recognizer timed out after {self.timeout:g}s", 502) from exc
                except OSError as exc:
                    raise TranscriberUnavailable(f"could not run the recognizer: {exc}") from exc
                if done.returncode != 0:
                    tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
                    raise TakeFailed(f"the recognizer exited {done.returncode}: {tail[0][:200]}", 502)
                try:
                    payload = json.loads(done.stdout)
                except ValueError as exc:
                    raise TakeFailed("the recognizer did not print valid JSON", 502) from exc
                return parse_payload(payload)
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
