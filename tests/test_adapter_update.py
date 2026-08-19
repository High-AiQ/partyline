"""Adapter host updates: argv contract, notice shape, and attach wiring.

The runner is injected. These tests never spawn a vendor CLI.
"""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from partyline.adapter_update import (
    default_runner,
    OUTPUT_CAP,
    UpdateResult,
    apply_update,
    format_notice,
    normalize_update_command,
    requested_update_argv,
)
from partyline.adapters.loader import BUNDLED_ROOT, _manifest


class NormalizeTest(unittest.TestCase):
    def test_empty_is_none(self):
        self.assertIsNone(normalize_update_command(None))
        self.assertIsNone(normalize_update_command([]))

    def test_argv_is_kept(self):
        self.assertEqual(normalize_update_command(["grok", "update"]), ["grok", "update"])

    def test_a_shell_string_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "argv array"):
            normalize_update_command("grok update")

    def test_blank_tokens_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            normalize_update_command(["grok", ""])


class RequestedArgvTest(unittest.TestCase):
    def test_unchecked_is_none_even_when_the_adapter_has_a_command(self):
        metadata = {"grok": {"update_command": ["grok", "update"]}}
        self.assertIsNone(requested_update_argv(metadata, "grok", False))

    def test_checked_without_a_command_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no update command"):
            requested_update_argv({"raw": {}}, "raw", True)

    def test_checked_returns_the_manifest_argv(self):
        metadata = {"pi": {"update_command": ["pi", "update", "--self"]}}
        self.assertEqual(
            requested_update_argv(metadata, "pi", True), ["pi", "update", "--self"]
        )


class NoticeTest(unittest.TestCase):
    def test_names_the_jack_and_the_exit(self):
        notice = format_notice(
            "grok", ["grok", "update"], UpdateResult(0, "already current\n")
        )
        self.assertEqual(
            notice,
            "↑ @grok update · `grok update` · exit 0\nalready current",
        )

    def test_empty_output_is_said_out_loud(self):
        notice = format_notice("sol", ["codex", "update"], UpdateResult(1, "  "))
        self.assertIn("(no output)", notice)
        self.assertIn("exit 1", notice)

    def test_a_long_transcript_is_truncated_with_a_count(self):
        body = "x" * (OUTPUT_CAP + 12)
        notice = format_notice("kimi", ["opencode", "upgrade"], UpdateResult(0, body))
        self.assertIn("… [truncated, 12 more chars]", notice)
        self.assertLess(len(notice), len(body) + 80)


class ApplyUpdateTest(unittest.IsolatedAsyncioTestCase):
    async def test_posts_whatever_the_runner_returned_including_failure(self):
        posted = []

        async def post(conv_id, sender, sender_type, body):
            posted.append((conv_id, sender, sender_type, body))

        result = await apply_update(
            post, "line", "hermes", ["hermes", "update"],
            runner=lambda argv: UpdateResult(1, f"failed: {' '.join(argv)}"),
        )
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(posted[0][0], "line")
        self.assertEqual(posted[0][1:3], ("system", "system"))
        self.assertIn("exit 1", posted[0][3])
        self.assertIn("failed: hermes update", posted[0][3])


class DefaultRunnerTest(unittest.TestCase):
    """The real runner is still a fake here: subprocess.run is patched."""

    def test_combines_stdout_and_stderr(self):
        completed = subprocess.CompletedProcess(["tool"], 0, stdout="out", stderr="err")
        with patch("partyline.adapter_update.subprocess.run", return_value=completed):
            result = default_runner(["tool"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, "outerr")

    def test_timeout_is_fail_open(self):
        with patch(
            "partyline.adapter_update.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["tool"], 1, output="partial"),
        ):
            result = default_runner(["tool"])
        self.assertEqual(result.exit_code, 124)
        self.assertIn("timed out", result.output)
        self.assertIn("partial", result.output)

    def test_a_missing_binary_is_fail_open(self):
        with patch(
            "partyline.adapter_update.subprocess.run",
            side_effect=FileNotFoundError("nope"),
        ):
            result = default_runner(["missing"])
        self.assertEqual(result.exit_code, 127)
        self.assertIn("nope", result.output)


class BundledManifestTest(unittest.TestCase):
    EXPECTED = {
        "grok": ["grok", "update"],
        "claude": ["claude", "update"],
        "codex": ["codex", "update"],
        "opencode": ["opencode", "upgrade"],
        "hermes": ["hermes", "update"],
        "pi": ["pi", "update", "--self"],
        "muse": ["bash", "-lc", "curl -fsSL https://dev.meta.ai/install.sh | bash"],
        "raw": None,
    }

    def test_every_bundled_adapter_declares_the_locked_updater(self):
        found = {path.parent.name for path in BUNDLED_ROOT.glob("*/adapter.toml")}
        self.assertEqual(found, set(self.EXPECTED))
        for adapter_id, argv in self.EXPECTED.items():
            with self.subTest(adapter_id):
                self.assertEqual(_manifest(BUNDLED_ROOT / adapter_id)["update_command"], argv)
