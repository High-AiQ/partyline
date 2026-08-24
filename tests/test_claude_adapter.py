"""Vendor-free contract tests for the Claude Code adapter."""

import contextlib
import json
import os
import shutil
import tempfile
import unittest
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
    Sessions are matched by what we typed into the pty, never by timing:
    review of #124 broke a spawn-time scheme twice, because a self-updating
    CLI opens its session late — after a neighbour that started later than
    it — and mtime and ``spawned_at`` share one host clock.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        PartylineAdapter._CLAIMED.clear()
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

    def write_session(self, name: str, *, cwd: str = "/work",
                      pasted: str = "") -> str:
        """A transcript, optionally recording a paste as a user record."""
        path = self.root / f"{name}.jsonl"
        records = [{"type": "mode", "sessionId": name},
                   {"type": "user", "cwd": cwd, "sessionId": name,
                    "message": {"content": pasted or "unrelated chatter"}}]
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        return str(path)

    def make_adapter(self, ident: str = "attachment-1",
                     name: str = "claude") -> PartylineAdapter:
        async def post(sender: str, sender_type: str, body: str) -> None:
            return None

        async def on_status(status: str) -> None:
            return None

        adapter = PartylineAdapter(
            {"command": ["claude"], "id": ident, "name": name,
             "cwd": "/work", "conv_name": "a line", "resume": False},
            post, on_status,
        )
        adapter.spawned_at = 1_000.0
        adapter.resume = False
        adapter._silent_until_wake = False
        adapter.alive = lambda: True
        return adapter

    def test_the_session_that_recorded_our_briefing_is_ours(self):
        adapter = self.make_adapter()
        adapter._note_paste(adapter.briefing())
        mine = self.write_session("random-id", pasted=adapter.briefing())

        with self.searching():
            self.assertEqual(adapter._find_transcript(), mine)

    def test_a_session_that_recorded_nothing_of_ours_is_not_adopted(self):
        """A CLI the user runs by hand in the same directory is not us."""
        adapter = self.make_adapter()
        adapter._note_paste(adapter.briefing())
        self.write_session("hand-run")

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    def test_a_session_in_another_directory_is_not_adopted(self):
        adapter = self.make_adapter()
        adapter._note_paste(adapter.briefing())
        self.write_session("elsewhere", cwd="/other", pasted=adapter.briefing())

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    def test_nothing_is_adopted_before_anything_has_been_pasted(self):
        adapter = self.make_adapter()
        self.write_session("random-id", pasted="some other briefing entirely")

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    def test_concurrent_attachments_claim_their_own_sessions(self):
        """Content pairs them 1:1 however their sessions interleave.

        Spawn-time windows failed here: the first attachment may self-update
        and open its session *after* the second one spawned, which put its
        own transcript permanently outside its window.
        """
        first, second = self.make_adapter(name="alpha"), self.make_adapter(
            ident="attachment-2", name="beta")
        first._note_paste(first.briefing())
        second._note_paste(second.briefing())
        # Deliberately out of order: beta's session opens first.
        theirs = self.write_session("random-beta", pasted=second.briefing())
        mine = self.write_session("random-alpha", pasted=first.briefing())

        with self.searching("missing.jsonl"):
            self.assertEqual(first._find_transcript(), mine)
            self.assertEqual(second._find_transcript(), theirs)

    def test_ownership_is_the_same_whichever_adapter_claims_first(self):
        first, second = self.make_adapter(name="alpha"), self.make_adapter(
            ident="attachment-2", name="beta")
        first._note_paste(first.briefing())
        second._note_paste(second.briefing())
        theirs = self.write_session("random-beta", pasted=second.briefing())
        mine = self.write_session("random-alpha", pasted=first.briefing())

        with self.searching("missing.jsonl"):
            self.assertEqual(second._find_transcript(), theirs)
            self.assertEqual(first._find_transcript(), mine)

    async def test_a_resumed_attachment_claims_its_session_on_the_first_wake(self):
        """A resume gets no briefing, so its first delivery identifies it."""
        adapter = self.make_adapter()
        adapter.resume = True
        adapter.att["resume"] = True
        digest = adapter.format_digest([{"sender": "greg", "body": "x" * 200}])
        with patch.object(PartylineAdapter, "send_keys", AsyncMock()):
            await adapter.deliver([{"sender": "greg", "body": "x" * 200}])
        fresh = self.write_session("random-resume", pasted=digest)

        with self.searching("missing.jsonl"):
            self.assertEqual(adapter._find_transcript(), fresh)

    def test_a_short_wake_is_too_thin_to_name_a_session_by(self):
        adapter = self.make_adapter()
        adapter._note_paste("ok")

        self.assertEqual(adapter._pastes, [])

    def test_a_stale_pinned_transcript_loses_to_a_fresh_adoption(self):
        """A resume whose pin was dropped must not tail its own dead session."""
        adapter = self.make_adapter()
        adapter.resume = True
        adapter._note_paste("d" * 200)
        stale = self.write_session("attachment-1")
        os.utime(stale, (200.0, 200.0))
        fresh = self.write_session("random-resume", pasted="d" * 200)

        with self.searching():
            self.assertEqual(adapter._find_transcript(), fresh)

    def test_a_write_just_before_respawn_is_not_proof_the_pin_survived(self):
        """mtime and spawned_at are one clock, so no allowance is given.

        A five-second grace let the previous process's last write vouch for
        the new one, and the stale session won again.
        """
        adapter = self.make_adapter()
        adapter.resume = True
        adapter._note_paste("d" * 200)
        stale = self.write_session("attachment-1")
        os.utime(stale, (adapter.spawned_at - 1, adapter.spawned_at - 1))
        fresh = self.write_session("random-resume", pasted="d" * 200)

        with self.searching():
            self.assertEqual(adapter._find_transcript(), fresh)

    def test_a_pinned_transcript_written_since_spawn_still_wins(self):
        """The ordinary resume: the CLI kept the pin and is appending."""
        adapter = self.make_adapter()
        adapter.resume = True
        pinned = self.write_session("attachment-1")
        os.utime(pinned, (adapter.spawned_at + 2, adapter.spawned_at + 2))

        with self.searching():
            self.assertEqual(adapter._find_transcript(), pinned)

    def test_a_fresh_attachment_trusts_its_own_pinned_name(self):
        adapter = self.make_adapter()
        pinned = self.write_session("attachment-1")

        with self.searching():
            self.assertEqual(adapter._find_transcript(), pinned)

    def test_an_adopted_transcript_is_claimed_against_a_second_adapter(self):
        first = self.make_adapter()
        second = self.make_adapter(ident="attachment-2")
        first._note_paste(first.briefing())
        second._note_paste(first.briefing())
        mine = self.write_session("random-id", pasted=first.briefing())

        with self.searching("missing.jsonl"):
            self.assertEqual(first._find_transcript(), mine)
            self.assertIsNone(second._find_transcript())

    def test_an_unreadable_transcript_is_not_adopted(self):
        adapter = self.make_adapter()
        adapter._note_paste(adapter.briefing())
        self.write_session("locked", pasted=adapter.briefing())

        with self.searching(), patch("builtins.open", side_effect=OSError):
            self.assertIsNone(adapter._find_transcript())

    def test_a_transcript_of_garbage_is_not_adopted(self):
        adapter = self.make_adapter()
        adapter._note_paste(adapter.briefing())
        (self.root / "half-written.jsonl").write_text("not json\n", encoding="utf-8")

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    def test_a_stranger_transcript_is_not_read_past_the_scan_bound(self):
        adapter = self.make_adapter()
        adapter._note_paste(adapter.briefing())
        path = self.root / "enormous.jsonl"
        filler = json.dumps({"type": "user", "cwd": "/work",
                             "message": {"content": "z" * 4_000}})
        path.write_text("\n".join([filler] * 200) + "\n", encoding="utf-8")

        with self.searching():
            self.assertIsNone(adapter._find_transcript())

    async def test_stop_releases_the_claim(self):
        """A detached attachment must not hold a session another can use."""
        adapter = self.make_adapter()
        adapter._note_paste(adapter.briefing())
        mine = self.write_session("random-id", pasted=adapter.briefing())
        with self.searching("missing.jsonl"):
            adapter._find_transcript()
        self.assertIn(mine, PartylineAdapter._CLAIMED)

        await adapter.stop()

        self.assertNotIn(mine, PartylineAdapter._CLAIMED)


if __name__ == "__main__":
    unittest.main()
