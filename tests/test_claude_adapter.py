"""Vendor-free contract tests for the Claude Code adapter."""

import contextlib
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.adapters.bundled.claude.adapter import PartylineAdapter


class ClaudeManifestTest(unittest.TestCase):
    def test_manifest_declares_receipt_turn_end(self):
        root = Path(__file__).parents[1] / "partyline" / "adapters" / "bundled" / "claude"
        manifest = (root / "adapter.toml").read_text(encoding="utf-8")
        self.assertIn("resume = true", manifest)
        self.assertIn('turn_end = "receipt"', manifest)
        self.assertIn('update_command = ["claude", "update"]', manifest)


class ClaudeCommandTest(unittest.TestCase):
    def make_adapter(self, *, command: list[str], resume: bool, hook_url: str | None = None):
        """Build only the pure argv seam; no pty or Claude CLI is involved."""
        adapter = PartylineAdapter.__new__(PartylineAdapter)
        adapter.att = {"command": command, "id": "attachment-1"}
        if hook_url is not None:
            adapter.att["hook_url"] = hook_url
        adapter.resume = resume
        return adapter

    def test_fresh_command_gets_one_session_id(self):
        adapter = self.make_adapter(command=["claude", "--model", "opus"], resume=False)

        self.assertEqual(
            adapter.build_command(),
            ["claude", "--model", "opus", "--session-id", "attachment-1"],
        )

    def test_existing_session_id_is_not_duplicated(self):
        adapter = self.make_adapter(
            command=["claude", "--session-id", "chosen-by-user"], resume=False,
        )

        self.assertEqual(adapter.build_command(), ["claude", "--session-id", "chosen-by-user"])

    def test_resume_command_uses_the_attachment_id(self):
        adapter = self.make_adapter(command=["claude", "--model", "opus"], resume=True)

        self.assertEqual(
            adapter.build_command(),
            ["claude", "--model", "opus", "--resume", "attachment-1"],
        )

    def test_notification_hook_is_structured_settings_not_a_vendor_invocation(self):
        adapter = self.make_adapter(
            command=["claude"], resume=False,
            hook_url="https://hooks.example.test/notify?line=partyline&kind=agent",
        )

        command = adapter.build_command()
        settings = json.loads(command[command.index("--settings") + 1])
        hook = settings["hooks"]["Notification"][0]["hooks"][0]

        self.assertEqual(hook["type"], "command")
        self.assertIn("curl -s -m 5 -X POST", hook["command"])
        self.assertIn("hooks.example.test", hook["command"])
        self.assertIn("--data-binary @-", hook["command"])
        self.assertEqual(
            settings["hooks"]["Stop"][0]["hooks"][0]["command"], hook["command"],
        )
        self.assertEqual(
            settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
            hook["command"],
        )
        self.assertNotIn("SubagentStop", settings["hooks"])

    def test_existing_settings_are_not_replaced(self):
        adapter = self.make_adapter(
            command=["claude", "--settings", "existing.json"],
            resume=False,
            hook_url="https://hooks.example.test/notify",
        )

        self.assertEqual(
            adapter.build_command(),
            ["claude", "--settings", "existing.json", "--session-id", "attachment-1"],
        )


