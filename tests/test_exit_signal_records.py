"""Exit records name the signal behind an exit and who sent it; an unknown peak reads not sampled."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline import process_exit
from partyline.attachment_stop_audit import direct_stop, pop_stop_intent
from partyline.memory_contracts import ProcessExit


class SignalNameTest(unittest.TestCase):
    def test_negative_codes_and_128_plus_n_name_their_signal(self):
        self.assertEqual(process_exit.exit_signal(-15), "SIGTERM")
        self.assertEqual(process_exit.exit_signal(143), "SIGTERM")
        self.assertEqual(process_exit.exit_signal(137), "SIGKILL")
        self.assertEqual(process_exit.exit_signal(-9), "SIGKILL")

    def test_ordinary_codes_name_no_signal(self):
        for code in (0, 1, 3, 125, 128):
            self.assertIsNone(process_exit.exit_signal(code), code)

    def test_notice_names_the_signal_and_the_sender(self):
        evidence = ProcessExit(code=143, limit_bytes=1024, signal="SIGTERM", sent_by="external")
        self.assertEqual(process_exit.exit_notice("reviewer", evidence),
                         "reviewer exited (code 143, SIGTERM sent by external)")
        plain = ProcessExit(code=3, limit_bytes=1024)
        self.assertEqual(process_exit.exit_notice("reviewer", plain), "reviewer exited (code 3)")

    def test_the_oom_notice_names_the_signal_and_sender_too(self):
        evidence = ProcessExit(code=-9, reason="oom", limit_bytes=1024**3, peak_bytes=1024**3,
                               result="oom-kill", signal="SIGKILL", sent_by="external")
        notice = process_exit.exit_notice("reviewer", evidence)
        self.assertIn("exit code -9, SIGKILL sent by external).", notice)

    def test_unknown_peak_reads_not_sampled_in_the_oom_notice(self):
        evidence = ProcessExit(code=-9, reason="oom", limit_bytes=1024**3, result="oom-kill")
        self.assertIn("recorded peak not sampled", process_exit.exit_notice("reviewer", evidence))


class SignalSenderTest(unittest.IsolatedAsyncioTestCase):
    def adapter(self, stopping=False):
        return SimpleNamespace(memory_scope=None, memory_limit="4G", _stopping=stopping,
                               on_status=AsyncMock(), att={"name": "reviewer", "id": "rev"},
                               post=AsyncMock())

    async def report(self, adapter, code):
        with patch.object(process_exit, "inspect_exit",
                          side_effect=lambda scope, code, limit: ProcessExit(code=code, limit_bytes=1024)):
            await process_exit.report_exit(adapter, code)

    async def test_a_signal_nobody_asked_for_is_recorded_as_external(self):
        adapter = self.adapter()

        await self.report(adapter, 143)

        adapter.post.assert_awaited_once_with(
            "system", "system", "reviewer exited (code 143, SIGTERM sent by external)")

    async def test_a_stop_partyline_made_is_recorded_with_its_source_once(self):
        adapter = self.adapter()
        direct_stop("rev", "line_process_routes.detach_attachment")

        await self.report(adapter, -15)

        adapter.post.assert_awaited_once()
        notice = adapter.post.await_args.args[2]
        self.assertIn("SIGTERM sent by partyline: line_process_routes.detach_attachment", notice)
        self.assertIsNone(pop_stop_intent("rev"))  # consumed by its exit

    async def test_a_stopping_adapter_posts_nothing_and_consumes_its_intent(self):
        adapter = self.adapter(stopping=True)
        direct_stop("rev", "restart.shutdown")

        await self.report(adapter, -15)

        adapter.post.assert_not_awaited()
        self.assertIsNone(pop_stop_intent("rev"))

    async def test_a_clean_exit_names_no_signal(self):
        adapter = self.adapter()

        await self.report(adapter, 0)

        adapter.post.assert_awaited_once_with("system", "system", "reviewer exited (code 0)")
