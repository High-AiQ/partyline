"""Server-side speech to text for the composer's microphone.

Processes are CLIs and cannot take audio, so a browser take is transcribed here
and only the text goes back. The model comes from the optional ``voice`` extra
(faster-whisper), is loaded on first use, serves one take at a time so two
takes never double VRAM, and is dropped again after a stretch of idleness. The
audio lives in memory for the length of one call and is never written.
"""

from __future__ import annotations

import importlib.util
import io
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .asr_backends import parse_payload
from .transcript import TakeFailed, Transcript, TranscriberUnavailable

GPU_MODEL = "large-v3-turbo"
CPU_MODEL = "small"
DEFAULT_IDLE_SECONDS = 600.0
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
INSTALL_HINT = "voice input needs the optional extra: uv sync --extra voice"




@dataclass(frozen=True)
class TranscribeSettings:
    model: str | None = None
    device: str = "auto"
    compute_type: str | None = None
    model_dir: str | None = None
    idle_seconds: float = DEFAULT_IDLE_SECONDS
    max_bytes: int = DEFAULT_MAX_BYTES

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> TranscribeSettings:
        env = os.environ if env is None else env

        def number(key: str, default: float) -> float:
            try:
                value = float(env.get(key, ""))
            except ValueError:
                return default
            return value if value > 0 else default

        return cls(
            model=env.get("PARTYLINE_TRANSCRIBE_MODEL") or None,
            device=(env.get("PARTYLINE_TRANSCRIBE_DEVICE") or "auto").lower(),
            model_dir=env.get("PARTYLINE_TRANSCRIBE_MODEL_DIR") or None,
            idle_seconds=number("PARTYLINE_TRANSCRIBE_IDLE_SECONDS", DEFAULT_IDLE_SECONDS),
            max_bytes=int(number("PARTYLINE_TRANSCRIBE_MAX_BYTES", DEFAULT_MAX_BYTES)),
        )


def _cuda_present() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _preload_cuda_libs() -> None:
    """Load pip-installed CUDA 12 libraries (the ``voice-gpu`` extra) for ctranslate2.

    ctranslate2 dlopens them by soname, which only works if they are already
    mapped; the wheels put them under site-packages/nvidia, off the loader path.
    """
    import ctypes
    from pathlib import Path

    spec = importlib.util.find_spec("nvidia")
    for root in (spec.submodule_search_locations or []) if spec else []:
        for pattern in ("cublas/lib/libcublasLt.so.12", "cublas/lib/libcublas.so.12",
                        "cudnn/lib/libcudnn.so.9"):
            for lib in Path(root).glob(pattern):
                try:
                    ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


def _build_model(name: str, device: str, compute_type: str, root: str | None) -> Any:
    if device == "cuda":
        _preload_cuda_libs()
    from faster_whisper import WhisperModel

    return WhisperModel(name, device=device, compute_type=compute_type, download_root=root)


class Transcriber:
    """One lazily loaded model behind one lock."""

    def __init__(
        self,
        settings: TranscribeSettings | None = None,
        *,
        factory: Callable[[str, str, str, str | None], Any] = _build_model,
        installed: Callable[[], bool] | None = None,
        cuda: Callable[[], bool] = _cuda_present,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or TranscribeSettings()
        self._factory = factory
        self._installed = installed or (lambda: importlib.util.find_spec("faster_whisper") is not None)
        self._cuda = cuda
        self._clock = clock
        self._lock = threading.Lock()
        self._model: Any = None
        self._last_used = 0.0
        self._timer: threading.Timer | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _plan(self) -> tuple[str, str, str]:
        device = self.settings.device
        if device == "auto":
            device = "cuda" if self._cuda() else "cpu"
        if device not in ("cuda", "cpu"):
            raise TranscriberUnavailable(f"unknown transcribe device {device!r}; use auto, cuda or cpu")
        model = self.settings.model or (GPU_MODEL if device == "cuda" else CPU_MODEL)
        return model, device, self.settings.compute_type or ("float16" if device == "cuda" else "int8")

    def status(self) -> dict[str, Any]:
        """Availability without loading anything."""
        if not self._installed():
            return {"available": False, "reason": INSTALL_HINT, "model": None}
        try:
            model, device, _ = self._plan()
        except TranscriberUnavailable as exc:
            return {"available": False, "reason": str(exc), "model": None}
        return {"available": True, "reason": None, "model": model}

    kind = "faster-whisper"

    def transcribe(self, data: bytes, mime: str = "") -> Transcript:
        """Blocking; callers run it in a worker thread. Takes are serialized."""
        if not self._installed():
            raise TranscriberUnavailable(INSTALL_HINT)
        with self._lock:
            self._cancel_timer()
            try:
                if self._model is None:
                    name, device, compute = self._plan()
                    try:
                        self._model = self._factory(name, device, compute, self.settings.model_dir)
                    except Exception as exc:
                        raise TranscriberUnavailable(
                            f"could not load speech model {name!r}: {exc}"
                        ) from exc
                try:
                    segments, info = self._model.transcribe(io.BytesIO(data), beam_size=5, vad_filter=True)
                    parts = [
                        {"start": p.start, "end": p.end, "text": p.text.strip(),
                         "no_speech_prob": getattr(p, "no_speech_prob", None),
                         "avg_logprob": getattr(p, "avg_logprob", None)}
                        for p in segments
                    ]
                    text = " ".join(p["text"] for p in parts).strip()
                except Exception as exc:
                    raise TakeFailed(f"could not transcribe that audio: {exc}") from exc
                return parse_payload({"text": text, "language": str(info.language or ""),
                                      "duration": info.duration, "segments": parts})
            finally:
                self._last_used = self._clock()
                self._arm_timer()

    def unload_if_idle(self) -> bool:
        """Drop the model once it has sat unused for the idle window."""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._model is None or self._clock() - self._last_used < self.settings.idle_seconds:
                return False
            self._model = None
            self._cancel_timer()
        finally:
            self._lock.release()
        try:
            import gc

            gc.collect()
        except Exception:  # pragma: no cover - collection is best effort
            pass
        return True

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _arm_timer(self) -> None:
        if self._model is None:
            return
        self._timer = threading.Timer(self.settings.idle_seconds, self.unload_if_idle)
        self._timer.daemon = True
        self._timer.start()
