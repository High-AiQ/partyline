"""Cwd git identity at the attachment and wake-digest boundaries."""

import asyncio
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.attachment_view import (
    attachment_response,
    cwd_git_digest,
    cwd_git_state,
)


class CwdGitStateTest(unittest.TestCase):
    def command(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def test_non_repository_and_missing_git_have_no_invented_identity(self):
        not_repo = subprocess.CompletedProcess([], 128, "", "not a repository")
        with patch("partyline.attachment_view._git", return_value=not_repo) as git:
            self.assertIsNone(cwd_git_state("/not-a-repository"))
            git.assert_called_once()
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(cwd_git_digest(directory), "")
        with patch("partyline.attachment_view._git", side_effect=FileNotFoundError):
            self.assertIsNone(cwd_git_state("/project"))

    def test_clean_and_dirty_repository_identity_reaches_both_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.command(repo, "init", "-q")
            self.command(repo, "config", "user.email", "test@example.com")
            self.command(repo, "config", "user.name", "Test")
            (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
            self.command(repo, "add", "tracked.txt")
            self.command(repo, "commit", "-qm", "initial")

            sha = self.command(repo, "rev-parse", "--short", "HEAD")
            self.assertEqual(cwd_git_state(directory).model_dump(), {"sha": sha, "dirty": False})
            response = asyncio.run(
                attachment_response(
                    {
                        "id": "att-1",
                        "conv_id": "line",
                        "name": "sol",
                        "adapter": "codex",
                        "command": ["codex"],
                        "cwd": directory,
                        "status": "running",
                        "follow": False,
                        "last_seen": 0,
                        "created_at": 1,
                    }
                )
            )
            self.assertEqual(response["cwd_git"], {"sha": sha, "dirty": False})
            self.assertEqual(cwd_git_digest(directory), f"(cwd git: {sha} clean)")

            (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            self.assertTrue(cwd_git_state(directory).dirty)
            self.assertEqual(cwd_git_digest(directory), f"(cwd git: {sha} dirty)")

    def test_attachment_response_offloads_git_from_the_event_loop(self):
        event_loop_thread = threading.get_ident()
        worker_threads = []

        def run(command, **_kwargs):
            worker_threads.append(threading.get_ident())
            stdout = "d87b3ae\n" if "rev-parse" in command else ""
            return subprocess.CompletedProcess(command, 0, stdout, "")

        with patch("partyline.attachment_view.subprocess.run", side_effect=run):
            asyncio.run(
                attachment_response(
                    {
                        "id": "att-1",
                        "conv_id": "line",
                        "name": "sol",
                        "adapter": "codex",
                        "command": ["codex"],
                        "cwd": "/project",
                        "status": "running",
                        "follow": False,
                        "last_seen": 0,
                        "created_at": 1,
                    }
                )
            )

        self.assertEqual(len(worker_threads), 2)
        self.assertTrue(all(thread != event_loop_thread for thread in worker_threads))


if __name__ == "__main__":
    unittest.main()
