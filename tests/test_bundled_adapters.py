"""Deterministic coverage for the bundled transcript adapters.

These tests exercise the adapters against small, temporary SQLite/JSONL
transcripts.  They deliberately do not start a CLI: the pty itself is owned by
the shared Adapter tests, while these tests focus on discovery and relaying
canonical transcript content.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.hermes.adapter import PartylineAdapter as HermesAdapter
from partyline.adapters.bundled.opencode import adapter as opencode_module
from partyline.adapters.bundled.opencode.adapter import PartylineAdapter as OpenCodeAdapter
from partyline.adapters.bundled.pi import adapter as pi_module
from partyline.adapters.bundled.pi.adapter import PartylineAdapter as PiAdapter
from partyline.adapters.bundled.raw import adapter as raw_module
from partyline.adapters.bundled.raw.adapter import RawAdapter


class Process:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def stop(self):
        self.returncode = 0


class RowsConnection:
    """Tiny context manager used to drive the adapter's polling error paths."""

    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args):
        return self

    def fetchall(self):
        return self.rows

    def close(self):
        pass


def attachment(name="agent", *, cwd="/project", command=None, **extra):
    return {
        "id": name + "-id",
        "name": name,
        "cwd": cwd,
        "command": command or ["fake-cli"],
        "adapter_metadata": {"command": ["fake-cli"]},
        **extra,
    }


class RecordingAdapterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.messages = []
        self.statuses = []

    async def post(self, sender, sender_type, body):
        self.messages.append((sender, sender_type, body))

    async def status(self, value):
        self.statuses.append(value)

    def make(self, cls, **att_extra):
        return cls(attachment(**att_extra), self.post, self.status)


