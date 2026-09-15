"""A line hears whether its checkout is current and clean; a stale base cuts no child."""

import os
import subprocess
import tempfile
import unittest

from partyline import checkout_health


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _commit(repo, message):
    _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
         "--allow-empty", "-m", message, cwd=repo)


class CheckoutHealthTest(unittest.TestCase):
    """An origin with two clones: `work` is the line's checkout, `other` moves origin on."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        origin = os.path.join(self.directory.name, "origin.git")
        _git("init", "-q", "--bare", "-b", "main", origin, cwd=self.directory.name)
        self.work = os.path.join(self.directory.name, "work")
        _git("clone", "-q", origin, self.work, cwd=self.directory.name)
        _git("checkout", "-q", "-b", "main", cwd=self.work)
        _commit(self.work, "root")
        _git("push", "-q", "-u", "origin", "main", cwd=self.work)
        self.other = os.path.join(self.directory.name, "other")
        _git("clone", "-q", origin, self.other, cwd=self.directory.name)

    def test_a_current_clean_checkout_reads_as_such(self):
        health = checkout_health.inspect(self.work)
        self.assertEqual((health.ahead, health.behind, health.modified, health.untracked),
                         (0, 0, 0, 0))
        self.assertTrue(health.fetched)
        text = checkout_health.describe(health)
        self.assertIn("on main, up to date with origin/main; working tree clean", text)
        self.assertNotIn("STALE", text)
        self.assertIsNone(checkout_health.stale_base_reason(health))

    def test_a_checkout_behind_its_upstream_is_stale_and_cuts_no_child(self):
        _commit(self.other, "upstream moved")
        _commit(self.other, "and again")
        _git("push", "-q", cwd=self.other)
        _commit(self.work, "local only")
        with open(os.path.join(self.work, "notes.md"), "w") as fh:
            fh.write("uncommitted\n")
        health = checkout_health.inspect(self.work)  # the fetch sees the upstream move
        self.assertEqual((health.ahead, health.behind, health.untracked), (1, 2, 1))
        text = checkout_health.describe(health)
        self.assertIn("2 commits behind and 1 local commit ahead of origin/main", text)
        self.assertIn("1 untracked file", text)
        self.assertIn("STALE", text)
        self.assertIn("ask before basing anything on it", text)
        reason = checkout_health.stale_base_reason(health)
        self.assertIn("2 commits behind origin/main", reason)
        self.assertIn("ask the person to bring main up to date", reason)

    def test_without_a_fetch_the_report_says_the_upstream_was_not_refreshed(self):
        _commit(self.other, "upstream moved")
        _git("push", "-q", cwd=self.other)
        health = checkout_health.inspect(self.work, fetch=False)
        self.assertEqual(health.behind, 0)  # not visible until fetched
        self.assertIn("(upstream not refreshed)", checkout_health.describe(health))

    def test_a_dirty_but_current_checkout_warns_without_blocking(self):
        with open(os.path.join(self.work, "notes.md"), "w") as fh:
            fh.write("uncommitted\n")
        _git("add", "notes.md", cwd=self.work)
        health = checkout_health.inspect(self.work)
        self.assertEqual(health.modified, 1)
        text = checkout_health.describe(health)
        self.assertIn("working tree 1 modified file — uncommitted work belongs to someone", text)
        self.assertIsNone(checkout_health.stale_base_reason(health))

    def test_outside_git_or_without_an_upstream_there_is_no_alarm(self):
        self.assertIsNone(checkout_health.inspect(self.directory.name))
        self.assertIsNone(checkout_health.describe(None))
        lone = os.path.join(self.directory.name, "lone")
        os.makedirs(lone)
        _git("init", "-q", "-b", "main", cwd=lone)
        _commit(lone, "root")
        text = checkout_health.describe(checkout_health.inspect(lone))
        self.assertIn("tracking no upstream; working tree clean", text)
