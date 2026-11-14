"""A fresh spawn and a resume wire the same hooks and settings, except the named differences."""

import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from partyline.attachment_resume import resume_adapter
from partyline.attachment_start import prepare_attachment
from partyline.db import Db
from partyline.resource_budget import GIB, Host
from partyline.runtime import ChatRuntime

# Keys only the resume path builds: the delivery history it replays and the resume bookkeeping.
RESUME_ONLY_KEYS = {
    "resume", "delivered_bodies", "delivered_transcript_records", "legacy_relayed_bodies",
    "mark_transcript_delivery", "post_resume_record",
}
# Keys only a fresh spawn sets: none today.
FRESH_ONLY_KEYS: set[str] = set()
# Hooks that must be live callables on a resume, whatever the adapter.
HOOKS = ("on_process_exit", "on_provider_error", "on_turn_usage", "startup_attention")


class _Presence:
    def watch(self, adapter, *_args):
        return adapter

    def posting(self, *_args):
        return lambda *_: None

    def statusing(self, *_args, **_kwargs):
        return lambda *_: None


class WiringParityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        host = patch("partyline.resource_budget.host_resources", return_value=Host(cpus=8, ram_bytes=8 * GIB))
        host.start()
        self.addCleanup(host.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")

    def attachment(self, adapter):
        self.db._exec("DELETE FROM attachments")
        self.db.add_attachment("one", "line", "worker", adapter, [adapter], self.directory.name)
        self.db.set_cli_session("one", "s", None)
        return self.db.get_attachment("one")

    def fresh_keys(self, adapter):
        att = self.attachment(adapter)
        att["runtime_owner"] = "owner"
        with patch("partyline.attachment_wiring.provision_connection"):
            prepare_attachment(att, self.runtime, lambda *_: "hook", "")
        return att

    async def resumed_keys(self, adapter):
        self.attachment(adapter)
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='one'")
        made = {}

        def make(_kind, att, *_args, **_kwargs):
            made["att"] = att
            return AsyncMock(stage_startup_delivery=lambda _m: False)

        metadata = {adapter: {"capabilities": {"resume": True}}}
        with patch("partyline.attachment_wiring.provision_connection"):
            await resume_adapter("one", None, runtime=self.runtime, adapter_metadata=metadata,
                                 make_adapter=make, presence=_Presence(), hook_url=lambda *_: "hook")
        self.runtime.live.clear()
        return made["att"]

    async def test_both_paths_wire_the_same_keys_for_every_adapter(self):
        for adapter in ("claude", "codex", "opencode-v2"):
            with self.subTest(adapter=adapter):
                fresh, resumed = set(self.fresh_keys(adapter)), set(await self.resumed_keys(adapter))
                self.assertEqual(fresh - resumed, FRESH_ONLY_KEYS)
                self.assertEqual(resumed - fresh, RESUME_ONLY_KEYS)

    async def test_a_resumed_process_gets_every_hook_the_fresh_one_does(self):
        for adapter in ("claude", "codex", "opencode-v2"):
            with self.subTest(adapter=adapter):
                att = await self.resumed_keys(adapter)
                for hook in HOOKS:
                    self.assertTrue(callable(att[hook]), hook)
                self.assertEqual(callable(att.get("on_compaction")), adapter != "claude")
                self.assertIn("scratch_worktrees", att)
                self.assertIn("auto_compact_tokens", att)
                self.assertIn("topic", att)
                self.assertIn("fresh_checkpoint", att)
