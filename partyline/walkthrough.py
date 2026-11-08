"""Ephemeral walkthrough frame buffering and time-based selection."""

from dataclasses import dataclass, field
import re

from .screen_frames import BufferedFrame
from .screen_pointer import captured_pointer, annotate_stationary_pointers, visually_identical


@dataclass
class WalkthroughBuffer:
    """A bounded take. The first and most recent frames survive eviction when possible."""

    max_duration_ms: int = 600_000
    max_frames: int = 600
    max_bytes: int = 128 * 1024 * 1024
    frames: list[BufferedFrame] = field(default_factory=list)
    size: int = 0
    started_at: int | None = None

    def add(self, frame: BufferedFrame) -> bool:
        if self.max_frames < 1 or len(frame.data) > self.max_bytes:
            return False
        if self.frames and frame.ts_ms < self.frames[-1].ts_ms:
            return False
        if self.started_at is not None and frame.ts_ms - self.started_at > self.max_duration_ms:
            return False
        if self.started_at is None:
            self.started_at = frame.ts_ms
        self.frames.append(frame)
        self.size += len(frame.data)
        while len(self.frames) > self.max_frames or self.size > self.max_bytes:
            # Preserve the opening frame when there is room for both endpoints.
            index = min(range(1, len(self.frames) - 1),
                        key=lambda i: self.frames[i + 1].ts_ms - self.frames[i - 1].ts_ms) \
                if len(self.frames) > 2 else 0
            self.size -= len(self.frames.pop(index).data)
        return True

    def clear(self) -> None:
        self.frames.clear()
        self.size = 0
        self.started_at = None


def select_frames(frames: list[BufferedFrame], segments: list[dict],
                  count: int = 24, pause_seconds: float = 0.5) -> list[BufferedFrame]:
    """Select endpoints, sentence-ending frames, then evenly spaced changed frames.

    Segment times are seconds relative to the take start. A pause selects the
    latest frame at or before the preceding segment's end, never a future frame.
    """
    frames = deduplicate_frames(annotate_stationary_pointers(frames))
    if count <= 0 or not frames:
        return []
    if count == 1:
        return [frames[0]]
    if len(frames) <= 2:
        return frames[:count]
    chosen = {0, len(frames) - 1}
    pauses = []
    for current, following in zip(segments, segments[1:], strict=False):
        gap = following["start"] - current["end"]
        if gap >= pause_seconds:
            end = current["end"] * 1000
            indexes = [i for i, frame in enumerate(frames) if frame.ts_ms <= end]
            if indexes:
                pauses.append((gap, indexes[-1]))
    for _, index in sorted(pauses, reverse=True):
        if len(chosen) >= count:
            break
        chosen.add(index)
    candidates = set(range(len(frames))) - chosen
    while candidates and len(chosen) < count:
        # Fill the largest temporal gaps so the whole take remains represented.
        index = max(candidates, key=lambda i: min(abs(frames[i].ts_ms - frames[j].ts_ms)
                                                   for j in chosen))
        chosen.add(index)
        candidates.remove(index)
    return deduplicate_frames([frames[i] for i in sorted(chosen)])


def deduplicate_frames(frames: list[BufferedFrame]) -> list[BufferedFrame]:
    """Drop adjacent identical views, comparing positions only for ordinary pointers."""
    kept = []
    for frame in frames:
        if kept and _near_duplicate(kept[-1], frame):
            continue
        kept.append(frame)
    return kept


def _near_duplicate(first: BufferedFrame, second: BufferedFrame) -> bool:
    a, b = first.pointer or {}, second.pointer or {}
    if captured_pointer(first) != captured_pointer(second):
        return False
    if captured_pointer(first):
        return visually_identical(first, second)
    if bool(a.get("visible")) != bool(b.get("visible")):
        return False
    if a.get("visible") and (abs(a["x"] - b["x"]) > 3 or abs(a["y"] - b["y"]) > 3):
        return False
    return visually_identical(first, second)


_SILENCE_PHRASES = {tuple(phrase.split()) for phrase in (
    "thank you for watching", "thanks for watching", "thank you",
    "bye bye", "the end", "you", "thanks", "bye")}
_SILENCE_MAX_WORDS = max(map(len, _SILENCE_PHRASES))


def _only_silence_phrases(segments: list[dict]) -> bool:
    """Match a sequence of known phrases in linear time, despite overlapping phrases."""
    words = re.findall(r"\w+", " ".join(part["text"].casefold() for part in segments))
    if not words:
        return False
    reachable = [True] + [False] * len(words)
    for start in range(len(words)):
        if reachable[start]:
            for size in range(1, min(_SILENCE_MAX_WORDS, len(words) - start) + 1):
                if tuple(words[start:start + size]) in _SILENCE_PHRASES:
                    reachable[start + size] = True
    return reachable[-1]


def speech_segments(segments: list[dict], no_input: bool) -> list[dict]:
    """Suppress common silence artifacts and join incomplete adjacent phrases."""
    nonempty = [segment for segment in segments if segment["text"].strip()]
    if no_input or _only_silence_phrases(nonempty):
        return []
    joined = []
    for segment in nonempty:
        part = dict(segment)
        part["text"] = part["text"].strip()
        if (joined and not re.search(r'[.!?]["\']?$', joined[-1]["text"])
                and part["start"] - joined[-1]["end"] <= 2):
            joined[-1]["text"] += " " + part["text"]
            joined[-1]["end"] = max(joined[-1]["end"], part["end"])
        else:
            joined.append(part)
    return joined


def assemble_message(notes: str, segments: list[dict], frames: list[BufferedFrame],
                     transcription_error: bool = False, duration_ms: int = 0) -> str:
    """Interleave transcript and numbered image references in recording order."""
    events = []
    for segment in segments:
        events.append((max(0, int(segment["start"] * 1000)), 0, segment["text"].strip()))
    for index, frame in enumerate(frames, 1):
        pointer = frame.pointer
        region = frame.region
        visible = (pointer and pointer.get("visible") and
                   region["x"] <= pointer["x"] < region["x"] + region["width"] and
                   region["y"] <= pointer["y"] < region["y"] + region["height"])
        stationary = ", stationary" if pointer and pointer.get("stationary") else ""
        location = f" (pointer at {pointer['x']},{pointer['y']}{stationary})" if visible else ""
        if captured_pointer(frame):
            location = " (view centre; pointer captured)"
        events.append((frame.ts_ms, 1, f"frame {index}{location}"))
    duration_ms = max(duration_ms, *(frame.ts_ms for frame in frames),
                      *(int(segment["end"] * 1000) for segment in segments), 0)
    seconds = duration_ms // 1000
    lines = [f"Walkthrough · {seconds // 60}:{seconds % 60:02d} · {len(frames)} "
             f"{'frame' if len(frames) == 1 else 'frames'}"]
    if notes.strip():
        lines.append(notes.strip())
    if not segments and not transcription_error:
        lines.append("(no speech detected — check the microphone)")
    if frames:
        lines.append("Contact sheet first: open it, then fetch only the frames you need "
                     "(thumb ≈ 230 tokens, slim ≈ 1,400).")
    if transcription_error:
        lines.append("Speech transcription failed; " + (
            "the screen frames are included below." if frames else "no screen frames were captured."))
    for timestamp, kind, text in sorted(events, key=lambda event: (event[0], event[1])):
        if text:
            seconds = timestamp // 1000
            label = f"[{seconds // 60}:{seconds % 60:02d}]"
            lines.append(f'{label} "{text}"' if kind == 0 else f"{label} → {text}")
    return "\n".join(lines) or "Walkthrough (no speech or frames captured)."
