"""Walkthrough speech segmentation and backend-independent timed transcription."""

from array import array
from dataclasses import replace
from io import BytesIO
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import wave

from partyline.asr_backends import OpenAICompatible
from partyline.transcriber import Transcriber, TranscribeSettings
from partyline.transcript import TakeFailed, Transcript
from partyline.walkthrough import assemble_message, speech_segments
from partyline.walkthrough_audio import Audio, decode, utterances
from partyline.walkthrough_transcribe import CONCURRENCY, transcribe_walkthrough
from tests.walkthrough_audio_fakes import PASSAGES, recognizer, wav


class SegmentingTest(unittest.TestCase):
    def test_offsets_preserve_leading_silence_and_pauses(self):
        audio = decode(wav(PASSAGES))
        self.assertEqual(audio.duration, 9)
        self.assertEqual(utterances(audio), [(44, 106), (194, 256), (344, 406)])
        with wave.open(BytesIO(audio.wav(44, 106)), "rb") as source:
            self.assertEqual(source.getnframes(), 62 * 320)
        self.assertEqual(utterances(Audio(b"", ())), [])

    def test_silence_clicks_and_noise_do_not_make_utterances(self):
        self.assertEqual(utterances(decode(wav())), [])
        self.assertEqual(utterances(decode(wav(((1, 1.04, 9000),)))), [])
        self.assertEqual(utterances(decode(wav(((0, 9, 50),)))), [])

    def test_short_gaps_stay_in_one_utterance_and_eof_is_flushed(self):
        audio = decode(wav(((0, 1, 3000), (1.2, 2, 3000)), duration=2))
        self.assertEqual(utterances(audio), [(0, 100)])

    def test_long_utterance_splits_at_quietest_point_under_thirty_seconds(self):
        # Feed window energies directly so this regression stays under one second.
        audio = Audio(b"", (0.1,) * 3000)
        levels = list(audio.levels)
        levels[1399] = 0.02  # quietest point at 28 s, still above the speech threshold
        chunks = utterances(replace(audio, levels=tuple(levels)))
        self.assertEqual(chunks, [(0, 1400), (1400, 2900), (2900, 3000)])
        self.assertTrue(all(end - start <= 1500 for start, end in chunks))

    def test_invalid_truncated_and_wrong_format_audio_fail_cleanly(self):
        for data in (b"garbage", b"RIFF", wav(rate=8000), wav(duration=0),
                     wav(duration=601, rate=1), wav()[:-2]):
            with self.subTest(size=len(data)), self.assertRaises(TakeFailed):
                decode(data)
        # A header can claim an oversized recording without allocating that recording.
        data = bytearray(wav(duration=1))
        data[40:44] = (16000 * 2 * 601).to_bytes(4, "little")
        with self.assertRaises(TakeFailed):
            decode(bytes(data))

    def test_thirty_second_boundary_does_not_split_off_trailing_padding(self):
        for voiced in range(1489, 1495):
            with self.subTest(voiced=voiced):
                levels = (0,) * 50 + (0.05,) * voiced + (0,) * 50
                self.assertEqual(utterances(Audio(b"", levels)), [(44, 1544)])

    def test_split_leaves_a_transcribable_tail_when_speech_reaches_eof(self):
        for length in range(1501, 1506):
            with self.subTest(length=length):
                chunks = utterances(Audio(b"", (0.05,) * length))
                self.assertEqual(chunks, [(0, length - 6), (length - 6, length)])


