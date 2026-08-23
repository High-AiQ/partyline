"""Deterministic coverage for the bundled Muse Code adapter.

Fixtures use Muse's durable log schema; no vendor CLI, network, or real user
session is touched. The shared pty responder has its own real-pty control in
``test_adapter_base``.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from partyline.adapters.bundled.muse.adapter import CURSOR_QUERY, PartylineAdapter

CWD = "/tmp/muse-project"
SESSION_ID = "12345678-1234-4234-8234-123456789abc"


class Process:
    def __init__(self, alive=True):
        self.returncode = None if alive else 0

    def poll(self):
        return self.returncode


def make_adapter(*, command=None, resume=False, session_id=None, cwd=CWD, on_cli_session=None):
    posts = []
    statuses = []

    async def post(sender, sender_type, body):
        posts.append((sender, sender_type, body))

    async def on_status(status):
        statuses.append(status)

    adapter = PartylineAdapter(
        {
            "adapter_metadata": {"env_unset": []},
            "command": list(command if command is not None else ["muse", "--yolo"]),
            "cli_session": session_id,
            "conv_name": "muse tests",
            "cwd": cwd,
            "name": "musey",
            "resume": resume,
        },
        post,
        on_status,
        on_cli_session,
    )
    return adapter, posts, statuses


def record(payload_type, payload):
    return {"schema_version": 1, "payload_type": payload_type, "payload": payload}


def metadata(cwd=CWD):
    return record("runtime.session.metadata", {"kind": "metadata", "record": {
        "workspace_root": cwd,
    }})


def user_prompt(prompt):
    return record("runtime.command_intake.received", {"kind": "command_intake", "record": {
        "command": {"kind": "turn_submit", "prompt": prompt},
    }})


def assistant(message_id, text):
    return record("runtime.session", {
        "kind": "run",
        "event": {"kind": "assistant_message_committed", "message_id": message_id, "text": text},
    })


def run_started(prompt):
    """The meta provider's spelling of a submitted prompt: no command_intake
    record is written at all; the prompt rides the run's `started` event."""
    return record("runtime.session", {
        "kind": "run",
        "event": {"kind": "started", "prompt": prompt},
    })


class ManifestTest(unittest.TestCase):
    def test_manifest_enables_real_resume_and_logging(self):
        root = Path(__file__).parents[1] / "partyline" / "adapters" / "bundled" / "muse"
        manifest = (root / "adapter.toml").read_text(encoding="utf-8")

        self.assertIn('version = "1.0.2"', manifest)
        self.assertIn('command = ["muse", "--yolo"]', manifest)
        self.assertIn("resume = true", manifest)


class CommandTest(unittest.TestCase):
    def test_fresh_tui_receives_the_briefing_as_its_initial_prompt(self):
        adapter, _, _ = make_adapter(command=["muse", "--provider", "echo"])

        self.assertEqual(
            adapter.build_command(),
            ["muse", "--provider", "echo", adapter.briefing()],
        )

    def test_resume_uses_the_stored_uuid_and_preserves_flags(self):
        adapter, _, _ = make_adapter(
            command=["muse", "--provider", "echo", "--yolo"],
            resume=True,
            session_id=SESSION_ID,
        )

        self.assertEqual(
            adapter.build_command(),
            ["muse", "resume", SESSION_ID, "--provider", "echo", "--yolo"],
        )

    def test_resume_without_a_stored_uuid_refuses_to_start_fresh(self):
        adapter, _, _ = make_adapter(resume=True)

        with self.assertRaisesRegex(ValueError, "stored session UUID"):
            adapter.build_command()

    def test_disabling_the_structured_output_channel_is_rejected(self):
        adapter, _, _ = make_adapter(command=["muse", "--no-session-log"])

        with self.assertRaisesRegex(ValueError, "incompatible"):
            adapter.build_command()

    def test_empty_command_uses_the_unattended_default_without_mutating_it(self):
        adapter, _, _ = make_adapter(command=[])
        stored = adapter.att["command"]

        self.assertEqual(adapter.build_command(), ["muse", "--yolo", adapter.briefing()])
        self.assertEqual(stored, [])


class TerminalProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_bundled_adapter_opts_into_the_core_responder(self):
        adapter, _, _ = make_adapter()

        self.assertTrue(adapter.answers_terminal_queries)

    async def test_split_cursor_query_then_render_marks_input_ready(self):
        adapter, _, _ = make_adapter()

        await adapter.on_output(CURSOR_QUERY[:2])
        await adapter.on_output(CURSOR_QUERY[2:])
        self.assertFalse(adapter._tui_rendered.is_set())
        await adapter.on_output(b"first rendered terminal frame")

        self.assertTrue(adapter._tui_rendered.is_set())

    async def test_missing_cursor_query_degrades_to_assumed_readiness(self):
        adapter, _, _ = make_adapter()
        adapter.TUI_READY_TIMEOUT = 0

        await adapter._wait_until_tui_rendered()

        self.assertFalse(adapter._tui_rendered.is_set())


class StoreFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_home = Path(self.temp.name)
        patcher = patch.dict(os.environ, {"XDG_DATA_HOME": str(self.data_home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        PartylineAdapter._claimed_sessions.clear()
        self.addCleanup(PartylineAdapter._claimed_sessions.clear)

    def write_session(self, session_id, records, *, subagent=False):
        root = self.data_home / "muse" / "sessions" / "2026" / "08" / "09" / session_id
        if subagent:
            root = root / "subagent" / "child"
        root.mkdir(parents=True, exist_ok=True)
        path = root / "session.jsonl"
        path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        return path


class LifecycleTest(StoreFixture, unittest.IsolatedAsyncioTestCase):
    async def test_fresh_start_snapshots_existing_logs_before_spawning(self):
        adapter, _, _ = make_adapter()
        existing = self.write_session(SESSION_ID, [metadata()])

        with patch("partyline.adapters.base.Adapter.start", new_callable=AsyncMock) as parent:
            await adapter.start()

        self.assertEqual(adapter._known_logs, {existing})
        parent.assert_awaited_once_with()

    async def test_resume_start_snapshots_the_existing_log_byte_offset(self):
        adapter, _, _ = make_adapter(resume=True, session_id=SESSION_ID)
        existing = self.write_session(SESSION_ID, [assistant("old", "old reply")])

        with patch("partyline.adapters.base.Adapter.start", new_callable=AsyncMock):
            await adapter.start()

        self.assertEqual(adapter._resume_offset, existing.stat().st_size)

    async def test_resume_start_stat_failure_preserves_safe_eof_fallback(self):
        adapter, _, _ = make_adapter(resume=True, session_id=SESSION_ID)
        broken = MagicMock()
        broken.stat.side_effect = OSError

        with (
            patch.object(adapter, "_log_for_session", return_value=broken),
            patch("partyline.adapters.base.Adapter.start", new_callable=AsyncMock),
        ):
            await adapter.start()

        self.assertIsNone(adapter._resume_offset)

    async def test_stop_releases_the_session_claim_before_parent_cleanup(self):
        adapter, _, _ = make_adapter(resume=True, session_id=SESSION_ID)
        self.write_session(SESSION_ID, [metadata()])
        self.assertIsNotNone(adapter._find_and_claim())

        with patch("partyline.adapters.base.Adapter.stop", new_callable=AsyncMock) as parent:
            await adapter.stop()

        self.assertNotIn(SESSION_ID, PartylineAdapter._claimed_sessions)
        parent.assert_awaited_once_with()


class DiscoveryTest(StoreFixture):
    def test_fresh_session_is_matched_by_workspace_and_exact_initial_prompt(self):
        adapter, _, _ = make_adapter()
        path = self.write_session(SESSION_ID, [metadata(), user_prompt(adapter.briefing())])

        self.assertEqual(adapter._find_and_claim(), path)
        self.assertEqual(adapter._session_id, SESSION_ID)

    def test_fresh_meta_session_is_matched_by_its_run_started_prompt(self):
        adapter, _, _ = make_adapter()
        path = self.write_session(SESSION_ID, [metadata(), run_started(adapter.briefing())])

        self.assertEqual(adapter._find_and_claim(), path)
        self.assertEqual(adapter._session_id, SESSION_ID)

    def test_another_run_started_prompt_is_ignored(self):
        adapter, _, _ = make_adapter()
        self.write_session(SESSION_ID, [metadata(), run_started("someone else's briefing")])

        self.assertIsNone(adapter._find_and_claim())

    def test_wrong_workspace_prompt_and_preexisting_log_are_ignored(self):
        wrong_cwd, _, _ = make_adapter()
        self.write_session(SESSION_ID, [
            metadata("/tmp/elsewhere"), user_prompt(wrong_cwd.briefing()),
        ])
        self.assertIsNone(wrong_cwd._find_and_claim())

        wrong_prompt, _, _ = make_adapter()
        path = self.write_session(SESSION_ID, [metadata(), user_prompt("someone else's briefing")])
        self.assertIsNone(wrong_prompt._find_and_claim())

        old, _, _ = make_adapter()
        old._known_logs.add(path)
        self.assertIsNone(old._find_and_claim())

    def test_claimed_and_subagent_sessions_are_skipped(self):
        adapter, _, _ = make_adapter()
        self.write_session(SESSION_ID, [metadata(), user_prompt(adapter.briefing())])
        PartylineAdapter._claimed_sessions.add(SESSION_ID)
        self.assertIsNone(adapter._find_and_claim())

        subagent, _, _ = make_adapter()
        self.write_session(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            [metadata(), user_prompt(subagent.briefing())],
            subagent=True,
        )
        self.assertIsNone(subagent._find_and_claim())

    def test_resume_finds_only_the_stored_uuid_and_release_makes_it_available(self):
        adapter, _, _ = make_adapter(resume=True, session_id=SESSION_ID)
        expected = self.write_session(SESSION_ID, [metadata(), user_prompt("old")])
        self.write_session("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", [metadata()])

        self.assertEqual(adapter._find_and_claim(), expected)
        second, _, _ = make_adapter(resume=True, session_id=SESSION_ID)
        self.assertIsNone(second._find_and_claim())
        PartylineAdapter._release(SESSION_ID)
        self.assertEqual(second._find_and_claim(), expected)
        PartylineAdapter._release(None)

    def test_missing_store_has_no_candidates(self):
        adapter, _, _ = make_adapter()

        self.assertEqual(adapter._session_logs(), [])
        self.assertIsNone(adapter._log_for_session(SESSION_ID))

    def test_unreadable_or_nonmatching_log_is_ignored(self):
        adapter, _, _ = make_adapter()
        path = self.write_session(SESSION_ID, [])
        with patch.object(Path, "open", side_effect=OSError):
            self.assertFalse(adapter._matches_fresh_session(path))
        self.assertFalse(adapter._matches_fresh_session(path))

    def test_realpath_type_failure_falls_back_to_string_comparison(self):
        adapter, _, _ = make_adapter(cwd=CWD)
        path = self.write_session(SESSION_ID, [metadata(), user_prompt(adapter.briefing())])
        with patch("partyline.adapters.bundled.muse.adapter.os.path.realpath", side_effect=TypeError):
            self.assertTrue(adapter._matches_fresh_session(path))


class TranscriptTest(StoreFixture, unittest.IsolatedAsyncioTestCase):
    async def test_only_committed_assistant_text_is_posted(self):
        adapter, posts, _ = make_adapter()
        path = self.write_session(SESSION_ID, [
            user_prompt("hello"),
            # stdout's streaming vocabulary is not the durable-log contract.
            record("run.output.delta", {"text": "stdout partial"}),
            record("run.terminal.completed", {"text": "stdout final"}),
            record("runtime.session", {"kind": "run", "event": {
                "kind": "assistant_message_delta", "text": "partial",
            }}),
            assistant("message-1", "finished reply"),
        ])
        adapter.alive = lambda: False

        await adapter._tail(path, 0)

        self.assertEqual(posts, [("musey", "agent", "finished reply")])

    async def test_resume_offsets_prevent_old_messages_from_replaying(self):
        adapter, posts, _ = make_adapter(resume=True, session_id=SESSION_ID)
        path = self.write_session(SESSION_ID, [assistant("old", "old reply")])
        offset = path.stat().st_size
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(assistant("new", "new reply")) + "\n")
        adapter.alive = lambda: False
        adapter._silent_until_wake = False

        await adapter._tail(path, offset)
        self.assertEqual(posts, [("musey", "agent", "new reply")])

        unknown, unknown_posts, _ = make_adapter(resume=True, session_id=SESSION_ID)
        unknown.alive = lambda: False
        unknown._silent_until_wake = False
        await unknown._tail(path, None)
        self.assertEqual(unknown_posts, [])

    async def test_duplicate_ids_malformed_lines_and_partial_tail_are_safe(self):
        adapter, posts, _ = make_adapter()
        path = self.write_session(SESSION_ID, [assistant("same", "once")])
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(assistant("same", "twice")) + "\n")
            file.write("not json\n")
            file.write('{"payload_type":"runtime.session"')
        adapter.alive = lambda: False

        await adapter._tail(path, 0)

        self.assertEqual(posts, [("musey", "agent", "once")])


class RunTest(StoreFixture, unittest.IsolatedAsyncioTestCase):
    async def test_run_reports_timeout_when_no_session_appears(self):
        adapter, posts, _ = make_adapter()
        adapter.proc = Process()
        adapter.DISCOVERY_TIMEOUT = 0

        await adapter._run()

        self.assertIn("no Muse session log appeared", posts[0][2])
        self.assertTrue(posts[0][2].startswith("musey: no Muse session log"))

    async def test_run_claims_reports_and_tails_the_session(self):
        sessions = []
        adapter, _, _ = make_adapter(on_cli_session=sessions.append)
        path = self.write_session(SESSION_ID, [metadata(), user_prompt(adapter.briefing())])
        adapter._tui_rendered.set()
        adapter._tail = AsyncMock()

        await adapter._run()

        self.assertEqual(sessions, [SESSION_ID])
        adapter._tail.assert_awaited_once_with(path, 0)
        self.assertNotIn(SESSION_ID, PartylineAdapter._claimed_sessions)

    async def test_run_without_callback_or_live_process_exits_quietly(self):
        adapter, posts, _ = make_adapter()
        adapter.proc = Process(alive=False)

        await adapter._run()

        self.assertEqual(posts, [])


if __name__ == "__main__":
    unittest.main()
