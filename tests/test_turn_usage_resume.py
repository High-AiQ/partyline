"""A resumed or reattached process records its model usage, once, and never its history."""

import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.claude.adapter import PartylineAdapter as Claude
from partyline.adapters.bundled.codex.adapter import PartylineAdapter as Codex
from partyline.adapters.bundled.opencode.v2 import PartylineAdapter as OpenCode
from partyline.attachment_resume import resume_adapter
from partyline.db import Db
from partyline.resource_budget import GIB, Host
from partyline.runtime import ChatRuntime
from partyline.turn_usage_parse import make_turn
from tests import turn_usage_fixtures as fx


def ms(offset):
    return int((fx.NOW + offset) * 1000)


# Each adapter's transcript: two responses from before the restart (-100, -50), one 3 s before the
# new spawn (-3, which a fresh process would keep as clock slack) and two after it (+2, +4).
def claude_records(offset):
    return [fx.claude_line(f"msg_{offset}", [fx.BASH], fx.usage(2, 100, 900, 30), offset=offset)]


def codex_records(offset):
    call = {"type": "custom_tool_call", "name": "exec", "input": fx.SECRET}
    done = {"response_id": f"resp_{offset}", "usage": fx.codex_usage(1000, 400, 20)}
    return [fx.codex("response_item", call, offset), fx.codex("token_usage_record", done, offset)]


def opencode_records(offset):
    return [(f"oc_{offset}", fx.opencode_row(completed=ms(offset)))]


CASES = {
    "claude": (Claude, {"name": "claude", "cwd": "/work"}, claude_records),
    "codex": (Codex, {"name": "codex", "command": ["codex"], "cli_session": "s"}, codex_records),
    "opencode-v2": (OpenCode, {"name": "oc", "cwd": "/work", "command": ["opencode2"],
                               "cli_session": "s"}, opencode_records),
}
OFFSETS = (-100, -50, -3, 2, 4)


class _Presence:
    def watch(self, adapter, *_args):
        return adapter

    def posting(self, *_args):
        return lambda *_: None

    def statusing(self, *_args, **_kwargs):
        return lambda *_: None


class ReattachUsageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        host = patch("partyline.resource_budget.host_resources", return_value=Host(cpus=8, ram_bytes=8 * GIB))
        host.start()
        self.addCleanup(host.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")

    def rows(self):
        return [dict(row) for row in self.db._exec(
            "SELECT attachment_id, response_id FROM turn_usage ORDER BY response_id")]

    async def resumed(self, kind):
        """The adapter exactly as the restart plan builds it, spawned at the fixture clock."""
        cls, extra, _records = CASES[kind]
        self.db.add_attachment("one", "line", extra["name"], kind.split("-")[0], ["x"], self.directory.name)
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='one'")
        made = {}

        def make(_kind, att, *_args, **_kwargs):
            att.update({key: value for key, value in extra.items() if key not in att})
            made["adapter"] = cls(att, AsyncMock(), AsyncMock())
            return made["adapter"]

        async def spawn():
            made["adapter"].spawned_at = fx.NOW

        metadata = {kind.split("-")[0]: {"capabilities": {"resume": True}}}
        arguments = dict(runtime=self.runtime, adapter_metadata=metadata, make_adapter=make,
                         presence=_Presence(), hook_url=lambda *_: "hook")
        with (patch("partyline.attachment_resume.bind_role_delivery"),
              patch("partyline.attachment_resume.bind_connection_hint"),
              patch("partyline.attachment_resume.provision_connection"),
              patch.object(cls, "start", side_effect=spawn),
              patch.object(cls, "stage_startup_delivery", return_value=False)):
            await resume_adapter("one", None, **arguments)
        return made["adapter"]

    async def test_every_reattached_adapter_records_after_the_reattach_only_and_only_once(self):
        for kind, (_cls, _extra, records) in CASES.items():
            with self.subTest(kind=kind):
                self.db._exec("DELETE FROM turn_usage")
                self.db._exec("DELETE FROM attachments")
                self.runtime.live.clear()
                adapter = await self.resumed(kind)
                self.assertTrue(adapter.resume)
                for _replay in range(2):  # the tail replays the whole transcript on every resume
                    adapter.__dict__.pop("_turn_parser", None)
                    for offset in OFFSETS:
                        for record in records(offset):
                            await adapter.note_turn_usage(record)
                rows = self.rows()
                self.assertEqual({row["attachment_id"] for row in rows}, {"one"})
                self.assertEqual([row["response_id"].split("_")[1] for row in rows], ["2", "4"])

    async def test_a_fresh_process_keeps_its_clock_slack_but_a_resume_does_not(self):
        adapter = await self.resumed("claude")
        adapter.spawned_at = fx.NOW
        early = claude_records(-3)[0]
        await adapter.note_turn_usage(early)
        self.assertEqual(self.rows(), [])
        adapter.resume = False
        adapter.__dict__.pop("_turn_parser", None)
        await adapter.note_turn_usage(early)
        self.assertEqual(len(self.rows()), 1)

    async def test_the_resume_path_hands_the_adapter_a_usage_callback_bound_to_its_attachment(self):
        adapter = await self.resumed("codex")
        self.assertTrue(callable(adapter.att["on_turn_usage"]))
        turn = make_turn("r", fx.NOW + 1, input=1, output=1, context=1)
        self.assertTrue(await adapter.att["on_turn_usage"](turn))
        self.assertEqual(self.rows(), [{"attachment_id": "one", "response_id": "r"}])
