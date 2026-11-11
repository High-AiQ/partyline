"""In-memory PCM silence detection for walkthroughs, without a voice extra.

The browser decodes its recording to mono 16 kHz PCM WAV. Use 20 ms RMS
windows and a 500 ms pause to keep natural utterances together. Timing stays
on the original recording clock, including all leading/intervening silence.
"""

from array import array
from dataclasses import dataclass
from io import BytesIO
import math
import sys
import wave

from .transcript import TakeFailed

RATE = 16000
WINDOW = 320
PAUSE = 25
PAD = 6
MAX_WINDOWS = 1500  # 30 seconds
MIN_SPEECH = 6  # reject clicks shorter than 120 ms


@dataclass(frozen=True)
class Audio:
    pcm: bytes
    levels: tuple[float, ...]

    @property
    def duration(self) -> float:
        return len(self.pcm) / (2 * RATE)

    def wav(self, start: int, end: int) -> bytes:
        output = BytesIO()
        with wave.open(output, "wb") as target:
            target.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            target.writeframes(self.pcm[start * WINDOW * 2:end * WINDOW * 2])
        return output.getvalue()


def decode(data: bytes) -> Audio:
    try:
        with wave.open(BytesIO(data), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, RATE):
                raise ValueError("expected mono 16 kHz PCM16")
            if not 0 < source.getnframes() <= RATE * 600:
                raise ValueError("expected up to ten minutes of audio")
            pcm = source.readframes(source.getnframes())
            if len(pcm) != source.getnframes() * 2:
                raise ValueError("truncated WAV")
    except (wave.Error, EOFError, ValueError) as exc:
        raise TakeFailed("walkthrough audio must be mono 16 kHz PCM16 WAV (up to ten minutes)") from exc
    samples = array("h", pcm)
    if sys.byteorder != "little":  # pragma: no cover - big-endian hosts
        samples.byteswap()
    levels = tuple(math.sqrt(sum(v * v for v in samples[i:i + WINDOW]) /
                             len(samples[i:i + WINDOW])) / 32768
                   for i in range(0, len(samples), WINDOW))
    return Audio(pcm, levels)


def utterances(audio: Audio) -> list[tuple[int, int]]:
    """Return padded window ranges; cap long speech at its quietest recent point."""
    levels = audio.levels
    if not levels:
        return []
    # Same 0.003 RMS floor as the existing mic meter. Modest noise adaptation
    # helps room noise without raising the threshold above ordinary quiet speech.
    floor = sorted(levels)[len(levels) // 10]
    threshold = max(0.003, min(0.015, floor * 3))
    spans = []
    start = last = None
    voiced = 0
    for index, level in enumerate(levels):
        if level >= threshold:
            if start is None:
                start = index
            last = index
            voiced += 1
        if start is not None and (index - last >= PAUSE or index == len(levels) - 1):
            if voiced >= MIN_SPEECH:
                spans.append((max(0, start - PAD), min(len(levels), last + 1 + PAD), last + 1))
            start = last = None
            voiced = 0
    chunks = []
    for start, end, speech_end in spans:
        while end - start > MAX_WINDOWS:
            limit = start + MAX_WINDOWS
            if speech_end <= limit:
                # Only padding crosses the cap: trim it instead of sending silence.
                end = limit
                break
            # Leave at least 120 ms for the final piece, including at recording EOF.
            latest = min(limit, end - MIN_SPEECH)
            # Prefer the latest equal-energy point, avoiding tiny leading chunks.
            split = min(range(limit - 250, latest + 1), key=lambda i: (levels[i - 1], -i))
            chunks.append((start, split))
            start = split
        chunks.append((start, end))
    return chunks