class ClaudeTranscriptTest(unittest.IsolatedAsyncioTestCase):
    # Test fixtures live beside the tests, not inside the adapter package.
    # Anything under partyline/ ships in the wheel, so a fixture placed there
    # is shipped to every user to support a test they will never run.
    fixture = Path(__file__).parent / "fixtures" / "claude_transcript.jsonl"

    def make_adapter(self, posts: list[tuple[str, str, str]]) -> PartylineAdapter:
        async def post(sender: str, sender_type: str, body: str) -> None:
            posts.append((sender, sender_type, body))

        async def on_status(status: str) -> None:
            return None

        adapter = PartylineAdapter(
            {
                "command": ["claude"],
                "id": "attachment-1",
                "name": "claude",
                "cwd": "/work",
                "resume": True,
            },
            post,
            on_status,
        )
        # This test isolates transcript parsing. The process has already received a real wake.
        adapter._silent_until_wake = False
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: timestamp == "fresh"
        # These tests isolate the poll and the tail, not transcript identity:
        # their paths are names, not files on disk.
        adapter._pinned_is_ours = lambda path: True
        return adapter

    async def test_transcript_posts_only_fresh_unique_assistant_text(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)

        async def tail(path: str, handle) -> None:
            self.assertEqual(path, "fixture.jsonl")
            for line in self.fixture.read_text(encoding="utf-8").splitlines():
                await handle(json.loads(line))

        adapter._tail_jsonl = tail
        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", return_value=["fixture.jsonl"]),
        ):
            await adapter._run()

        self.assertEqual(posts, [("claude", "agent", "first answer\n\nsecond paragraph")])

    async def test_run_waits_for_transcript_and_retries_briefing(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.resume = False
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: True

        # Simulate transcript appearing after two empty globs, then found
        globs = [[], [], ["found.jsonl"]]

        async def fake_tail(path, handle):
            await handle(
                {
                    "type": "assistant",
                    "timestamp": "fresh",
                    "uuid": "u1",
                    "message": {"content": [{"type": "text", "text": "hi"}]},
                }
            )

        adapter._tail_jsonl = fake_tail
        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", side_effect=globs),
            patch.object(adapter, "send_keys", AsyncMock()) as mock_keys,
        ):
            await adapter._run()
        # briefing sent once at start, and transcript found
        self.assertTrue(mock_keys.called)
        self.assertEqual(posts, [("claude", "agent", "hi")])

    async def test_run_exits_when_process_dies_before_transcript(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.alive = lambda: False
        adapter._fresh = lambda timestamp: True

        async def fake_tail(path, handle):
            self.fail("should not tail without transcript")

        adapter._tail_jsonl = fake_tail
        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", return_value=[]),
        ):
            await adapter._run()
        self.assertEqual(posts, [])

    async def test_timeout_notice_names_claude_without_addressing_it(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.resume = False
        adapter.master = 1
        # The CLI outlives the 45s mark by a long way, then exits. Without a
        # bound the search would now run for as long as it is alive.
        polls = iter(range(200))
        adapter.alive = lambda: next(polls, None) is not None

        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", return_value=[]),
            patch("partyline.adapters.bundled.claude.adapter.os.write"),
            patch.object(adapter, "send_keys", AsyncMock()),
        ):
            await adapter._run()

        self.assertTrue(posts[0][2].startswith("claude: no transcript after 45s"))

    async def test_timeout_warns_once_and_keeps_watching(self):
        """The 45s mark is a warning, not a verdict.

        Returning here left the attachment live, mentionable, and mute: its
        cursor still advanced while nothing it said could reach the line.
        """
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.resume = False
        adapter.master = 1
        adapter._fresh = lambda timestamp: True
        polls = iter(range(300))
        adapter.alive = lambda: next(polls, None) is not None

        # Empty until well past the old give-up point, then the CLI finally
        # writes the transcript under the pinned name.
        pinned_polls = 0

        def fake_glob(pattern):
            nonlocal pinned_polls
            if "attachment-1" not in pattern:
                return []
            pinned_polls += 1
            return ["late.jsonl"] if pinned_polls > 60 else []

        async def fake_tail(path, handle):
            self.assertEqual(path, "late.jsonl")

        adapter._tail_jsonl = fake_tail
        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", side_effect=fake_glob),
            patch("partyline.adapters.bundled.claude.adapter.os.write"),
            patch.object(adapter, "send_keys", AsyncMock()),
        ):
            await adapter._run()

        notices = [body for _, _, body in posts]
        self.assertEqual(
            sum(1 for body in notices if "no transcript after 45s" in body), 1,
            "the warning must not repeat every second",
        )
        self.assertTrue(
            any("the line is reachable again" in body for body in notices),
            "recovery after a warned wait must be announced",
        )

    async def test_run_retries_briefing_at_12_and_24_seconds(self):
        posts: list[tuple[str, str, str]] = []
        adapter = self.make_adapter(posts)
        adapter.resume = False
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: True
        adapter.master = 1

        # Simulate waited hitting 12 before the transcript appears. Only the
        # pinned pattern counts as a poll: an empty search also sweeps the
        # unpinned sessions, and counting both would misplace the retry.
        polls = 0

        def fake_glob(pattern):
            nonlocal polls
            if "attachment-1" not in pattern:
                return []
            polls += 1
            return [] if polls < 13 else ["found.jsonl"]

        async def fake_tail(path, handle):
            await handle(
                {
                    "type": "assistant",
                    "timestamp": "fresh",
                    "uuid": "u2",
                    "message": {"content": [{"type": "text", "text": "after retry"}]},
                }
            )

        adapter._tail_jsonl = fake_tail
        import asyncio as _asyncio2

        orig_sleep2 = _asyncio2.sleep

        async def _fast_sleep2(*args, **kwargs):
            await orig_sleep2(0)

        with (
            patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", _fast_sleep2),
            patch("partyline.adapters.bundled.claude.adapter.glob.glob", side_effect=fake_glob),
            patch("partyline.adapters.bundled.claude.adapter.os.write") as mock_write,
            patch.object(adapter, "send_keys", AsyncMock()) as mock_keys,
        ):
            await adapter._run()
        # Should have retried at 12
        self.assertEqual(mock_write.call_count, 1)
        self.assertGreaterEqual(mock_keys.call_count, 2)  # initial + 1 retry
        self.assertEqual(posts, [("claude", "agent", "after retry")])


