"""OpenCode v2 fixtures mirror its session_v2/session_message store."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch, Mock

from partyline.adapters.bundled.opencode.v2 import PartylineAdapter
from partyline.adapters.receipts import BEGAN, ENDED


class OpenCodeV2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "opencode.db"
        self.db = sqlite3.connect(self.store)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE session_v2(id TEXT, directory TEXT, parent_id TEXT);
            CREATE TABLE session_message(id TEXT, session_id TEXT, type TEXT,
                                         seq INTEGER, time_created INTEGER, data TEXT);
            INSERT INTO session_v2 VALUES('ours', '/project', NULL);
            INSERT INTO session_v2 VALUES('other', '/project', NULL);
            INSERT INTO session_v2 VALUES('child', '/project', 'ours');
        """)
        self.post = AsyncMock()
        self.adapter = self.make()
        PartylineAdapter._CLAIMED.clear()
        self.addCleanup(PartylineAdapter._CLAIMED.clear)

    def make(self, **extra):
        att = dict(id="a", name="agent", conv_id="line", conv="room", cwd="/project",
                   command=[], adapter_metadata={"capabilities": {"transcript": True}})
        att.update(extra)
        adapter = PartylineAdapter(att, self.post, AsyncMock())
        adapter._store = self.store
        adapter.spawned_at = 1
        return adapter

    def row(self, ident, kind, data, seq=1, session="ours", created=1000):
        self.db.execute("INSERT INTO session_message VALUES(?,?,?,?,?,?)",
                        (ident, session, kind, seq, created, json.dumps(data)))
        self.db.commit()

    def claim(self):
        self.row("claim", "user", {"text": self.adapter._claim_token})
        self.adapter._session_id = self.adapter._find_session()

    def test_command_is_interactive_private_and_claimed(self):
        command = self.adapter.build_command()
        self.assertEqual(command[:4], ["opencode2", "--standalone", "--auto", "--prompt"])
        self.assertIn(self.adapter._claim_token, command[-1])
        resumed = self.make(resume=True, cli_session="ours")
        self.assertIn("--session", resumed.build_command())
        self.assertIn("READY", resumed.build_command()[-1])
        for args in (["--server", "remote"], ["--server=remote"], ["--standalone=false"],
                     ["--no-standalone"], ["--prompt=x"], ["--prompt", "x"]):
            with self.assertRaises(ValueError):
                self.make(command=["opencode2", *args]).build_command()
        with self.assertRaises(ValueError):
            self.make(command=["opencode2", "-s", "x"], resume=True,
                      cli_session="ours").build_command()
        command = self.make(command=["custom", "--standalone"]).build_command()
        self.assertEqual(command.count("--standalone"), 1)

    def test_store_path_comes_from_selected_binary(self):
        with patch("partyline.adapters.bundled.opencode.v2.subprocess.run") as run:
            run.return_value.stdout = str(self.store) + "\n"
            self.assertEqual(self.adapter._resolve_store(), self.store)
            self.assertEqual(run.call_args.args[0], ["opencode2", "debug", "paths", "db"])
            run.return_value.stdout = ":memory:"
            with self.assertRaises(ValueError):
                self.adapter._resolve_store()

    def test_v2_database_is_separate_unless_explicitly_overridden(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(self.adapter.spawn_env(), {"OPENCODE_DB": "opencode-v2.db"})
        with patch.dict("os.environ", {"OPENCODE_DB": "/custom/session.db"}):
            self.assertEqual(self.adapter.spawn_env(), {"OPENCODE_DB": "/custom/session.db"})

    def test_claim_rejects_neighbors_old_markers_and_children(self):
        self.row("neighbor", "user", {"text": "another marker"}, session="other")
        self.row("old", "user", {"text": self.adapter._claim_token}, created=999)
        self.row("child", "user", {"text": self.adapter._claim_token}, session="child")
        self.row("fake", "user", {"metadata": self.adapter._claim_token})
        self.assertIsNone(self.adapter._find_session())
        self.claim()
        self.assertEqual(self.adapter._session_id, "ours")
        self.assertTrue(self.adapter._claim_proven)
        PartylineAdapter._CLAIMED.add((str(self.store), "ours"))
        self.assertIsNone(self.adapter._find_session())
        self.assertIsNone(self.make()._find_session())

    def test_resume_cannot_claim_a_different_session(self):
        self.adapter.resume = True
        self.adapter.att["cli_session"] = "other"
        self.claim()
        self.assertIsNone(self.adapter._session_id)

    async def test_completed_speech_only_and_idle_closes_turn_once(self):
        self.row("history", "assistant", {"time": {"completed": 1}, "content": [
            {"type": "text", "text": "old"}]}, seq=0)
        self.claim()
        self.row("stream", "assistant", {"time": {}, "content": [{"type": "text", "text": "partial"}]}, seq=2)
        self.row("summary", "compaction", {"summary": "private summary"}, seq=3)
        self.row("answer", "assistant", {"time": {"completed": 1500}, "content": [
            {"type": "reasoning", "text": "private"}, {"type": "tool", "text": "tool output"},
            {"type": "text", "text": "answer"}, {}, None, {"type": "text", "text": 3}]}, seq=4)
        self.row("steer", "user", {"text": "follow-up"}, seq=5)
        self.row("idle", "idle", {"outcome": "interrupted"}, seq=6)
        with patch("partyline.adapters.bundled.opencode.v2.receipt", new_callable=AsyncMock) as receipt:
            await self.adapter._poll()
            await self.adapter._poll()
        self.assertEqual([c.args[1] for c in receipt.call_args_list], [BEGAN, ENDED])
        self.post.assert_awaited_once_with("agent", "agent", "answer")
        self.assertTrue(self.adapter._ready_result)
        self.db.execute("UPDATE session_message SET data=? WHERE id='stream'", (json.dumps({
            "time": {"completed": 1600}, "content": [{"type": "text", "text": "finished"}]}),))
        self.db.commit()
        await self.adapter._poll()
        self.assertEqual(self.post.call_args.args[-1], "finished")

    async def test_speech_gate_and_malformed_data(self):
        self.adapter._session_id = "ours"
        for i, data in enumerate((None, [], {}, {"time": None}, {"time": {"completed": 1}, "content": 5})):
            self.row(str(i), "assistant", data, seq=i)
        self.row("speech", "assistant", {"time": {"completed": 1}, "content": [
            {"type": "text", "text": "unclaimed"}]}, seq=7)
        await self.adapter._poll()
        self.post.assert_not_awaited()
        self.assertEqual(self.adapter._decode("bad json"), {})

    async def test_wake_receipt_requires_recorded_user_marker(self):
        self.claim()
        await self.adapter._poll()
        confirm = AsyncMock(return_value=True)
        self.adapter.att["confirm_delivery_ids"] = confirm
        self.adapter._wake_receipts = [{"digest": "message", "marker": "paste-marker",
                                       "ids": [42], "proven": False}]
        self.row("wake", "user", {"text": "message paste-marker"}, seq=2)
        await self.adapter._poll()
        confirm.assert_awaited_once_with([42])
        self.assertEqual(self.adapter._confirmed_delivery_ids, {42})

    async def test_run_claims_and_polls_then_stop_releases(self):
        self.claim()
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(side_effect=[True, True, False])
        self.adapter.on_cli_session = Mock()
        with patch("partyline.adapters.bundled.opencode.v2.asyncio.sleep", new_callable=AsyncMock):
            await self.adapter._run()
        self.adapter.on_cli_session.assert_called_once_with("ours")
        self.assertIn((str(self.store), "ours"), PartylineAdapter._CLAIMED)
        with patch("partyline.adapters.base.Adapter.stop", new_callable=AsyncMock):
            await self.adapter.stop()
        self.assertNotIn((str(self.store), "ours"), PartylineAdapter._CLAIMED)

    async def test_run_handles_missing_store_timeout_and_exit(self):
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(return_value=True)
        self.adapter._find_session = Mock(side_effect=sqlite3.OperationalError("busy"))
        with patch("partyline.adapters.bundled.opencode.v2.asyncio.sleep", new_callable=AsyncMock):
            await self.adapter._run()
        self.assertIn("45s", self.post.call_args.args[-1])
        self.adapter.alive = Mock(return_value=False)
        await self.adapter._run()

    async def test_poll_failure_is_retried(self):
        self.claim()
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(side_effect=[True, True, False])
        self.adapter._poll = AsyncMock(side_effect=sqlite3.OperationalError("busy"))
        with patch("partyline.adapters.bundled.opencode.v2.asyncio.sleep", new_callable=AsyncMock):
            await self.adapter._run()
        self.adapter._poll.assert_awaited_once()

    async def test_prefilled_prompt_gets_one_enter_but_screen_never_proves_claim(self):
        self.adapter._resolve_store = Mock(return_value=self.store)
        self.adapter.alive = Mock(return_value=True)
        self.adapter.screen_text = Mock(return_value=self.adapter._claim_token)
        self.adapter._write_all = AsyncMock()
        with patch("partyline.adapters.bundled.opencode.v2.asyncio.sleep", new_callable=AsyncMock):
            await self.adapter._run()
        self.adapter._write_all.assert_awaited_once_with(b"\r")
        self.assertFalse(self.adapter._claim_proven)
        self.assertIsNone(self.adapter._ready_result)
        self.assertTrue(all(call.args[1] == "system" for call in self.post.call_args_list))

    async def test_compaction_rewrite_does_not_replay_speech_or_adopt_sibling(self):
        self.claim()
        answer = {"time": {"completed": 1500}, "content": [{"type": "text", "text": "answer"}]}
        self.row("answer", "assistant", answer, seq=2)
        await self.adapter._poll()
        self.db.execute("DELETE FROM session_message")
        self.db.commit()
        self.row("answer", "assistant", answer, seq=2)
        self.row("compact", "compaction", {"status": "completed", "summary": "private",
                                           "recent": "private"}, seq=3)
        self.row("sibling", "assistant", answer, seq=4, session="other")
        await self.adapter._poll()
        self.post.assert_awaited_once_with("agent", "agent", "answer")