class HermesAdapterTest(RecordingAdapterTest):
    def setUp(self):
        super().setUp()
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.env = patch.dict(os.environ, {"HERMES_HOME": self.home.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        HermesAdapter._claimed_sessions.clear()
        self.addCleanup(HermesAdapter._claimed_sessions.clear)

    def make_store(self):
        path = Path(self.home.name) / "state.db"
        db = sqlite3.connect(path)
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, cwd TEXT, started_at REAL);
            CREATE TABLE IF NOT EXISTS messages(
              id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
              content TEXT, active INTEGER DEFAULT 1
            );
            """
        )
        return db

    async def test_build_command_and_text_normalization(self):
        fresh = self.make(HermesAdapter)
        self.assertEqual(fresh.build_command(), ["fake-cli", "--cli", "--pass-session-id"])

        resumed = self.make(HermesAdapter, resume=True, cli_session="session-7")
        self.assertEqual(
            resumed.build_command(),
            ["fake-cli", "--cli", "--pass-session-id", "--resume", "session-7"],
        )
        self.assertEqual(HermesAdapter._text("plain"), "plain")
        self.assertEqual(HermesAdapter._text([{"text": "one"}, {"text": "two"}]), "one\n\ntwo")
        self.assertEqual(HermesAdapter._text({"content": "object"}), "object")
        self.assertEqual(HermesAdapter._text(None), "")
        self.assertEqual(HermesAdapter._text(7), "7")
        with self.assertRaises(ValueError):
            self.make(HermesAdapter, resume=True).build_command()
        existing_flags = self.make(
            HermesAdapter,
            command=["fake-cli", "--cli", "--pass-session-id", "-r", "old"],
            resume=True,
            cli_session="new",
        )
        self.assertEqual(
            existing_flags.build_command(), ["fake-cli", "--cli", "--pass-session-id", "-r", "old"]
        )
        HermesAdapter._release(None)

    async def test_discovery_matches_cwd_and_claims_each_session_once(self):
        db = self.make_store()
        now = time.time()
        db.executemany(
            "INSERT INTO sessions VALUES(?,?,?)",
            [
                ("first", "/project", now - 1),
                ("other", "/elsewhere", now - 0.5),
                ("second", "/project", now - 0.2),
            ],
        )
        db.commit()
        db.close()
        one = self.make(HermesAdapter)
        one.spawned_at = now
        two = self.make(HermesAdapter)
        two.spawned_at = now
        one._db = one._open_db()
        two._db = two._open_db()
        self.assertEqual(one._discover(), "first")
        self.assertEqual(two._discover(), "second")
        self.assertIsNone(one._discover())
        HermesAdapter._release("first")
        self.assertEqual(one._discover(), "first")
        one._db.close()
        two._db.close()

        self.assertTrue(one._same_cwd("/project"))
        self.assertFalse(one._same_cwd("/elsewhere"))
        self.assertFalse(one._same_cwd(None))
        one.att["cwd"] = object()
        self.assertFalse(one._same_cwd("/project"))
        one._db = None
        self.assertIsNone(one._discover())

        missing = self.make(HermesAdapter)
        with patch.object(missing, "_db_path", return_value=Path(self.home.name) / "missing.db"):
            self.assertIsNone(missing._open_db())

    async def test_tail_reposts_only_active_assistant_messages(self):
        db = self.make_store()
        db.executemany(
            "INSERT INTO messages(id,session_id,role,content,active) VALUES(?,?,?,?,?)",
            [
                (1, "s", "user", "question", 1),
                (2, "s", "assistant", "answer", 1),
                (3, "s", "assistant", json.dumps([{"text": "second"}]), 0),
                (4, "other", "assistant", "wrong session", 1),
                (5, "s", "assistant", "   ", 1),
            ],
        )
        db.commit()
        db.close()
        adapter = self.make(HermesAdapter)
        adapter._db = adapter._open_db()
        adapter.proc = Process()

        async def stop_after_post(*args):
            self.messages.append(args)
            adapter.proc.stop()

        adapter.post = stop_after_post
        await adapter._tail("s", 0)
        self.assertEqual(self.messages, [("agent", "agent", "answer")])
        adapter._db.close()

    async def test_run_handles_missing_store_and_process_exit(self):
        adapter = self.make(HermesAdapter)
        adapter.proc = Process()
        adapter.screen_text = lambda: "Welcome to Hermes Agent"
        await adapter._run()
        self.assertEqual(
            self.messages, [("system", "system", "@agent could not open the Hermes session store read-only")]
        )

        exited = self.make(HermesAdapter)
        exited.proc = Process()
        exited.proc.stop()
        await exited._run()
        self.assertEqual(self.messages[-1][2], "@agent could not open the Hermes session store read-only")

    async def test_run_timeout_and_missing_resume_session(self):
        db = self.make_store()
        db.close()
        timeout_adapter = self.make(HermesAdapter)
        timeout_adapter.proc = Process()
        timeout_adapter.screen_text = lambda: "Welcome to Hermes Agent"
        timeout_adapter.DISCOVERY_TIMEOUT = 999
        timeout_sleeps = 0
        timeout_adapter.send_keys = AsyncMock()
        timeout_adapter.send_key = lambda _key: None

        async def stop_after_discovery(_seconds):
            nonlocal timeout_sleeps
            timeout_sleeps += 1
            # The first sleep is the one after the briefing; the second is discovery.
            if timeout_sleeps > 1:
                timeout_adapter.proc.stop()

        timeout_adapter._discover = lambda: None
        with patch("partyline.adapters.bundled.hermes.adapter.asyncio.sleep", new=stop_after_discovery):
            await timeout_adapter._run()
        self.assertIn("no Hermes session appeared", self.messages[-1][2])

        no_callback = self.make(HermesAdapter)
        no_callback.proc = Process()
        no_callback.screen_text = lambda: "Welcome to Hermes Agent"
        no_callback.on_cli_session = None
        no_callback.send_keys = AsyncMock()
        no_callback.send_key = lambda _key: None
        no_callback._discover = lambda: "session-without-callback"
        no_callback._tail = AsyncMock()
        with patch("partyline.adapters.bundled.hermes.adapter.asyncio.sleep", new=AsyncMock()):
            await no_callback._run()

        missing_resume = self.make(HermesAdapter, resume=True, cli_session="")
        missing_resume.proc = Process()
        missing_resume.screen_text = lambda: "Welcome to Hermes Agent"
        await missing_resume._run()
        self.assertEqual(missing_resume._session_id, None)

    async def test_run_retries_startup_screen_until_process_exits(self):
        adapter = self.make(HermesAdapter)
        adapter.proc = Process()
        adapter.screen_text = lambda: "still starting"
        sleeps = 0

        async def sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            adapter.proc.stop()

        with patch("partyline.adapters.bundled.hermes.adapter.asyncio.sleep", new=sleep):
            await adapter._run()
        self.assertEqual(sleeps, 1)

    async def test_run_resume_uses_cursor_without_briefing(self):
        db = self.make_store()
        db.execute("INSERT INTO messages VALUES(?,?,?,?,?)", (9, "resume-s", "assistant", "old", 1))
        db.commit()
        db.close()
        adapter = self.make(HermesAdapter, resume=True, cli_session="resume-s")
        adapter.proc = Process()
        adapter.screen_text = lambda: "Welcome to Hermes Agent"
        seen = []

        async def tail(session_id, last_id):
            seen.append((session_id, last_id))
            adapter.proc.stop()

        adapter._tail = tail
        await adapter._run()
        self.assertEqual(seen, [("resume-s", 9)])
        self.assertEqual(self.messages, [])

    async def test_run_fresh_discovers_session_and_sends_briefing(self):
        db = self.make_store()
        now = time.time()
        db.execute("INSERT INTO sessions VALUES(?,?,?)", ("fresh-s", "/project", now))
        db.commit()
        db.close()
        adapter = self.make(HermesAdapter)
        adapter.spawned_at = now
        adapter.proc = Process()
        adapter.screen_text = lambda: "Welcome to Hermes Agent"
        sent = []
        sessions = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        adapter.send_key = lambda key: sent.append(key)
        adapter.on_cli_session = sessions.append

        async def tail(session_id, last_id):
            sessions.append((session_id, last_id))
            adapter.proc.stop()

        adapter._tail = tail
        with patch("partyline.adapters.bundled.hermes.adapter.asyncio.sleep", new=AsyncMock()):
            await adapter._run()
        self.assertEqual(sessions, ["fresh-s", ("fresh-s", 0)])
        self.assertEqual(sent, [adapter.briefing(), "enter"])


class OpenCodeAdapterTest(RecordingAdapterTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "opencode.db"
        self.original_store = opencode_module.STORE
        opencode_module.STORE = self.store
        self.addCleanup(self._restore_store)
        OpenCodeAdapter._CLAIMED.clear()
        self.addCleanup(OpenCodeAdapter._CLAIMED.clear)

    def _restore_store(self):
        opencode_module.STORE = self.original_store

    def make_store(self, *, session_id="session-1", cwd="/project", created=None):
        db = sqlite3.connect(self.store)
        db.executescript(
            """
            CREATE TABLE session(id TEXT PRIMARY KEY, directory TEXT, time_created INTEGER);
            CREATE TABLE message(id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE part(
              id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
              time_created INTEGER, data TEXT
            );
            """
        )
        db.execute("INSERT INTO session VALUES(?,?,?)", (session_id, cwd, created or int(time.time() * 1000)))
        db.commit()
        return db

    async def test_build_find_and_release_claims(self):
        plain = self.make(OpenCodeAdapter)
        self.assertEqual(plain.build_command(), ["fake-cli"])
        resumed = self.make(OpenCodeAdapter, resume=True, cli_session="resume-s")
        self.assertEqual(resumed.build_command(), ["fake-cli", "--session", "resume-s"])

        db = self.make_store()
        db.close()
        one = self.make(OpenCodeAdapter)
        one.spawned_at = time.time()
        two = self.make(OpenCodeAdapter)
        two.spawned_at = one.spawned_at
        self.assertEqual(one._find_session(), "session-1")
        OpenCodeAdapter._CLAIMED.add("session-1")
        self.assertIsNone(two._find_session())
        OpenCodeAdapter._CLAIMED.discard("session-1")
        self.assertEqual(two._find_session(), "session-1")

        resumed = self.make(OpenCodeAdapter, resume=True, cli_session="resume-s")
        self.assertEqual(resumed._find_session(), "resume-s")
        OpenCodeAdapter._CLAIMED.add("resume-s")
        self.assertIsNone(resumed._find_session())

        missing = self.make(OpenCodeAdapter)
        opencode_module.STORE = Path(self.tmp.name) / "missing.db"
        self.assertIsNone(missing._find_session())
        opencode_module.STORE = self.store
        with patch.object(missing, "_connect", side_effect=sqlite3.OperationalError("locked")):
            self.assertIsNone(missing._find_session())

        flags = self.make(
            OpenCodeAdapter,
            command=["opencode", "--session", "already", "-s", "also"],
            resume=True,
            cli_session="new",
        )
        self.assertEqual(flags.build_command(), ["opencode", "--session", "already", "-s", "also"])

    async def test_run_tails_completed_text_parts_and_skips_invalid_parts(self):
        created = int(time.time() * 1000)
        db = self.make_store(created=created)
        db.executemany(
            "INSERT INTO message VALUES(?,?)",
            [
                ("m1", json.dumps({"role": "assistant", "time": {"completed": 1}})),
                ("m2", json.dumps({"role": "assistant", "time": {"completed": 1}})),
                ("m3", json.dumps({"role": "user", "time": {"completed": 1}})),
            ],
        )
        db.executemany(
            "INSERT INTO part VALUES(?,?,?,?,?)",
            [
                ("p1", "m1", "session-1", created, json.dumps({"type": "text", "text": "hello"})),
                ("p2", "m2", "session-1", created + 1, json.dumps({"type": "text", "text": 123})),
                ("p3", "m3", "session-1", created + 2, json.dumps({"type": "text", "text": "user"})),
            ],
        )
        db.commit()
        db.close()
        adapter = self.make(OpenCodeAdapter)
        adapter.spawned_at = created / 1000
        adapter.proc = Process()
        sent = []
        adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))
        adapter.on_cli_session = lambda session: sent.append(("session", session))

        async def post(sender, sender_type, body):
            self.messages.append((sender, sender_type, body))
            adapter.proc.stop()

        adapter.post = post
        with patch("partyline.adapters.bundled.opencode.adapter.asyncio.sleep", new=AsyncMock()):
            await adapter._run()
        self.assertEqual(self.messages, [("agent", "agent", "hello")])
        self.assertEqual(sent[0], adapter.briefing())
        self.assertEqual(sent[1], ("session", "session-1"))

    async def test_run_resume_and_no_session_paths(self):
        adapter = self.make(OpenCodeAdapter, resume=True, cli_session="resume-s")
        adapter.proc = Process()
        adapter.send_keys = AsyncMock()
        adapter._find_session = lambda: "resume-s"
        adapter._connect = lambda: RowsConnection([])
        adapter.on_cli_session = None
        resume_sleeps = 0

        async def stop_after_poll(_seconds):
            nonlocal resume_sleeps
            resume_sleeps += 1
            if resume_sleeps > 1:
                adapter.proc.stop()

        with patch("partyline.adapters.bundled.opencode.adapter.asyncio.sleep", new=stop_after_poll):
            await adapter._run()
        adapter.send_keys.assert_not_awaited()

        dead = self.make(OpenCodeAdapter)
        dead.proc = Process()
        dead.proc.stop()
        with patch("partyline.adapters.bundled.opencode.adapter.asyncio.sleep", new=AsyncMock()):
            await dead._run()

        no_session = self.make(OpenCodeAdapter)
        no_session.proc = Process()
        no_session.send_keys = AsyncMock()
        no_session._find_session = lambda: None
        no_session_sleeps = 0

        async def stop_after_wait(_seconds):
            nonlocal no_session_sleeps
            no_session_sleeps += 1
            if no_session_sleeps > 1:
                no_session.proc.stop()

        with patch("partyline.adapters.bundled.opencode.adapter.asyncio.sleep", new=stop_after_wait):
            await no_session._run()
        self.assertEqual(self.messages, [])

    async def test_run_skips_bad_poll_and_bad_json_rows(self):
        adapter = self.make(OpenCodeAdapter)
        adapter.proc = Process()
        adapter._find_session = lambda: "s"
        adapter._connect = lambda: RowsConnection(
            [("bad", "not json"), ("number", json.dumps({"text": 9})), ("number", json.dumps({"text": 9}))]
        )
        adapter.send_keys = AsyncMock()
        poll_sleeps = 0

        async def stop_after_rows(_seconds):
            nonlocal poll_sleeps
            poll_sleeps += 1
            if poll_sleeps > 1:
                adapter.proc.stop()

        with patch("partyline.adapters.bundled.opencode.adapter.asyncio.sleep", new=stop_after_rows):
            await adapter._run()
        self.assertEqual(self.messages, [])

        error_adapter = self.make(OpenCodeAdapter)
        error_adapter.proc = Process()
        error_adapter._find_session = lambda: "s"
        error_adapter._connect = lambda: (_ for _ in ()).throw(sqlite3.OperationalError("busy"))
        error_adapter.send_keys = AsyncMock()
        error_sleeps = 0

        async def stop_error(_seconds):
            nonlocal error_sleeps
            error_sleeps += 1
            if error_sleeps > 1:
                error_adapter.proc.stop()

        with patch("partyline.adapters.bundled.opencode.adapter.asyncio.sleep", new=stop_error):
            await error_adapter._run()

        timeout_adapter = self.make(OpenCodeAdapter)
        timeout_adapter.proc = Process()
        timeout_adapter.send_keys = AsyncMock()
        timeout_adapter._find_session = lambda: None
        with patch("partyline.adapters.bundled.opencode.adapter.asyncio.sleep", new=AsyncMock()):
            await timeout_adapter._run()
        self.assertIn("no session appeared after 45s", self.messages[-1][2])

    async def test_stop_releases_claimed_session(self):
        adapter = self.make(OpenCodeAdapter)
        adapter._session_id = "claimed"
        OpenCodeAdapter._CLAIMED.add("claimed")
        await adapter.stop()
        self.assertNotIn("claimed", OpenCodeAdapter._CLAIMED)


class PiAdapterTest(RecordingAdapterTest):
    async def test_build_command_uses_private_session_directory(self):
        with tempfile.TemporaryDirectory() as root:
            old_root = pi_module.SESSION_ROOT
            pi_module.SESSION_ROOT = root
            self.addCleanup(setattr, pi_module, "SESSION_ROOT", old_root)
            adapter = self.make(PiAdapter)
            self.assertEqual(adapter.session_dir(), os.path.join(root, "agent-id"))
            self.assertEqual(
                adapter.build_command(),
                ["fake-cli", "--session-dir", os.path.join(root, "agent-id"), "--session-id", "agent-id"],
            )
            explicit = self.make(
                PiAdapter, command=["pi", "--session-dir", "custom", "--session-id", "custom-id"]
            )
            self.assertEqual(
                explicit.build_command(), ["pi", "--session-dir", "custom", "--session-id", "custom-id"]
            )
            resumed = self.make(PiAdapter, resume=True)
            self.assertEqual(resumed.build_command(), adapter.build_command())

    async def test_run_tails_only_spoken_assistant_text_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as root:
            old_root = pi_module.SESSION_ROOT
            pi_module.SESSION_ROOT = root
            self.addCleanup(setattr, pi_module, "SESSION_ROOT", old_root)
            adapter = self.make(PiAdapter)
            adapter.proc = Process()
            path = Path(adapter.session_dir()) / "session.jsonl"
            path.parent.mkdir(parents=True)
            records = [
                "not json\n",
                json.dumps({"type": "other"}) + "\n",
                json.dumps({"type": "message", "id": "u", "message": {"role": "user"}}) + "\n",
                json.dumps(
                    {
                        "type": "message",
                        "id": "r1",
                        "timestamp": "not needed",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "thinking", "text": "secret reasoning"},
                                {"type": "text", "text": "first"},
                                {"type": "text", "text": "second"},
                            ],
                        },
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "thinking", "text": "only thinking"}],
                        },
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "type": "message",
                        "id": "r1",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "duplicate"}]},
                    }
                )
                + "\n",
            ]
            path.write_text("".join(records), encoding="utf-8")
            sent = []
            adapter.send_keys = AsyncMock(side_effect=lambda text: sent.append(text))

            async def post(sender, sender_type, body):
                self.messages.append((sender, sender_type, body))
                adapter.proc.stop()

            adapter.post = post
            with patch("partyline.adapters.bundled.pi.adapter.asyncio.sleep", new=AsyncMock()):
                await adapter._run()
            self.assertEqual(self.messages, [("agent", "agent", "first\n\nsecond")])
            self.assertEqual(sent, [adapter.briefing()])

    async def test_run_resume_ignores_stale_transcript_records(self):
        with tempfile.TemporaryDirectory() as root:
            old_root = pi_module.SESSION_ROOT
            pi_module.SESSION_ROOT = root
            self.addCleanup(setattr, pi_module, "SESSION_ROOT", old_root)
            adapter = self.make(PiAdapter, resume=True)
            adapter.proc = Process()
            path = Path(adapter.session_dir()) / "resume.jsonl"
            path.parent.mkdir(parents=True)
            now = time.time()
            path.write_text(
                json.dumps(
                    {
                        "type": "message",
                        "id": "old",
                        "timestamp": "2000-01-01T00:00:00Z",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "old"}]},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "message",
                        "id": "new",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "new"}]},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            adapter.spawned_at = now

            async def post(sender, sender_type, body):
                self.messages.append((sender, sender_type, body))
                adapter.proc.stop()

            adapter.post = post
            adapter.send_keys = AsyncMock()
            with patch("partyline.adapters.bundled.pi.adapter.asyncio.sleep", new=AsyncMock()):
                await adapter._run()
            self.assertEqual(self.messages, [("agent", "agent", "new")])
            adapter.send_keys.assert_not_awaited()

    async def test_run_exits_when_process_dies_before_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            old_root = pi_module.SESSION_ROOT
            pi_module.SESSION_ROOT = root
            self.addCleanup(setattr, pi_module, "SESSION_ROOT", old_root)
            adapter = self.make(PiAdapter)
            adapter.proc = Process()
            adapter.proc.stop()
            await adapter._run()

            waiting = self.make(PiAdapter)
            waiting.proc = Process()
            waiting.send_keys = AsyncMock()
            wait_calls = 0

            async def stop_wait(_seconds):
                nonlocal wait_calls
                wait_calls += 1
                if wait_calls > 1:
                    waiting.proc.stop()

            with (
                patch("partyline.adapters.bundled.pi.adapter.glob.glob", return_value=[]),
                patch("partyline.adapters.bundled.pi.adapter.asyncio.sleep", new=stop_wait),
            ):
                await waiting._run()

    async def test_run_retries_trust_prompt_and_finds_latest_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            old_root = pi_module.SESSION_ROOT
            pi_module.SESSION_ROOT = root
            self.addCleanup(setattr, pi_module, "SESSION_ROOT", old_root)
            adapter = self.make(PiAdapter)
            adapter.proc = Process()
            adapter.master = 7
            path = Path(adapter.session_dir()) / "latest.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "type": "message",
                        "id": "ok",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "ready"}]},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            adapter.send_keys = AsyncMock()
            calls = 0

            def glob_hits(*_args):
                nonlocal calls
                calls += 1
                return [] if calls <= 12 else [str(path)]

            async def no_wait(_seconds):
                pass

            async def post(sender, sender_type, body):
                self.messages.append((sender, sender_type, body))
                adapter.proc.stop()

            adapter.post = post
            with (
                patch("partyline.adapters.bundled.pi.adapter.glob.glob", side_effect=glob_hits),
                patch("partyline.adapters.bundled.pi.adapter.os.write") as write,
                patch("partyline.adapters.bundled.pi.adapter.asyncio.sleep", new=no_wait),
            ):
                await adapter._run()
            self.assertEqual(self.messages, [("agent", "agent", "ready")])
            write.assert_called_once_with(7, b"\r")
            self.assertGreaterEqual(adapter.send_keys.await_count, 2)

    async def test_run_reports_missing_transcript_after_timeout(self):
        with tempfile.TemporaryDirectory() as root:
            old_root = pi_module.SESSION_ROOT
            pi_module.SESSION_ROOT = root
            self.addCleanup(setattr, pi_module, "SESSION_ROOT", old_root)
            adapter = self.make(PiAdapter)
            adapter.proc = Process()
            adapter.master = 7
            adapter.send_keys = AsyncMock()

            async def no_wait(_seconds):
                pass

            with (
                patch("partyline.adapters.bundled.pi.adapter.glob.glob", return_value=[]),
                patch("partyline.adapters.bundled.pi.adapter.os.write"),
                patch("partyline.adapters.bundled.pi.adapter.asyncio.sleep", new=no_wait),
            ):
                await adapter._run()
            self.assertIn("no transcript after 45s", self.messages[-1][2])

    async def test_fresh_timestamp_and_transcript_alias(self):
        adapter = self.make(PiAdapter, resume=True)
        adapter.spawned_at = time.time()
        self.assertFalse(adapter._fresh(None))
        self.assertFalse(adapter._fresh("not-a-timestamp"))
        self.assertTrue(adapter._fresh(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))


class RawAdapterTest(RecordingAdapterTest):
    async def test_strips_terminal_control_sequences_and_flushes_quiet_output(self):
        adapter = self.make(RawAdapter)
        adapter.proc = Process()
        await adapter.on_output(b"\x1b[31mhello\x1b[0m\r\nworld\r\xff")
        self.assertEqual(adapter._buffer, ["hello\nworld\n\ufffd"])
        adapter.QUIET_SECONDS = 0

        async def post(sender, sender_type, body):
            self.messages.append((sender, sender_type, body))
            adapter.proc.stop()

        adapter.post = post
        with patch("partyline.adapters.bundled.raw.adapter.asyncio.sleep", new=AsyncMock()):
            await adapter._run()
        self.assertEqual(self.messages, [("agent", "agent", "hello\nworld\n\ufffd")])

    async def test_digest_filters_system_and_own_mention_and_send_keys(self):
        adapter = self.make(RawAdapter, name="Raw-Agent")
        digest = adapter.format_digest(
            [
                {"sender_type": "system", "body": "@Raw-Agent joined"},
                {"sender_type": "human", "body": "@raw-agent: please check this"},
                {"sender_type": "human", "body": "plain follow-up"},
            ]
        )
        self.assertEqual(digest, "please check this\nplain follow-up")
        adapter.master = 7
        with patch("partyline.adapters.bundled.raw.adapter.os.write") as write:
            await adapter.send_keys("hello")
        write.assert_called_once_with(7, b"hello\r")
        self.assertIs(RawAdapter, raw_module.PartylineAdapter)
