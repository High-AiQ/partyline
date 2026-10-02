"""Cwd git identity at the attachment and wake-digest boundaries."""

import asyncio
import subprocess
import tempfile
import threading
import time
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
                        "last_seen": 0,
                        "created_at": 1,
                    }
                )
            )

        self.assertEqual(len(worker_threads), 2)
        self.assertTrue(all(thread != event_loop_thread for thread in worker_threads))

    def test_git_fanout_is_capped_and_page_wait_is_bounded(self):
        active = [0]
        maximum = [0]
        lock = threading.Lock()

        def hang(command, **_kwargs):
            with lock:
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
            try:
                time.sleep(1.2)
                return subprocess.CompletedProcess(command, 0, "d87b3ae\n", "")
            finally:
                with lock:
                    active[0] -= 1

        async def fanout():
            attachments = [
                {"id": f"att-{i}", "conv_id": "line", "name": "sol", "adapter": "codex",
                 "command": ["codex"], "cwd": "/project", "status": "running",
                 "last_seen": 0, "created_at": 1}
                for i in range(64)
            ]
            started = time.monotonic()
            responses = await asyncio.gather(*(attachment_response(att) for att in attachments))
            return time.monotonic() - started, responses

        with patch("partyline.attachment_view.subprocess.run", side_effect=hang):
            elapsed, responses = asyncio.run(fanout())

        self.assertLess(elapsed, 1.0)
        self.assertTrue(all(response["cwd_git"] is None for response in responses))
        self.assertLessEqual(maximum[0], 4)

    def test_same_cwd_fanout_coalesces_and_timeout_does_not_cancel_lookup(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow_git(command, **_kwargs):
            calls.append(command[-1])
            if "rev-parse" in command:
                entered.set()
                release.wait(2)
                return subprocess.CompletedProcess(command, 0, "d87b3ae\n", "")
            return subprocess.CompletedProcess(command, 0, "", "")

        async def fanout():
            attachment = {
                "id": "att", "conv_id": "line", "name": "sol", "adapter": "codex",
                "command": ["codex"], "cwd": "/shared", "status": "running",
                "last_seen": 0, "created_at": 1,
            }
            with patch("partyline.attachment_view.GIT_LOOKUP_TIMEOUT_SECONDS", 0.02):
                expired = asyncio.create_task(attachment_response(attachment))
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            others = [asyncio.create_task(attachment_response({**attachment, "id": f"att-{i}"}))
                      for i in range(63)]
            try:
                self.assertIsNone((await expired)["cwd_git"])
                release.set()
                responses = await asyncio.gather(*others)
            finally:
                release.set()
            return responses

        with patch("partyline.attachment_view.subprocess.run", side_effect=slow_git):
            responses = asyncio.run(fanout())

        self.assertEqual(len(calls), 2)
        self.assertEqual([response["cwd_git"] for response in responses],
                         [{"sha": "d87b3ae", "dirty": False}] * 63)


if __name__ == "__main__":
    unittest.main()
