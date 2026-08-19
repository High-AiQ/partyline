"""The grok tail must wait on ``adapter._poll``, not the importing module.

2026-08-19: kimi's presence-stack split the tail into ``tail.py`` while tests
still patched ``adapter.asyncio.sleep``. The loop never yielded; a
``keep_growing`` writer filled ~31 GB; WSL OOM-killed the cockpit twice.
Do not reproduce that by running ``tests.test_grok_adapter`` on this machine.
"""

from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from partyline.adapters.bundled.grok.adapter import PartylineAdapter


GROK_PKG = Path(__file__).resolve().parents[1] / "partyline" / "adapters" / "bundled" / "grok"
SESSION_ID = "12345678-1234-4234-8234-123456789abc"


def make_adapter():
    adapter = PartylineAdapter(
        {
            "adapter_metadata": {"env_unset": []},
            "command": ["grok"],
            "cli_session": None,
            "conv_name": "poll guard",
            "cwd": "/tmp/grok-project",
            "id": SESSION_ID,
            "name": "groky",
            "resume": False,
        },
        AsyncMock(),
        AsyncMock(),
    )
    adapter._silent_until_wake = False
    adapter._accounted = 0
    return adapter


def _sleep_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "sleep":
            if isinstance(func.value, ast.Name) and func.value.id == "asyncio":
                hits.append(f"{path.name}:{node.lineno}")
    return hits


class TailPollTargetTest(unittest.TestCase):
    def test_tail_and_resume_do_not_call_asyncio_sleep(self):
        """A module split that sleeps on its own import is the OOM."""
        for name in ("tail.py", "resume.py"):
            self.assertEqual(_sleep_calls(GROK_PKG / name), [], name)

    def test_only_adapter_poll_and_run_may_asyncio_sleep(self):
        tree = ast.parse((GROK_PKG / "adapter.py").read_text(encoding="utf-8"))
        allowed = {"_poll", "_run"}
        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "sleep"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "asyncio"
                    and node.name not in allowed
                ):
                    hits.append(f"{node.name}:{child.lineno}")
        self.assertEqual(hits, [])

    def test_poll_is_called_with_no_arguments(self):
        """A leftover sleep(delay) stub TypeErrors and looks like a hang."""
        params = list(inspect.signature(PartylineAdapter._poll).parameters)
        self.assertEqual(params, ["self"])


class StopPollRunsTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_stop_patch_on_poll_actually_runs(self):
        """If this times out, the tail is waiting on the wrong sleep."""
        adapter = make_adapter()
        adapter.alive = lambda: True
        called = []

        async def stop_poll():
            called.append(True)
            adapter.alive = lambda: False

        adapter._poll = stop_poll
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat_history.jsonl"
            path.write_text('{"type":"assistant"', encoding="utf-8")
            await adapter._tail_grok_transcript(path, AsyncMock())
        self.assertEqual(called, [True])

    async def test_patching_the_adapter_module_sleep_does_not_stop_the_tail(self):
        """The false assumption that took the VM down: the wrong module."""
        adapter = make_adapter()
        adapter.alive = lambda: True
        called = []

        async def stop_poll():
            called.append("poll")
            adapter.alive = lambda: False

        async def wrong_sleep(_):
            called.append("module")
            adapter.alive = lambda: False

        adapter._poll = stop_poll
        import partyline.adapters.bundled.grok.adapter as adapter_mod
        original = adapter_mod.asyncio.sleep
        adapter_mod.asyncio.sleep = wrong_sleep
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "chat_history.jsonl"
                path.write_text('{"type":"assistant"', encoding="utf-8")
                await adapter._tail_grok_transcript(path, AsyncMock())
        finally:
            adapter_mod.asyncio.sleep = original
        self.assertEqual(called, ["poll"])
        self.assertNotIn("module", called)
