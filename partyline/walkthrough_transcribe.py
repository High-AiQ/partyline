"""Recover utterance timestamps for any recognizer returning only plain text."""

from concurrent.futures import ThreadPoolExecutor

from .transcript import Transcript
from .walkthrough import speech_text
from .walkthrough_audio import RATE, WINDOW, decode, utterances

CONCURRENCY = 3


def transcribe_walkthrough(backend, data: bytes, mime: str) -> Transcript:
    original = backend.transcribe(data, mime)
    if original.segments:
        return original
    audio = decode(data)
    chunks = utterances(audio)
    if not chunks:
        return Transcript("", "", audio.duration)

    def transcribe_chunk(span):
        start, end = span
        result = backend.transcribe(audio.wav(start, end), "audio/wav")
        # Apply the walkthrough hallucination filter per utterance as well as
        # for the whole message. A silent chunk must not invent an outro.
        text = speech_text(result.text, False)
        return result.language, ({"start": round(start * WINDOW / RATE, 3),
                                  "end": round(min(end * WINDOW / RATE, audio.duration), 3),
                                  "text": text, "utterance": True} if text else None)

    # executor.map preserves recording order even when replies arrive out of order.
    # Only three calls run at once; PCM chunks are materialized inside the workers.
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        results = list(pool.map(transcribe_chunk, chunks))
    segments = tuple(segment for _, segment in results if segment)
    language = original.language or next((lang for lang, _ in results if lang), "")
    return Transcript(" ".join(s["text"] for s in segments), language, audio.duration, segments)
