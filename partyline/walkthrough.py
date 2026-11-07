"""Ephemeral walkthrough frame buffering and time-based selection."""

from dataclasses import dataclass, field

from .screen_frames import BufferedFrame, pick_distinct


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
    distinct = {id(frame) for frame in pick_distinct(frames, len(frames))}
    candidates = {i for i, frame in enumerate(frames) if id(frame) in distinct} - chosen
    while candidates and len(chosen) < count:
        # Fill the largest temporal gaps so the whole take remains represented.
        index = max(candidates, key=lambda i: min(abs(frames[i].ts_ms - frames[j].ts_ms)
                                                   for j in chosen))
        chosen.add(index)
        candidates.remove(index)
    return [frames[i] for i in sorted(chosen)]


def assemble_message(notes: str, segments: list[dict], frames: list[BufferedFrame],
                     transcription_error: bool = False) -> str:
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
        location = f" (pointer at {pointer['x']},{pointer['y']})" if visible else ""
        events.append((frame.ts_ms, 1, f"frame {index}{location}"))
    lines = [notes.strip()] if notes.strip() else []
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
