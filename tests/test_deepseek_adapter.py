"""Fixture coverage for the DeepSeek Harness ACP transcript adapter."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from partyline.adapters.bundled.deepseek.adapter import PartylineAdapter


def attachment(**extra):
    return {
        "id": "deepseek-attachment",
        "name": "luna",
        "cwd": "/project",
        "command": ["dsh", "--profile", "acp"],
        "adapter_metadata": {"command": ["dsh", "--profile", "acp"]},
        "conv_name": "harness",
        "resume": False,
        **extra,
    }


class DeepSeekAdapterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.messages = []
        self.receipts = []
        PartylineAdapter._CLAIMED.clear()

    def tearDown(self):
        PartylineAdapter._CLAIMED.clear()

    async def post(self, sender, sender_type, body):
        self.messages.append((sender, sender_type, body))

    async def status(self, value):
        pass

    def make(self, **extra):
        return PartylineAdapter(attachment(**extra), self.post, self.status)

    async def test_default_command_and_resume_command_are_argv(self):
        fresh = self.make(command=[])
        self.assertEqual(fresh.build_command(), ["dsh", "--profile", "acp"])
        resumed = self.make(resume=True, cli_session="session-7")
        self.assertEqual(resumed.build_command(), ["dsh", "--profile", "acp"])

    async def test_patch_path_is_expanded_for_direct_pty_exec(self):
        adapter = self.make(command=[
            "dsh", "--profile", "acp", "--note", "~literal $value", "--patch",
            "~/.dsh/models/qwen.yml",
        ])
        with patch.dict("os.environ", {"HOME": "/tmp/operator"}):
            self.assertEqual(
                adapter.build_command(),
                [
                    "dsh", "--profile", "acp", "--note", "~literal $value", "--patch",
                    "/tmp/operator/.dsh/models/qwen.yml",
                ],
            )

    async def test_patch_expansion_uses_dsh_home_without_touching_other_arguments(self):
        adapter = self.make(command=[
            "dsh", "--profile", "acp", "--note", "~literal $value", "--patch",
            "$DSH_HOME/models/qwen.yml",
        ])
        with patch.dict("os.environ", {"DSH_HOME": "/tmp/operator", "HOME": "/tmp/other"}):
            self.assertEqual(
                adapter.build_command(),
                [
                    "dsh", "--profile", "acp", "--note", "~literal $value", "--patch",
                    "/tmp/operator/models/qwen.yml",
                ],
            )

    async def test_acp_pty_is_raw_before_wire_frames(self):
        adapter = self.make()
        adapter.master = 12
        with patch("partyline.adapters.bundled.deepseek.adapter.tty.setraw") as setraw:
            adapter._prepare_pty()
        setraw.assert_called_once_with(12)

    async def test_wire_response_is_resolved_but_update_is_not_chat(self):
        adapter = self.make()
        response = asyncio.get_running_loop().create_future()
        adapter._pending[3] = response
        await adapter.on_output(
            b'{"jsonrpc":"2.0","method":"session/update","params":{"update":{}}}\n'
            b'{"jsonrpc":"2.0","id":3,"result":{"sessionId":"s"}}\n'
        )
        self.assertEqual(response.result(), {"sessionId": "s"})
        self.assertEqual(self.messages, [])

    async def test_permission_request_selects_allow_once(self):
        adapter = self.make()
        adapter._write_frame = AsyncMock()
        await adapter.on_output(
            json.dumps({
                "jsonrpc": "2.0", "id": 9, "method": "session/request_permission",
                "params": {"options": [
                    {"optionId": "reject-once"}, {"optionId": "allow-once"},
                ]},
            }).encode() + b"\n"
        )
        adapter._write_frame.assert_awaited_once_with({
            "jsonrpc": "2.0", "id": 9,
            "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}},
        })

    async def test_permission_request_cancels_when_no_allow_option_exists(self):
        adapter = self.make()
        adapter._write_frame = AsyncMock()
        await adapter.on_output(
            json.dumps({
                "jsonrpc": "2.0", "id": 9, "method": "session/request_permission",
                "params": {"options": [{"optionId": "reject-once"}]},
            }).encode() + b"\n"
        )
        adapter._write_frame.assert_awaited_once_with({
            "jsonrpc": "2.0", "id": 9,
            "result": {"outcome": {"outcome": "cancelled"}},
        })

    async def test_transcript_posts_only_spoken_text_and_receipts(self):
        adapter = self.make()
        with patch(
            "partyline.adapters.bundled.deepseek.adapter.receipt",
            new=AsyncMock(side_effect=lambda _att, event: self.receipts.append(event)),
        ):
            await adapter._handle_record({"seq": 1, "type": "turn/start"})
            await adapter._handle_record({
                "seq": 2,
                "type": "assistant/message",
                "data": {"message": {"role": "assistant", "content": [
                    {"type": "reasoning", "text": "private"},
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ]}},
            })
            await adapter._handle_record({"seq": 3, "type": "turn/end"})
            await adapter._handle_record({
                "seq": 4, "type": "assistant/message",
                "data": {"message": {"role": "tool", "content": [{"type": "text", "text": "no"}]}},
            })
        self.assertEqual(self.messages, [("luna", "agent", "first\n\nsecond")])
        self.assertEqual(self.receipts, ["UserPromptSubmit", "Stop"])

    async def test_duplicate_and_malformed_records_are_ignored(self):
        adapter = self.make()
        await adapter._handle_record({"seq": 1, "type": "not-a-real-event"})
        await adapter._handle_record({"seq": 1, "type": "assistant/message", "data": {}})
        await adapter._handle_record({"type": "assistant/message", "data": {}})
        self.assertEqual(self.messages, [])

    async def test_claimed_plain_log_and_compressed_log_refusal(self):
        with tempfile.TemporaryDirectory() as root:
            session = "session-1"
            path = Path(root) / "sessions" / "--project--" / session
            path.mkdir(parents=True)
            plain = path / "session.v3.jsonl"
            plain.write_text(json.dumps({"type": "session", "version": 3}) + "\n")
            adapter = self.make()
            with patch.dict("os.environ", {"DSH_HOME": root}):
                self.assertEqual(adapter._find_log(session), plain)
                self.assertIsNone(adapter._find_log(session))

            compressed_path = Path(root) / "sessions" / "--project--" / "session-2"
            compressed_path.mkdir()
            compressed = compressed_path / "session.v3.jsonl.zstd"
            compressed.write_bytes(b"not-json")
            second = self.make()
            with patch.dict("os.environ", {"DSH_HOME": root}):
                with self.assertRaisesRegex(RuntimeError, "compression: none"):
                    second._find_log("session-2")

    async def test_resume_snapshot_skips_existing_sequences(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "session.v3.jsonl"
            path.write_text(
                '{"type":"session","version":3}\n'
                '{"seq":0,"type":"turn/end"}\n'
                '{"seq":2,"type":"turn/start"}\n'
                'partial',
                encoding="utf-8",
            )
            self.assertEqual(PartylineAdapter._snapshot_sequences(path), {0, 2})

    async def test_delivery_uses_acp_prompt_request_not_bracketed_paste(self):
        adapter = self.make()
        adapter._session_id = "session-1"
        adapter.format_digest = lambda _messages: "wake"
        adapter._request = AsyncMock()
        adapter._silent_until_wake = True
        await adapter.deliver([{"id": 4, "body": "wake"}])
        adapter._request.assert_awaited_once_with("session/prompt", {
            "sessionId": "session-1", "prompt": [{"type": "text", "text": "wake"}],
        })
        self.assertFalse(adapter._silent_until_wake)

    async def test_resumed_delivery_releases_silence_before_reply_is_tailed(self):
        adapter = self.make(resume=True)
        adapter._session_id = "session-1"
        adapter.format_digest = lambda _messages: "wake"
        pending = asyncio.get_running_loop().create_future()

        async def wait_for_request(*_args, **_kwargs):
            await pending
            return {}

        adapter._request = AsyncMock(side_effect=wait_for_request)
        task = asyncio.create_task(adapter.deliver([{"id": 4, "body": "wake"}]))
        await asyncio.sleep(0)
        self.assertFalse(adapter._silent_until_wake)
        await adapter._handle_record({
            "seq": 5,
            "type": "assistant/message",
            "data": {
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "resumed reply"}],
                }
            },
        })
        self.assertEqual(self.messages, [("luna", "agent", "resumed reply")])
        pending.set_result({})
        await task

    async def test_setup_failure_marks_adapter_not_ready(self):
        adapter = self.make()
        adapter._request = AsyncMock(side_effect=RuntimeError("bad profile"))
        adapter._mark_not_ready = Mock()
        await adapter._run()
        adapter._mark_not_ready.assert_called_once_with()
        self.assertIn("ACP setup failed", self.messages[0][2])


if __name__ == "__main__":
    unittest.main()
