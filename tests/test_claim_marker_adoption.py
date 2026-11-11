"""A resumed transcript is adopted although a tool result printed strangers' markers."""

import asyncio
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from tests.adapter_event_clock import install as event_clock
from partyline.adapters import jsonl_receipts
from partyline.adapters.bundled.claude.adapter import PartylineAdapter

OWN = "6982c170-0000-4000-8000-000000000000"
STRANGER = "cff4f39a-0000-4000-8000-000000000000"


def user(text):
    return {"type": "user", "message": {"content": text}}


def tool_result(text):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": text}]}}


class ClaimMarkerAdoptionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = f"{self.temp.name}/session.jsonl"
        self.posted = []
        adapter = PartylineAdapter(
            {"id": OWN, "name": "opus2", "cwd": self.temp.name, "command": ["claude"],
             "adapter_metadata": {"capabilities": {"transcript": True}}},
            AsyncMock(), AsyncMock(),
        )
        adapter._post_to_chat = AsyncMock(side_effect=lambda *a: self.posted.append(a))
        adapter.alive = lambda: True
        self.adapter = event_clock(adapter)
        self.sleeps = 0

    def write(self, *records):
        with open(self.path, "a", encoding="utf-8") as out:
            out.writelines(json.dumps(r) + "\n" for r in records)

    def resumed(self):
        self.write(
            user(f"old briefing\n[partyline-claim: {OWN}/36677324b71a]"),
            user(f"wake\n[partyline-claim: {OWN}/5f1bf4fd54ed]"),
            tool_result(f"cmdline [partyline-claim: {STRANGER}/7e79aa7cf3d8]"),
        )

    def test_prior_own_markers_outweigh_foreign_ones_in_a_tool_result(self):
        self.resumed()
        self.assertFalse(self.adapter.foreign_claim(self.path))
        self.assertFalse(self.adapter.recorded_claim(self.path))

    def test_a_file_with_only_foreign_markers_is_refused(self):
        self.write(user(f"hi [partyline-claim: {STRANGER}/7e79aa7cf3d8]"))
        self.assertTrue(self.adapter.foreign_claim(self.path))

    def test_a_file_without_markers_is_not_foreign(self):
        self.write(user("hello"))
        self.assertFalse(self.adapter.foreign_claim(self.path))

    async def run_tail(self, step):
        """Tail the file; ``step`` runs on each fake sleep and may end the process."""
        real_sleep = asyncio.sleep

        async def fake_sleep(_seconds):
            self.sleeps += 1
            step(self.sleeps)
            await real_sleep(0)

        spoken = []

        async def handle(record):
            await self.adapter.post("opus2", "agent", json.dumps(record)[:20])
            spoken.append(record)

        with patch.object(jsonl_receipts.asyncio, "sleep", fake_sleep):
            await asyncio.wait_for(jsonl_receipts.tail_jsonl(self.adapter, self.path, handle), 5)
        return spoken

    async def test_resumed_transcript_is_adopted_and_speech_flows_with_the_new_nonce(self):
        self.resumed()
        self.adapter._nonce = "aaaaaaaaaaaa"

        def step(n):
            if n == 1:
                self.assertFalse(self.adapter._claim_proven)
                self.write(user(f"wake\n{self.adapter._claim_token}"))
            elif n > 3:
                self.adapter.alive = lambda: False

        await self.run_tail(step)

        self.assertTrue(self.adapter._claim_proven)
        agent = [p for p in self.posted if p[1] == "agent"]
        self.assertTrue(agent)
        self.assertFalse([p for p in self.posted if "not adopting" in p[2]])

    async def test_refusal_is_loud_and_recovers_when_this_activations_nonce_appears(self):
        self.write(user(f"x [partyline-claim: {STRANGER}/7e79aa7cf3d8]"))
        self.adapter._nonce = "bbbbbbbbbbbb"

        def step(n):
            if n == 2:
                self.write(user(f"wake\n{self.adapter._claim_token}"))
            elif n > 5:
                self.adapter.alive = lambda: False

        await self.run_tail(step)

        self.assertEqual(sum("not adopting" in p[2] for p in self.posted), 1)
        self.assertTrue(self.adapter._claim_proven)

    async def test_refusal_ends_the_tail_when_the_process_exits_unclaimed(self):
        self.write(user(f"x [partyline-claim: {STRANGER}/7e79aa7cf3d8]"))
        self.adapter._nonce = "cccccccccccc"

        spoken = await self.run_tail(lambda n: setattr(self.adapter, "alive", lambda: False))

        self.assertEqual(spoken, [])
        self.assertFalse(self.adapter._claim_proven)
        self.assertEqual(sum("not adopting" in p[2] for p in self.posted), 1)