class ClaudeLostPinTest(unittest.IsolatedAsyncioTestCase):
    """A CLI that self-updates at attach re-execs without the session pin.

    The pinned transcript name then never appears, and before adoption the
    adapter went mute while the attachment stayed live and mentionable.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        PartylineAdapter._LIVE.clear()
        PartylineAdapter._CLAIMED.clear()
        self.addCleanup(PartylineAdapter._LIVE.clear)
        self.addCleanup(PartylineAdapter._CLAIMED.clear)

    @contextlib.contextmanager
    def searching(self, pinned: str = "attachment-1.jsonl"):
        """Point the pinned lookup and the unpinned sweep at the sandbox."""
        with (
            patch.object(PartylineAdapter, "transcript_glob",
                         return_value=str(self.root / pinned)),
            patch("partyline.adapters.bundled.claude.adapter.os.path.expanduser",
                  return_value=str(self.root / "*.jsonl")),
        ):
            yield

    def write_session(self, name: str, *, cwd: str, stamp: float) -> str:
        path = self.root / f"{name}.jsonl"
        records = [
            {"type": "mode", "mode": "normal", "sessionId": name},
            {"type": "user", "cwd": cwd, "sessionId": name,
             "timestamp": datetime.fromtimestamp(stamp, UTC).isoformat().replace("+00:00", "Z")},
        ]
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        return str(path)

    def make_adapter(self, posts: list[tuple[str, str, str]]) -> PartylineAdapter:
        async def post(sender: str, sender_type: str, body: str) -> None:
            posts.append((sender, sender_type, body))

        async def on_status(status: str) -> None:
            return None

        adapter = PartylineAdapter(
            {"command": ["claude"], "id": "attachment-1", "name": "claude",
             "cwd": "/work", "resume": False},
            post, on_status,
        )
        adapter.spawned_at = 1_000.0
        adapter.resume = False
        adapter._silent_until_wake = False
        return adapter

    def test_session_opened_after_spawn_in_our_cwd_is_adopted(self):
        adapter = self.make_adapter([])
        path = self.write_session("random-id", cwd="/work", stamp=1_002.0)

        with self.searching():
            self.assertEqual(adapter._find_transcript(), path)

    def test_a_users_own_older_session_is_not_adopted(self):
        """Greg running the CLI by hand in the same directory is not us."""
        adapter = self.make_adapter([])
        self.write_session("hand-run", cwd="/work", stamp=900.0)

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    def test_a_session_in_another_directory_is_not_adopted(self):
        adapter = self.make_adapter([])
        self.write_session("elsewhere", cwd="/other", stamp=1_002.0)

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    def test_another_attachments_pinned_session_is_never_adopted(self):
        """Two attachments starting together must not swap transcripts."""
        adapter = self.make_adapter([])
        PartylineAdapter._LIVE["attachment-2"] = 1_000.0
        self.write_session("attachment-2", cwd="/work", stamp=1_002.0)

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    def test_an_adopted_transcript_is_claimed_against_a_second_adapter(self):
        first, second = self.make_adapter([]), self.make_adapter([])
        second.att = dict(second.att, id="attachment-2")
        path = self.write_session("random-id", cwd="/work", stamp=1_002.0)

        with self.searching("missing.jsonl"):
            self.assertEqual(first._find_transcript(), path)
            self.assertIsNone(second._find_transcript())

    def test_the_pinned_transcript_still_wins_when_it_exists(self):
        adapter = self.make_adapter([])
        pinned = self.write_session("attachment-1", cwd="/work", stamp=1_002.0)
        self.write_session("random-id", cwd="/work", stamp=1_003.0)

        with self.searching():
            self.assertEqual(adapter._find_transcript(), pinned)

    def test_a_transcript_that_never_names_a_directory_is_not_adopted(self):
        """Garbage and truncation judge nothing: unreadable is not ours."""
        adapter = self.make_adapter([])
        path = self.root / "half-written.jsonl"
        path.write_text('not json\n{"type": "mode"}\n', encoding="utf-8")

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    def test_an_unreadable_transcript_is_not_adopted(self):
        adapter = self.make_adapter([])
        self.write_session("locked", cwd="/work", stamp=1_002.0)

        with self.searching(), patch("builtins.open", side_effect=OSError):
            self.assertIsNone(adapter._find_transcript())

    async def test_stop_releases_the_pin_and_the_claim(self):
        """A detached attachment must not hold a session another can use."""
        adapter = self.make_adapter([])
        path = self.write_session("random-id", cwd="/work", stamp=1_002.0)
        with self.searching():
            adapter._find_transcript()
        self.assertIn(path, PartylineAdapter._CLAIMED)

        await adapter.stop()

        self.assertNotIn(path, PartylineAdapter._CLAIMED)
        self.assertNotIn("attachment-1", PartylineAdapter._LIVE)

    async def test_start_registers_the_spawn_time_ownership_depends_on(self):
        """Without this registry every window is unbounded and swaps return."""
        adapter = self.make_adapter([])

        async def fake_start(self):
            self.spawned_at = 1_234.0

        with patch("partyline.adapters.base.Adapter.start", fake_start):
            await adapter.start()

        self.assertEqual(PartylineAdapter._LIVE["attachment-1"], 1_234.0)

    def test_a_stale_pinned_transcript_loses_to_a_fresh_adoption(self):
        """A resume whose pin was dropped must not tail its own dead session.

        The pinned file already exists — it is the session being resumed —
        so its presence proves nothing. Untouched since spawn, it is the file
        of a process that is no longer writing it.
        """
        adapter = self.make_adapter([])
        adapter.resume = True
        adapter.att["resume"] = True
        stale = self.write_session("attachment-1", cwd="/work", stamp=100.0)
        os.utime(stale, (200.0, 200.0))
        fresh = self.write_session("random-resume", cwd="/work", stamp=1_002.0)

        with self.searching():
            self.assertEqual(adapter._find_transcript(), fresh)

    def test_a_pinned_transcript_written_since_spawn_still_wins(self):
        """The ordinary resume: the CLI kept the pin and is appending."""
        adapter = self.make_adapter([])
        adapter.resume = True
        pinned = self.write_session("attachment-1", cwd="/work", stamp=100.0)
        os.utime(pinned, (1_002.0, 1_002.0))
        self.write_session("random-other", cwd="/work", stamp=1_003.0)

        with self.searching():
            self.assertEqual(adapter._find_transcript(), pinned)

    def test_two_attachments_do_not_swap_each_others_sessions(self):
        """Spawn order decides ownership, not who searches first.

        Two same-cwd attachments that both lost their pins each see two
        unclaimed random transcripts. Sorting by recency handed the first
        adapter the second process's session and let the second reach back
        through the skew allowance for the first's.
        """
        first, second = self.make_adapter([]), self.make_adapter([])
        second.att = dict(second.att, id="attachment-2")
        second.spawned_at = 1_002.0
        PartylineAdapter._LIVE.update({"attachment-1": 1_000.0, "attachment-2": 1_002.0})
        theirs = self.write_session("random-second", cwd="/work", stamp=1_003.0)
        ours = self.write_session("random-first", cwd="/work", stamp=1_001.0)

        with self.searching("missing.jsonl"):
            # Deliberately the later attachment first: claim order must not
            # decide identity.
            self.assertEqual(second._find_transcript(), theirs)
            self.assertEqual(first._find_transcript(), ours)

    def test_ownership_holds_when_the_earlier_attachment_claims_first(self):
        first, second = self.make_adapter([]), self.make_adapter([])
        second.att = dict(second.att, id="attachment-2")
        second.spawned_at = 1_002.0
        PartylineAdapter._LIVE.update({"attachment-1": 1_000.0, "attachment-2": 1_002.0})
        theirs = self.write_session("random-second", cwd="/work", stamp=1_003.0)
        ours = self.write_session("random-first", cwd="/work", stamp=1_001.0)

        with self.searching("missing.jsonl"):
            self.assertEqual(first._find_transcript(), ours)
            self.assertEqual(second._find_transcript(), theirs)

    def test_a_preamble_only_session_is_dated_by_its_mtime(self):
        """A brand-new session has written no stamped record yet."""
        adapter = self.make_adapter([])
        path = self.root / "just-opened.jsonl"
        path.write_text('{"type": "mode", "cwd": "/work"}\n', encoding="utf-8")
        os.utime(path, (1_001.0, 1_001.0))

        with self.searching():
            self.assertEqual(adapter._find_transcript(), str(path))


if __name__ == "__main__":
    unittest.main()