class TranscriptionTest(unittest.TestCase):
    def test_near_cap_speech_never_sends_a_rejected_silent_sliver(self):
        calls = []

        def transcribe(data, mime):
            audio = decode(data)
            calls.append(audio.duration)
            if audio.duration < 0.1:
                raise TakeFailed("audio too short", 502)
            return Transcript("spoken narration", "en", audio.duration)

        result = transcribe_walkthrough(SimpleNamespace(transcribe=transcribe),
                                        wav(((1, 30.78, 3000),), duration=31.78), "audio/wav")
        self.assertEqual(calls, [31.78, 30])
        self.assertEqual(result.segments, ({"start": 0.88, "end": 30.88,
                                           "text": "spoken narration", "utterance": True},))

    def test_json_http_preset_stitches_chunks_and_keeps_utterance_boundaries(self):
        with recognizer(4, outro=True) as (base, seen):
            result = transcribe_walkthrough(OpenAICompatible(base, "any-json-model", response_format="json"),
                                            wav(PASSAGES), "audio/wav")
        self.assertEqual(len(seen), 4)
        self.assertTrue(all(path == "/v1/audio/transcriptions" for path, _, _ in seen))
        self.assertTrue(all(fields["model"] == b"any-json-model" for _, fields, _ in seen))
        self.assertEqual(result.language, "en")
        self.assertEqual(result.duration, 9)
        self.assertEqual([s["start"] for s in result.segments], [0.88, 6.88])
        self.assertEqual([s["text"] for s in result.segments], ["Open the asset panel", "Preview the result"])
        parts = speech_segments(list(result.segments), False)
        self.assertEqual(len(parts), 2)
        self.assertEqual(assemble_message("", parts, []).count('] "'), 2)
        self.assertNotIn("Thanks", result.text)

    def test_verbose_http_preset_keeps_native_timestamps_and_one_request(self):
        with recognizer(1, native=True) as (base, seen):
            result = transcribe_walkthrough(OpenAICompatible(base, "native-model"),
                                            wav(PASSAGES), "audio/wav")
        self.assertEqual(len(seen), 1)
        self.assertEqual(result.segments, ({"start": 1.1, "end": 1.9, "text": "Preview the result"},))

    def test_local_faster_whisper_keeps_native_timestamps(self):
        model = SimpleNamespace(transcribe=Mock(return_value=(iter([
            SimpleNamespace(start=2.4, end=3.2, text="local speech")]),
            SimpleNamespace(language="en", duration=9))))
        backend = Transcriber(TranscribeSettings(), installed=lambda: True,
                              cuda=lambda: False, factory=lambda *_: model)
        try:
            result = transcribe_walkthrough(backend, b"native-audio", "audio/webm")
        finally:
            backend._cancel_timer()
        self.assertEqual(result.segments[0]["start"], 2.4)
        model.transcribe.assert_called_once()

    def test_silent_recording_skips_all_chunk_requests(self):
        backend = SimpleNamespace(transcribe=Mock(return_value=Transcript("imagined", "en", 0)))
        self.assertEqual(transcribe_walkthrough(backend, wav(), "audio/wav").text, "")
        backend.transcribe.assert_called_once()

    def test_empty_chunk_replies_and_language_fallback(self):
        replies = [Transcript("original", "", 0), Transcript("", "fr", 0)]
        backend = SimpleNamespace(transcribe=Mock(side_effect=replies))
        result = transcribe_walkthrough(backend, wav(((1, 2, 3000),)), "audio/wav")
        self.assertEqual((result.text, result.language, result.segments), ("", "fr", ()))

    def test_utterance_segments_are_not_joined_without_punctuation(self):
        parts = [{"start": 1, "end": 2, "text": "first", "utterance": True},
                 {"start": 2.3, "end": 3, "text": "second", "utterance": True}]
        self.assertEqual(speech_segments(parts, False), parts)

    def test_concurrency_is_bounded_and_stitching_uses_recording_order(self):
        barrier = threading.Barrier(CONCURRENCY)
        lock = threading.Lock()
        active = peak = calls = 0
        audio = wav(tuple((i * 2, i * 2 + 1, 1000 + i) for i in range(6)), duration=12)

        def transcribe(data, mime):
            nonlocal active, peak, calls
            with lock:
                calls += 1
                if calls == 1:
                    return Transcript("untimed", "", 0)
                active += 1
                peak = max(peak, active)
            with wave.open(BytesIO(data), "rb") as source:
                value = max(array("h", source.readframes(source.getnframes())))
            barrier.wait(timeout=0.5)  # event synchronization, never a timed sleep
            with lock:
                active -= 1
            return Transcript(str(value), "", 0)

        result = transcribe_walkthrough(SimpleNamespace(transcribe=transcribe), audio, "audio/wav")
        self.assertEqual((peak, calls), (CONCURRENCY, 7))
        self.assertEqual(result.text, "1000 1001 1002 1003 1004 1005")

    def test_chunk_failure_fails_the_take_instead_of_silently_losing_narration(self):
        backend = SimpleNamespace(transcribe=Mock(side_effect=[
            Transcript("full", "", 0), TakeFailed("failed")]))
        with self.assertRaisesRegex(TakeFailed, "failed"):
            transcribe_walkthrough(backend, wav(((1, 2, 3000),)), "audio/wav")
