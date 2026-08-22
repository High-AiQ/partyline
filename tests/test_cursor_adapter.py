"""Unit tests for the bundled Cursor adapter (`agent`).

Deterministic coverage without spawning the `agent` executable or touching
real network/CLI endpoints.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.cursor.adapter import PartylineAdapter
from partyline.adapters.bundled.cursor.parse import (
    chat_dir,
    cwd_md5,
    cwd_slug,
    fingerprint,
    parse_record,
    resync_fingerprints,
    transcript_path,
)
from partyline.adapters.receipts import BEGAN, ENDED


class Process:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def stop(self):
        self.returncode = 0


def attachment(name="agent", *, cwd="/test/project", command=None, **extra):
    return {
        "id": name + "-id",
        "name": name,
        "cwd": cwd,
        "command": command,
        "adapter_metadata": {"command": ["agent", "--yolo", "--trust"]},
        **extra,
    }


class CursorAdapterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.messages: list[tuple[str, str, str]] = []
        self.statuses: list[str] = []
        self.sessions: list[str] = []
        PartylineAdapter._CLAIMED.clear()
        self.addCleanup(PartylineAdapter._CLAIMED.clear)

    async def post(self, sender: str, sender_type: str, body: str) -> None:
        self.messages.append((sender, sender_type, body))

    async def status(self, value: str) -> None:
        self.statuses.append(value)

    def on_cli_session(self, session_id: str) -> None:
        self.sessions.append(session_id)

    def make_adapter(self, **att_extra) -> PartylineAdapter:
        adapter = PartylineAdapter(
            attachment(**att_extra),
            self.post,
            self.status,
            on_cli_session=self.on_cli_session,
        )
        adapter.INITIAL_DELAY = 0
        adapter.POLL_SECONDS = 0.01
        return adapter

    def test_manifest(self):
        import tomllib

        manifest_path = (
            Path(__file__).parent.parent
            / "partyline"
            / "adapters"
            / "bundled"
            / "cursor"
            / "adapter.toml"
        )
        with open(manifest_path, "rb") as fh:
            data = tomllib.load(fh)["adapter"]

        self.assertEqual(data["name"], "Cursor")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["entrypoint"], "adapter.py")
        self.assertEqual(data["command"], ["agent", "--yolo", "--trust"])
        self.assertEqual(data["requires"], ["agent"])
        self.assertEqual(data["update_command"], ["agent", "update"])
        self.assertTrue(data["capabilities"]["resume"])
        self.assertEqual(data["capabilities"]["turn_end"], "receipt")

    def test_build_command(self):
        # Default fresh command
        fresh = self.make_adapter()
        self.assertEqual(fresh.build_command(), ["agent", "--yolo", "--trust"])

        # Custom fresh command
        custom = self.make_adapter(command=["agent", "--model", "composer-2.5"])
        self.assertEqual(custom.build_command(), ["agent", "--model", "composer-2.5"])

        # Resume command
        resumed = self.make_adapter(resume=True, cli_session="3ebd57db-5810-460b")
        self.assertEqual(
            resumed.build_command(),
            ["agent", "--yolo", "--trust", "--resume", "3ebd57db-5810-460b"],
        )

        # Resume when --resume already in command
        already = self.make_adapter(
            command=["agent", "--resume", "3ebd57db-5810-460b"],
            resume=True,
            cli_session="3ebd57db-5810-460b",
        )
        self.assertEqual(
            already.build_command(), ["agent", "--resume", "3ebd57db-5810-460b"]
        )

        # Resume when -r in command
        short_r = self.make_adapter(
            command=["agent", "-r", "3ebd57db-5810-460b"],
            resume=True,
            cli_session="3ebd57db-5810-460b",
        )
        self.assertEqual(short_r.build_command(), ["agent", "-r", "3ebd57db-5810-460b"])

    def test_parsing_helpers(self):
        cwd = "/tmp/opencode/cursor-probe"
        self.assertEqual(cwd_slug(cwd), "tmp-opencode-cursor-probe")
        self.assertEqual(cwd_slug("/home/gmccarthy"), "home-gmccarthy")
        self.assertEqual(cwd_slug("///abc///def///"), "abc-def")

        import hashlib

        expected_md5 = hashlib.md5(os.path.realpath(cwd).encode("utf-8")).hexdigest()
        self.assertEqual(cwd_md5(cwd), expected_md5)

        trans_path = transcript_path(cwd, "test-uuid")
        self.assertEqual(
            trans_path,
            Path.home()
            / ".cursor"
            / "projects"
            / "tmp-opencode-cursor-probe"
            / "agent-transcripts"
            / "test-uuid"
            / "test-uuid.jsonl",
        )

        self.assertEqual(
            chat_dir(cwd), Path.home() / ".cursor" / "chats" / expected_md5
        )

    def test_parse_record(self):
        # User message -> BEGAN
        self.assertEqual(
            parse_record(
                {
                    "role": "user",
                    "message": {"content": [{"type": "text", "text": "hello"}]},
                }
            ),
            (BEGAN, None),
        )
        self.assertEqual(
            parse_record({"message": {"role": "user", "content": "hi"}}),
            (BEGAN, None),
        )

        # Turn ended status -> ENDED
        self.assertEqual(
            parse_record({"type": "turn_ended", "status": "success"}), (ENDED, None)
        )
        self.assertEqual(
            parse_record({"type": "turn_ended", "status": "error"}), (ENDED, None)
        )
        self.assertEqual(
            parse_record({"type": "turn_ended", "status": "aborted"}), (ENDED, None)
        )
        self.assertEqual(
            parse_record({"type": "turn_ended", "status": "other"}), (ENDED, None)
        )

        # Assistant text -> body
        self.assertEqual(
            parse_record(
                {
                    "role": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "first block"},
                            {"type": "text", "text": "second block"},
                        ]
                    },
                }
            ),
            (None, "first block\n\nsecond block"),
        )
        self.assertEqual(
            parse_record({"role": "assistant", "content": "string content"}),
            (None, "string content"),
        )
        self.assertEqual(
            parse_record(
                {"role": "assistant", "type": "text", "text": "direct text"}
            ),
            (None, "direct text"),
        )

        # Assistant tool_use alongside text -> skipped
        self.assertEqual(
            parse_record(
                {
                    "role": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Checking how to post...\n\n[REDACTED]"},
                            {"type": "tool_use", "name": "Shell", "input": {"command": "ls"}},
                        ]
                    },
                }
            ),
            (None, None),
        )

        # Assistant text with [REDACTED] stripped
        self.assertEqual(
            parse_record(
                {
                    "role": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "hello from composer\n\n[REDACTED]"}
                        ]
                    },
                }
            ),
            (None, "hello from composer"),
        )

        # Assistant text with ONLY [REDACTED] -> skipped
        self.assertEqual(
            parse_record(
                {
                    "role": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "[REDACTED]"}
                        ]
                    },
                }
            ),
            (None, None),
        )

        # String content with [REDACTED]
        self.assertEqual(
            parse_record({"role": "assistant", "content": "hello\n\n[REDACTED]"}),
            (None, "hello"),
        )
        self.assertEqual(
            parse_record({"role": "assistant", "content": "[REDACTED]"}),
            (None, None),
        )

        # Top-level text record with [REDACTED]
        self.assertEqual(
            parse_record({"type": "text", "text": "[REDACTED]"}),
            (None, None),
        )
        self.assertEqual(
            parse_record({"type": "text", "text": "isolated [REDACTED] text"}),
            (None, "isolated  text"),
        )

        # Unrelated record
        self.assertEqual(
            parse_record({"type": "progress", "percent": 50}), (None, None)
        )

    def test_discovery_and_claims(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            now = time.time()
            chat_base = Path(tmpdir) / "chats" / "mock-md5"
            chat_base.mkdir(parents=True)

            sess1 = chat_base / "uuid-1"
            sess1.mkdir()
            os.utime(sess1, (now - 1, now - 1))

            sess2 = chat_base / "uuid-2"
            sess2.mkdir()
            os.utime(sess2, (now, now))

            adapter1 = self.make_adapter(cwd="/mock/cwd")
            adapter1.spawned_at = now
            adapter2 = self.make_adapter(cwd="/mock/cwd")
            adapter2.spawned_at = now

            with patch(
                "partyline.adapters.bundled.cursor.adapter.chat_dir",
                return_value=chat_base,
            ):
                # adapter1 discovers newest first
                found1 = adapter1._find_chat()
                self.assertEqual(found1, "uuid-2")
                PartylineAdapter._CLAIMED.add("uuid-2")

                # adapter2 skips claimed uuid-2 and claims uuid-1
                found2 = adapter2._find_chat()
                self.assertEqual(found2, "uuid-1")
                PartylineAdapter._CLAIMED.add("uuid-1")

                # No more available sessions
                self.assertIsNone(adapter1._find_chat())

    async def test_stop_releases_claim(self):
        adapter = self.make_adapter()
        adapter._session_id = "test-uuid-claimed"
        PartylineAdapter._CLAIMED.add("test-uuid-claimed")

        await adapter.stop()
        self.assertNotIn("test-uuid-claimed", PartylineAdapter._CLAIMED)

    async def test_tail_and_receipts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "agent.jsonl"
            lines = [
                json.dumps(
                    {
                        "role": "user",
                        "message": {"content": [{"type": "text", "text": "start"}]},
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {
                            "content": [{"type": "tool_call", "name": "exec"}]
                        },
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "Done with task"}]
                        },
                    }
                )
                + "\n",
                json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
            ]
            path.write_text("".join(lines), encoding="utf-8")

            adapter = self.make_adapter(hook_url="http://hook.local")
            adapter.proc = Process()

            receipts_seen: list[tuple[dict, str]] = []

            async def mock_receipt(att, event):
                receipts_seen.append((att, event))

            with patch(
                "partyline.adapters.bundled.cursor.adapter.receipt",
                side_effect=mock_receipt,
            ):
                task = asyncio.create_task(adapter._tail_transcript(path))
                await asyncio.sleep(0.05)
                adapter.proc.stop()
                await task

            self.assertEqual(self.messages, [("agent", "agent", "Done with task")])
            self.assertEqual(
                [event for _, event in receipts_seen], [BEGAN, ENDED]
            )

    async def test_resume_no_replay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "agent.jsonl"
            old_lines = [
                json.dumps(
                    {
                        "role": "user",
                        "message": {"content": [{"type": "text", "text": "old query"}]},
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {"content": [{"type": "text", "text": "old reply"}]},
                    }
                )
                + "\n",
                json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
            ]
            path.write_text("".join(old_lines), encoding="utf-8")

            adapter = self.make_adapter(resume=True, cli_session="sess-1")
            adapter.proc = Process()
            # Resumed adapter is woken by delivery
            adapter._silent_until_wake = False

            receipts_seen: list[str] = []

            async def mock_receipt(att, event):
                receipts_seen.append(event)

            with patch(
                "partyline.adapters.bundled.cursor.adapter.receipt",
                side_effect=mock_receipt,
            ):
                task = asyncio.create_task(adapter._tail_transcript(path))
                await asyncio.sleep(0.05)

                # Append new turn
                new_lines = [
                    json.dumps(
                        {
                            "role": "user",
                            "message": {
                                "content": [{"type": "text", "text": "new query"}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "assistant",
                            "message": {
                                "content": [{"type": "text", "text": "new reply"}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
                ]
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write("".join(new_lines))

                await asyncio.sleep(0.05)
                adapter.proc.stop()
                await task

            # Only new turn should be emitted
            self.assertEqual(self.messages, [("agent", "agent", "new reply")])
            self.assertEqual(receipts_seen, [BEGAN, ENDED])

    async def test_rewrite_and_compaction_survival(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "agent.jsonl"
            initial_lines = [
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {"content": [{"type": "text", "text": "msg 1"}]},
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {"content": [{"type": "text", "text": "msg 2"}]},
                    }
                )
                + "\n",
            ]
            path.write_text("".join(initial_lines), encoding="utf-8")

            adapter = self.make_adapter()
            adapter.proc = Process()

            task = asyncio.create_task(adapter._tail_transcript(path))
            await asyncio.sleep(0.05)
            self.assertEqual(
                self.messages,
                [("agent", "agent", "msg 1"), ("agent", "agent", "msg 2")],
            )

            # Full file rewrite with same content plus msg 3
            rewritten_lines = initial_lines + [
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {"content": [{"type": "text", "text": "msg 3"}]},
                    }
                )
                + "\n"
            ]
            path.write_text("".join(rewritten_lines), encoding="utf-8")
            await asyncio.sleep(0.05)

            # msg 1 and msg 2 should not be repeated
            self.assertEqual(
                self.messages,
                [
                    ("agent", "agent", "msg 1"),
                    ("agent", "agent", "msg 2"),
                    ("agent", "agent", "msg 3"),
                ],
            )

            # Compaction: msg 1 dropped, file starts with msg 2, msg 3, msg 4
            compacted_lines = rewritten_lines[1:] + [
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {"content": [{"type": "text", "text": "msg 4"}]},
                    }
                )
                + "\n"
            ]
            path.write_text("".join(compacted_lines), encoding="utf-8")
            await asyncio.sleep(0.05)

            adapter.proc.stop()
            await task

            self.assertEqual(
                self.messages,
                [
                    ("agent", "agent", "msg 1"),
                    ("agent", "agent", "msg 2"),
                    ("agent", "agent", "msg 3"),
                    ("agent", "agent", "msg 4"),
                ],
            )

    def test_fingerprint_canonicalization(self):
        # Different escaping / unicode representations should produce identical fingerprints
        line1 = '{"role": "assistant", "text": "hello \\u2014 world"}\n'
        line2 = '{"role": "assistant", "text": "hello — world"}\n'
        self.assertEqual(fingerprint(line1), fingerprint(line2))

        # Differing key orders / whitespace
        dict1 = {"b": 2, "a": 1}
        dict2 = {"a": 1, "b": 2}
        self.assertEqual(fingerprint(dict1), fingerprint(dict2))
        self.assertEqual(fingerprint(json.dumps(dict1)), fingerprint(json.dumps(dict2)))

    def test_resync_fingerprints_helper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "f.jsonl"
            lines = ["line 1\n", "line 2\n", "line 3\n"]
            path.write_text("".join(lines), encoding="utf-8")
            fps = [fingerprint(line) for line in lines]

            # Matching prefix
            self.assertEqual(resync_fingerprints(path, fps[:2]), fps[:2])

            # Compaction / front truncation
            comp_path = Path(tmpdir) / "comp.jsonl"
            comp_lines = ["line 2\n", "line 3\n", "line 4\n"]
            comp_path.write_text("".join(comp_lines), encoding="utf-8")
            comp_fps = [fingerprint(line) for line in comp_lines]
            self.assertEqual(resync_fingerprints(comp_path, fps), comp_fps[:2])

            # Suffix match on edited prefix
            mod_lines = ["line 0\n", "line 2\n", "line 3\n"]
            mod_path = Path(tmpdir) / "mod.jsonl"
            mod_path.write_text("".join(mod_lines), encoding="utf-8")
            mod_fps = [fingerprint(line) for line in mod_lines]
            self.assertEqual(resync_fingerprints(mod_path, fps), mod_fps)

            # Subsegment match with front insertion
            sub_lines = ["meta\n", "line 2\n", "line 3\n", "line 4\n"]
            sub_path = Path(tmpdir) / "sub.jsonl"
            sub_path.write_text("".join(sub_lines), encoding="utf-8")
            sub_fps = [fingerprint(line) for line in sub_lines]
            self.assertEqual(resync_fingerprints(sub_path, fps), sub_fps[:3])

            # Disjoint file preserves seen_fps unchanged
            dis_lines = ["other 1\n", "other 2\n"]
            dis_path = Path(tmpdir) / "dis.jsonl"
            dis_path.write_text("".join(dis_lines), encoding="utf-8")
            self.assertEqual(resync_fingerprints(dis_path, fps), fps)

            # Non-existent file returns input
            missing = Path(tmpdir) / "missing.jsonl"
            self.assertEqual(resync_fingerprints(missing, fps), fps)

            # Empty seen
            self.assertEqual(resync_fingerprints(path, []), [])

    async def test_run_discovery_timeout_and_retries(self):
        adapter = self.make_adapter()
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        adapter._find_chat = lambda: None
        adapter.DISCOVERY_TIMEOUT = 0.05
        adapter.POLL_SECONDS = 0.01

        await adapter._run()
        self.assertIn("no Cursor session appeared", self.messages[-1][2])

        # Process death before discovery
        dead_adapter = self.make_adapter()
        dead_adapter.proc = Process()
        dead_adapter.proc.stop()
        await dead_adapter._run()

    async def test_run_success_fresh_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript = Path(tmpdir) / "test-sess.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {"content": [{"type": "text", "text": "hello"}]},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            adapter = self.make_adapter()
            adapter.proc = Process()
            adapter.send_keys = AsyncMock()
            adapter._find_chat = lambda: "test-sess"

            with patch(
                "partyline.adapters.bundled.cursor.adapter.transcript_path",
                return_value=transcript,
            ):
                task = asyncio.create_task(adapter._run())
                await asyncio.sleep(0.05)
                adapter.proc.stop()
                await task

            self.assertEqual(self.sessions, ["test-sess"])
            self.assertEqual(self.messages, [("agent", "agent", "hello")])
            self.assertTrue(await adapter.wait_ready())

    async def test_find_chat_error_and_edge_branches(self):
        # chat_dir does not exist
        adapter = self.make_adapter(cwd="/nonexistent/path")
        with patch("partyline.adapters.bundled.cursor.adapter.chat_dir", return_value=Path("/nonexistent")):
            self.assertIsNone(adapter._find_chat())

        # resume with claimed session
        adapter_resumed = self.make_adapter(resume=True, cli_session="claimed-uuid")
        PartylineAdapter._CLAIMED.add("claimed-uuid")
        self.assertIsNone(adapter_resumed._find_chat())

        # stale session mtime
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_base = Path(tmpdir)
            stale_dir = chat_base / "stale-uuid"
            stale_dir.mkdir()
            os.utime(stale_dir, (100, 100))
            adapter_stale = self.make_adapter(cwd="/test/path")
            adapter_stale.spawned_at = 1000.0
            with patch("partyline.adapters.bundled.cursor.adapter.chat_dir", return_value=chat_base):
                self.assertIsNone(adapter_stale._find_chat())

        # chats.iterdir() OSError
        with patch("partyline.adapters.bundled.cursor.adapter.chat_dir") as mock_cd:
            mock_cd.return_value.is_dir.return_value = True
            mock_cd.return_value.iterdir.side_effect = OSError("iter error")
            self.assertIsNone(adapter.find_chat() if hasattr(adapter, "find_chat") else adapter._find_chat())

    def test_is_replaced_handles_oserror(self):
        adapter = self.make_adapter()
        with patch("pathlib.Path.stat", side_effect=OSError("stat failed")):
            self.assertTrue(adapter._is_replaced(None, Path("/mock/path"), 123))

    async def test_tail_transcript_filters_tool_use_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "composer.jsonl"
            records = [
                {"role": "user", "message": {"content": [{"type": "text", "text": "say hello"}]}},
                {
                    "role": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Checking tools...\n\n[REDACTED]"},
                            {"type": "tool_use", "name": "Shell", "input": {"command": "ls"}},
                        ]
                    },
                },
                {"role": "assistant", "message": {"content": [{"type": "text", "text": "[REDACTED]"}]}},
                {
                    "role": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "composer here — connected.\n\n[REDACTED]"}
                        ]
                    },
                },
                {"type": "turn_ended", "status": "success"},
            ]
            path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

            adapter = self.make_adapter()
            adapter.proc = Process()

            receipts_seen: list[str] = []

            async def mock_receipt(att, event):
                receipts_seen.append(event)

            with patch(
                "partyline.adapters.bundled.cursor.adapter.receipt",
                side_effect=mock_receipt,
            ):
                task = asyncio.create_task(adapter._tail_transcript(path))
                await asyncio.sleep(0.05)
                adapter.proc.stop()
                await task

            self.assertEqual(receipts_seen, [BEGAN, ENDED])
            self.assertEqual(self.messages, [("agent", "agent", "composer here — connected.")])

    async def test_tail_transcript_sanitized_fixture(self):
        fixture_path = Path(__file__).parent / "fixtures" / "cursor_transcript.jsonl"
        self.assertTrue(fixture_path.is_file())

        adapter = self.make_adapter()
        adapter.proc = Process()

        receipts_seen: list[str] = []

        async def mock_receipt(att, event):
            receipts_seen.append(event)

        with patch(
            "partyline.adapters.bundled.cursor.adapter.receipt",
            side_effect=mock_receipt,
        ):
            task = asyncio.create_task(adapter._tail_transcript(fixture_path))
            await asyncio.sleep(0.05)
            adapter.proc.stop()
            await task

        self.assertEqual(receipts_seen, [BEGAN, BEGAN, ENDED])
        self.assertEqual(
            self.messages,
            [
                (
                    "agent",
                    "agent",
                    "Connected — I'm **composer**, on the line for the Cursor CLI adapter work; "
                    "standing by for @grok to assign.",
                ),
                (
                    "agent",
                    "agent",
                    "Connected and listening — standing by for @grok to assign; "
                    "not picking up #81 unless you hand it to me.",
                ),
            ],
        )

    async def test_tail_transcript_rewrite_with_changed_user_line_and_new_reply(self):
        fixture_path = Path(__file__).parent / "fixtures" / "cursor_transcript.jsonl"
        fixture_content = fixture_path.read_text(encoding="utf-8")
        fixture_lines = [line_text for line_text in fixture_content.splitlines() if line_text.strip()]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live.jsonl"
            path.write_text("\n".join(fixture_lines) + "\n", encoding="utf-8")

            adapter = self.make_adapter(resume=True, cli_session="sess-1")
            adapter.proc = Process()
            adapter._silent_until_wake = False

            receipts_seen: list[str] = []

            async def mock_receipt(att, event):
                receipts_seen.append(event)

            with patch(
                "partyline.adapters.bundled.cursor.adapter.receipt",
                side_effect=mock_receipt,
            ):
                task = asyncio.create_task(adapter._tail_transcript(path))
                await asyncio.sleep(0.05)

                self.assertEqual(self.messages, [])
                self.assertEqual(receipts_seen, [])

                rewritten_lines = list(fixture_lines)
                # Re-serialize user line 0 with escaped unicode and alternative key ordering
                user0 = json.loads(rewritten_lines[0])
                rewritten_lines[0] = json.dumps(
                    {"message": user0["message"], "role": "user"}
                ).replace("PM", "\\u0050\\u004d")

                # Re-serialize assistant line 8 with unicode escape \u2014
                rewritten_lines[8] = rewritten_lines[8].replace("—", "\\u2014")

                new_user = {
                    "role": "user",
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": "<timestamp>Sunday</timestamp>\n<user_query>test</user_query>",
                            }
                        ]
                    },
                }
                new_reply = {
                    "role": "assistant",
                    "message": {"content": [{"type": "text", "text": "4"}]},
                }
                new_turn_end = {"type": "turn_ended", "status": "success"}
                rewritten_lines.extend(
                    [json.dumps(new_user), json.dumps(new_reply), json.dumps(new_turn_end)]
                )

                path.write_text("\n".join(rewritten_lines) + "\n", encoding="utf-8")
                await asyncio.sleep(0.05)

                adapter.proc.stop()
                await task

                self.assertEqual(self.messages, [("agent", "agent", "4")])
                self.assertEqual(receipts_seen, [BEGAN, ENDED])

    async def test_consecutive_turns_with_identical_replies_and_ended(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live.jsonl"
            turn1 = [
                json.dumps(
                    {
                        "role": "user",
                        "message": {"content": [{"type": "text", "text": "q1"}]},
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {"content": [{"type": "text", "text": "ok"}]},
                    }
                )
                + "\n",
                json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
            ]
            path.write_text("".join(turn1), encoding="utf-8")

            adapter = self.make_adapter()
            adapter.proc = Process()

            receipts_seen: list[str] = []

            async def mock_receipt(att, event):
                receipts_seen.append(event)

            with patch(
                "partyline.adapters.bundled.cursor.adapter.receipt",
                side_effect=mock_receipt,
            ):
                task = asyncio.create_task(adapter._tail_transcript(path))
                await asyncio.sleep(0.05)

                self.assertEqual(self.messages, [("agent", "agent", "ok")])
                self.assertEqual(receipts_seen, [BEGAN, ENDED])

                turn2 = [
                    json.dumps(
                        {
                            "role": "user",
                            "message": {"content": [{"type": "text", "text": "q1"}]},
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "assistant",
                            "message": {"content": [{"type": "text", "text": "ok"}]},
                        }
                    )
                    + "\n",
                    json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
                ]
                with open(path, "a", encoding="utf-8") as f:
                    f.write("".join(turn2))
                await asyncio.sleep(0.05)

                adapter.proc.stop()
                await task

                self.assertEqual(
                    self.messages, [("agent", "agent", "ok"), ("agent", "agent", "ok")]
                )
                self.assertEqual(receipts_seen, [BEGAN, ENDED, BEGAN, ENDED])

    async def test_rewrite_with_front_edit_and_new_turn_emits_cleanly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live.jsonl"
            turn1 = [
                json.dumps(
                    {
                        "role": "user",
                        "message": {"content": [{"type": "text", "text": "q1"}]},
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {"content": [{"type": "text", "text": "ok"}]},
                    }
                )
                + "\n",
                json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
            ]
            path.write_text("".join(turn1), encoding="utf-8")

            adapter = self.make_adapter()
            adapter.proc = Process()

            receipts_seen: list[str] = []

            async def mock_receipt(att, event):
                receipts_seen.append(event)

            with patch(
                "partyline.adapters.bundled.cursor.adapter.receipt",
                side_effect=mock_receipt,
            ):
                task = asyncio.create_task(adapter._tail_transcript(path))
                await asyncio.sleep(0.05)

                self.assertEqual(self.messages, [("agent", "agent", "ok")])
                self.assertEqual(receipts_seen, [BEGAN, ENDED])

                # Front edit (inserted meta) + new completed turn in the rewrite
                rewritten = [
                    json.dumps({"type": "session_meta", "session_id": "sess-1"}) + "\n",
                    turn1[0],
                    turn1[1],
                    turn1[2],
                    json.dumps(
                        {
                            "role": "user",
                            "message": {"content": [{"type": "text", "text": "q2"}]},
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "assistant",
                            "message": {"content": [{"type": "text", "text": "ok"}]},
                        }
                    )
                    + "\n",
                    json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
                ]
                path.write_text("".join(rewritten), encoding="utf-8")
                await asyncio.sleep(0.05)

                adapter.proc.stop()
                await task

                self.assertEqual(
                    self.messages, [("agent", "agent", "ok"), ("agent", "agent", "ok")]
                )
                self.assertEqual(receipts_seen, [BEGAN, ENDED, BEGAN, ENDED])

    async def test_resume_snapshot_with_shifted_wrappers_and_new_turn_does_not_replay_old_speech(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live.jsonl"
            old_turns = [
                json.dumps(
                    {
                        "role": "user",
                        "message": {
                            "content": [{"type": "text", "text": "init briefing"}]
                        },
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "Connected"}]
                        },
                    }
                )
                + "\n",
                json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
                json.dumps(
                    {
                        "role": "user",
                        "message": {"content": [{"type": "text", "text": "wake 1"}]},
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "filter-ok"}]
                        },
                    }
                )
                + "\n",
                json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
            ]
            path.write_text("".join(old_turns), encoding="utf-8")

            adapter = self.make_adapter(resume=True, cli_session="sess-1")
            adapter.proc = Process()
            adapter._silent_until_wake = False

            receipts_seen: list[str] = []

            async def mock_receipt(att, event):
                receipts_seen.append(event)

            with patch(
                "partyline.adapters.bundled.cursor.adapter.receipt",
                side_effect=mock_receipt,
            ):
                task = asyncio.create_task(adapter._tail_transcript(path))
                await asyncio.sleep(0.05)

                self.assertEqual(self.messages, [])
                self.assertEqual(receipts_seen, [])

                # Cursor rewrites with shifted wrappers/prefixes across all records
                # (no suffix match) + new turn
                rewritten = [
                    json.dumps(
                        {"type": "wrapper_header", "meta": "session_init"}
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "user",
                            "context": "shifted",
                            "message": {
                                "content": [{"type": "text", "text": "shifted init"}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "assistant",
                            "extra": 1,
                            "message": {
                                "content": [{"type": "text", "text": "Connected"}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {"type": "turn_ended", "status": "success", "extra": 1}
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "user",
                            "context": "shifted",
                            "message": {
                                "content": [{"type": "text", "text": "shifted wake"}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "assistant",
                            "extra": 2,
                            "message": {
                                "content": [{"type": "text", "text": "filter-ok"}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {"type": "turn_ended", "status": "success", "extra": 2}
                    )
                    + "\n",
                    # New turn appended
                    json.dumps(
                        {
                            "role": "user",
                            "message": {
                                "content": [
                                    {"type": "text", "text": "real new prompt"}
                                ]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "assistant",
                            "message": {
                                "content": [{"type": "text", "text": "new reply"}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
                ]
                path.write_text("".join(rewritten), encoding="utf-8")
                await asyncio.sleep(0.05)

                adapter.proc.stop()
                await task

                # Old speech must not replay; positional escape hatch notice + new turn must post
                self.assertEqual(
                    self.messages,
                    [
                        (
                            "system",
                            "system",
                            "@agent: transcript rewritten beyond recognition — re-anchoring positionally",
                        ),
                        ("agent", "agent", "new reply"),
                    ],
                )
                self.assertEqual(receipts_seen, [ENDED, BEGAN, ENDED])

    async def test_resume_snapshot_with_front_header_and_new_turn_emits_cleanly(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "live.jsonl"
            old_turns = [
                json.dumps(
                    {
                        "role": "user",
                        "message": {
                            "content": [{"type": "text", "text": "init briefing"}]
                        },
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "Connected"}]
                        },
                    }
                )
                + "\n",
                json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
            ]
            path.write_text("".join(old_turns), encoding="utf-8")

            adapter = self.make_adapter(resume=True, cli_session="sess-1")
            adapter.proc = Process()
            adapter._silent_until_wake = False

            receipts_seen: list[str] = []

            async def mock_receipt(att, event):
                receipts_seen.append(event)

            with patch(
                "partyline.adapters.bundled.cursor.adapter.receipt",
                side_effect=mock_receipt,
            ):
                task = asyncio.create_task(adapter._tail_transcript(path))
                await asyncio.sleep(0.05)

                self.assertEqual(self.messages, [])
                self.assertEqual(receipts_seen, [])

                # Cursor rewrites with inserted header + past records + new turn
                rewritten = [
                    json.dumps(
                        {"type": "wrapper_header", "meta": "session_init"}
                    )
                    + "\n",
                    old_turns[0],
                    old_turns[1],
                    old_turns[2],
                    json.dumps(
                        {
                            "role": "user",
                            "message": {
                                "content": [
                                    {"type": "text", "text": "real new prompt"}
                                ]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "role": "assistant",
                            "message": {
                                "content": [{"type": "text", "text": "new reply"}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps({"type": "turn_ended", "status": "success"}) + "\n",
                ]
                path.write_text("".join(rewritten), encoding="utf-8")
                await asyncio.sleep(0.05)

                adapter.proc.stop()
                await task

                # Old speech must not replay; new turn posts directly via semantic re-anchoring
                self.assertEqual(
                    self.messages, [("agent", "agent", "new reply")]
                )
                self.assertEqual(receipts_seen, [BEGAN, ENDED])

    async def test_resume_snapshot_handles_oserror(self):
        adapter = self.make_adapter(resume=True, cli_session="sess-1")
        adapter.proc = Process()
        adapter.proc.stop()
        with patch("pathlib.Path.is_file", return_value=True):
            with patch("builtins.open", side_effect=OSError("snapshot read error")):
                await adapter._tail_transcript(Path("/fake/path.jsonl"))

    async def test_tail_transcript_edge_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "corrupt.jsonl"
            # half-written line + non-dict + bad json
            record = {"role": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}
            lines = [
                "not json\n",
                "[1, 2, 3]\n",
                json.dumps(record) + "\n",
                "half-line",
            ]
            path.write_text("".join(lines), encoding="utf-8")

            adapter = self.make_adapter()
            adapter.proc = Process()

            task = asyncio.create_task(adapter._tail_transcript(path))
            await asyncio.sleep(0.05)
            adapter.proc.stop()
            await task

            self.assertEqual(self.messages, [("agent", "agent", "ok")])

    async def test_run_retries_briefing_at_12s(self):
        adapter = self.make_adapter()
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        find_calls = 0

        def fake_find():
            nonlocal find_calls
            find_calls += 1
            if find_calls >= 3:
                return "found-uuid"
            return None

        adapter._find_chat = fake_find
        adapter.POLL_SECONDS = 6.0
        adapter.DISCOVERY_TIMEOUT = 30.0

        with (
            patch(
                "partyline.adapters.bundled.cursor.adapter.transcript_path",
                return_value=Path("/tmp/fake-trans"),
            ),
            patch.object(adapter, "_tail_transcript", AsyncMock()),
        ):
            with patch("pathlib.Path.is_file", return_value=True):
                await adapter._run()
            self.assertGreaterEqual(adapter.send_keys.await_count, 2)
            self.assertEqual(adapter._session_id, "found-uuid")

    async def test_run_transcript_file_timeout(self):
        adapter = self.make_adapter()
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        adapter._find_chat = lambda: "found-uuid"
        adapter.DISCOVERY_TIMEOUT = 0.05
        adapter.POLL_SECONDS = 0.01

        with patch(
            "partyline.adapters.bundled.cursor.adapter.transcript_path",
            return_value=Path("/tmp/missing-file"),
        ):
            await adapter._run()
            self.assertEqual(adapter._session_id, "found-uuid")


if __name__ == "__main__":
    unittest.main()
