"""The shared shape of a transcription, whichever backend produced it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TranscriberUnavailable(Exception):
    """A backend cannot run; the message is the reason shown to the person."""


class TakeFailed(Exception):
    """This one take could not be transcribed; the backend itself is fine.

    ``status`` is 422 when the audio is at fault and 502 when a recognizer or
    service failed on it. Unlike ``TranscriberUnavailable`` it must not switch
    voice input off: the next take may work.
    """

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class WhisperRetired(TakeFailed):
    """An OpenAI retirement error with a fixed message safe for the server log."""

    def __init__(self):
        super().__init__(
            "model whisper-1 is retired; switch the preset to gpt-transcribe in Settings → Voice", 502)


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    duration: float
    segments: tuple[dict[str, Any], ...] = ()


def _stamp(seconds: float) -> str:
    millis = max(0, int(round(float(seconds) * 1000)))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"


def segments_to_vtt(segments) -> str:
    """WebVTT for ``[{start, end, text}]`` (seconds from the start of the take)."""
    out = ["WEBVTT", ""]
    for seg in segments:
        # A cue ends at a blank line and "-->" is the timing separator.
        lines = [ln.strip() for ln in str(seg["text"]).replace("-->", "->").splitlines()]
        body = "\n".join(ln for ln in lines if ln)
        out += [f"{_stamp(seg['start'])} --> {_stamp(seg['end'])}", body, ""]
    return "\n".join(out)
