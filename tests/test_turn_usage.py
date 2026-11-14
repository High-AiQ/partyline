"""Actual model usage per response: parsing, dedup, attribution, storage, maths, reads."""

import asyncio
import json
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, turn_usage
from partyline.adapters.bundled.claude.adapter import PartylineAdapter as Claude
from partyline.adapters.bundled.codex.adapter import PartylineAdapter as Codex
from partyline.adapters.bundled.opencode.v2 import PartylineAdapter as OpenCode
from partyline.adapters.turn_usage import TurnUsage
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.hierarchy import set_parent
from partyline.runtime import ChatRuntime
from partyline.turn_usage_labels import tool_label
from partyline.turn_usage_parse import ClaudeTurns, CodexTurns, OpenCodeTurns, opencode_turn
from partyline.turn_usage_routes import turn_usage_router
from partyline.turn_usage_summary import percentile, summary
from tests import turn_usage_fixtures as fx
from tests.adapter_event_clock import install as event_clock


def feed_all(parser, records):
    return [turn for record in records if (turn := parser.feed(record))]


def total(turn):
    return turn["input"] + turn["cache_read"] + turn["cache_write"] + turn["output"]


class LabelTest(unittest.TestCase):
    def test_labels_are_names_only(self):
        self.assertEqual(tool_label("Bash", {"command": fx.SECRET}), "Bash")
        self.assertEqual(tool_label("mcp__partyline__post_message", {"body": fx.SECRET}), "post_message")
        self.assertEqual(tool_label("mcp__partyline__captain", {"op": "accept", "args": {}}),
                         "captain:accept")
        self.assertEqual(tool_label("partyline_extras", {"op": "turn_usage", "args": {}}),
                         "extras:turn_usage")
        self.assertEqual(tool_label("mcp__partyline__extras", {"op": "screen_element_action",
                                                               "args": {"action": "invoke"}}),
                         "extras:invoke")
        self.assertEqual(tool_label("mcp__partyline__screen_element_action", {"action": "invoke"}),
                         "screen_element_action:invoke")

    def test_unknown_values_never_become_labels(self):
        hostile = {"op": fx.SECRET, "args": {"action": fx.SECRET}}
        self.assertEqual(tool_label("mcp__partyline__extras", hostile), "extras")
        self.assertEqual(tool_label("mcp__partyline__extras", {"op": "screen_element_action",
                                                               "args": {"action": fx.SECRET}}),
                         "extras:screen_element_action")
        self.assertEqual(tool_label("has space and content " + fx.SECRET), "unknown")
        self.assertEqual(tool_label("extras", None), "extras")
        self.assertEqual(tool_label("captain", {"op": "accept", "args": "text"}), "captain:accept")
        self.assertIsNone(tool_label(None))
        self.assertIsNone(tool_label(""))


class ClaudeParseTest(unittest.TestCase):
    def test_streamed_lines_merge_into_one_response(self):
        turns = feed_all(ClaudeTurns(), fx.CLAUDE_STREAMED)
        last = {turn["response_id"]: turn for turn in turns}
        self.assertEqual(set(last), {"msg_1", "msg_2"})
        first = last["msg_1"]
        # The largest streamed counts win, never a sum of the repeated lines.
        self.assertEqual((first["input"], first["cache_write"], first["cache_read"], first["output"]),
                         (2, 100, 900, 80))
        self.assertEqual(first["reasoning"], 25)
        self.assertEqual(first["context"], 1002)
        self.assertEqual(total(first), 1082)
        self.assertEqual(first["model"], "claude-sonnet-5-5")
        self.assertEqual(first["calls"], ["Bash", "extras:invoke"])
        self.assertEqual(last["msg_2"]["calls"], [])

    def test_a_line_adding_nothing_is_dropped(self):
        parser = ClaudeTurns()
        self.assertIsNotNone(parser.feed(fx.CLAUDE_STREAMED[1]))
        self.assertIsNone(parser.feed(fx.CLAUDE_STREAMED[1]))
        self.assertIsNone(parser.feed(fx.claude_line("msg_1", [fx.TEXT], fx.usage(1, 1, 1, 1), offset=9)))

    def test_only_real_model_responses_count(self):
        parser = ClaudeTurns()
        for record in (
                {"type": "user", "message": {"id": "x", "usage": fx.usage(1, 1, 1, 1)}},
                {"type": "system", "subtype": "compact_boundary"},
                fx.claude_line("syn", [fx.TEXT], fx.usage(0, 0, 0, 0), model="<synthetic>"),
                {"type": "assistant", "message": "text"}, {"type": "assistant", "message": {"id": "n"}},
                {"type": "assistant", "message": {"usage": fx.usage(1, 1, 1, 1)}}, "not a record"):
            self.assertIsNone(parser.feed(record))

    def test_bad_counts_and_timestamps_are_tolerated(self):
        bad = {"input_tokens": "x", "output_tokens": -4, "cache_read_input_tokens": True}
        line = fx.claude_line("m", [fx.TEXT], bad)
        line["timestamp"] = "yesterday"
        turn = ClaudeTurns().feed(line)
        self.assertEqual(total(turn), 0)
        self.assertAlmostEqual(turn["timestamp"], time.time(), delta=30)

    def test_the_cache_of_seen_messages_is_bounded(self):
        parser = ClaudeTurns(keep=2)
        for number in range(5):
            parser.feed(fx.claude_line(f"m{number}", [fx.TEXT], fx.usage(1, 0, 0, 1)))
        self.assertEqual(list(parser._seen), ["m3", "m4"])


class CodexParseTest(unittest.TestCase):
    def test_records_attribute_the_calls_since_the_last_one(self):
        turns = feed_all(CodexTurns(), fx.CODEX_ROLLOUT)
        self.assertEqual([turn["response_id"] for turn in turns], ["resp_1", "resp_2"])
        first, second = turns
        # Codex counts cached tokens inside input_tokens, and reasoning inside output_tokens.
        self.assertEqual((first["input"], first["cache_read"], first["output"], first["reasoning"]),
                         (13000, 8000, 96, 11))
        self.assertEqual(total(first), 21096)
        self.assertEqual(first["context"], 21000)
        self.assertEqual((first["model"], first["window"]), ("gpt-6.1-sol", 475000))
        self.assertEqual(first["calls"], ["exec"])
        self.assertEqual(second["calls"], ["wait", "sleep"])

    def test_native_json_arguments_pick_only_allowlisted_operations(self):
        def label(name, arguments):
            parser = CodexTurns()
            parser.feed(fx.codex("response_item", {"type": "function_call", "name": name,
                                                   "arguments": arguments}, 1))
            return parser.feed(fx.codex("token_usage_record", {
                "response_id": "r", "usage": fx.codex_usage(10, 0, 1)}, 2))["calls"]

        extras = "mcp__partyline__extras"
        self.assertEqual(label(extras, json.dumps({"op": "turn_usage", "args": {}})), ["extras:turn_usage"])
        screen = {"op": "screen_element_action", "args": {"action": "invoke"}}
        self.assertEqual(label(extras, json.dumps(screen)), ["extras:invoke"])
        for arguments in (json.dumps({"op": fx.SECRET, "args": {}}), "{" + fx.SECRET, json.dumps([fx.SECRET]),
                          json.dumps({"op": "turn_usage", "pad": fx.SECRET * 400}), None, 7):
            self.assertEqual(label(extras, arguments), ["extras"])
        self.assertEqual(label("exec", json.dumps({"op": "turn_usage"})), ["exec"])

    def test_old_rollouts_fall_back_to_token_count_once_per_total(self):
        turns = feed_all(CodexTurns(), fx.CODEX_OLD)
        self.assertEqual([turn["response_id"] for turn in turns], ["total-110", "total-330"])
        self.assertEqual(turns[0]["calls"], ["exec"])
        self.assertEqual((turns[0]["input"], turns[0]["cache_read"], turns[0]["window"]), (80, 20, 1000))
        self.assertEqual(turns[1]["calls"], [])

    def test_unusable_records_are_ignored(self):
        parser = CodexTurns()
        nameless = fx.codex("token_usage_record", {"usage": fx.codex_usage(1, 0, 1)})
        for record in ("x", {"payload": 3}, nameless,
                       fx.codex("event_msg", {"type": "token_count", "info": {"last_token_usage": 3}}),
                       fx.codex("event_msg", {"type": "user_message", "message": fx.SECRET}),
                       fx.codex("response_item", {"type": "function_call", "name": 3})):
            self.assertIsNone(parser.feed(record))


class OpenCodeParseTest(unittest.TestCase):
    def test_reasoning_is_separate_in_the_store_and_folded_into_output(self):
        turn = opencode_turn("msg_9", fx.opencode_row())
        # OpenCode reports reasoning apart from output; the canonical output holds both.
        self.assertEqual((turn["input"], turn["cache_read"], turn["cache_write"]), (232, 256640, 7))
        self.assertEqual((turn["output"], turn["reasoning"]), (581, 380))
        self.assertEqual(turn["context"], 256879)
        self.assertEqual(total(turn), 257460)
        self.assertEqual((turn["model"], turn["calls"]), ("glm-5.3-flash", ["bash"]))
        self.assertAlmostEqual(turn["timestamp"], fx.NOW + 1, places=2)

    def test_rows_without_usage_are_skipped(self):
        self.assertIsNone(opencode_turn("a", {"content": []}))
        self.assertIsNone(opencode_turn("a", {"tokens": {"input": 0}}))
        self.assertIsNone(opencode_turn("a", []))
        self.assertIsNone(OpenCodeTurns().feed(("a", {"tokens": "?"})))
        row = fx.opencode_row()
        row["time"] = {}
        row["tokens"]["cache"] = None
        self.assertAlmostEqual(opencode_turn("b", row)["timestamp"], time.time(), delta=30)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.att = {"id": "att", "conv_id": "line", "adapter": "claude"}

    def rows(self):
        return [dict(row) for row in self.db._exec("SELECT * FROM turn_usage ORDER BY id")]

    def test_storing_the_same_response_again_merges_it(self):
        parser = ClaudeTurns()
        for turn in feed_all(parser, fx.CLAUDE_STREAMED[:3]):
            self.assertTrue(turn_usage.store(self.db, self.att, turn))
        (row,) = self.rows()
        self.assertEqual((row["input_tokens"], row["cache_write_tokens"], row["cache_read_tokens"],
                          row["output_tokens"], row["reasoning_tokens"], row["total_tokens"]),
                         (2, 100, 900, 80, 25, 1082))
        self.assertEqual((row["context_tokens"], row["model"], row["adapter"]),
                         (1002, "claude-sonnet-5-5", "claude"))
        self.assertEqual(json.loads(row["calls"]), ["Bash"])
        # A replay after a restart has lost the in-memory merge: the row still keeps what it had.
        replay = ClaudeTurns().feed(fx.CLAUDE_STREAMED[0])
        turn_usage.store(self.db, self.att, replay)
        (row,) = self.rows()
        self.assertEqual((row["output_tokens"], json.loads(row["calls"])), (80, ["Bash"]))

    def test_no_transcript_content_is_stored(self):
        for records, parser in ((fx.CLAUDE_STREAMED, ClaudeTurns()), (fx.CODEX_ROLLOUT, CodexTurns())):
            for turn in feed_all(parser, records):
                turn_usage.store(self.db, self.att, turn)
        turn_usage.store(self.db, self.att, opencode_turn("oc", fx.opencode_row(tools=(
            {"name": "bash"}, {"name": "mcp__partyline__extras", "input": {"op": fx.SECRET, "args": {}}}))))
        hostile = ClaudeTurns().feed(fx.claude_line("h", [fx.HOSTILE, fx.CAPTAIN], fx.usage(1, 1, 1, 1)))
        turn_usage.store(self.db, self.att, hostile)
        dump = json.dumps(self.rows())
        self.assertNotIn(fx.SECRET, dump)
        self.assertIn("captain:accept", dump)
        self.assertNotIn("extras:unknown", dump)

    def test_old_responses_are_never_stored_and_expire(self):
        old = time.time() - turn_usage.RETENTION_SECONDS - 10
        turn = {**ClaudeTurns().feed(fx.CLAUDE_STREAMED[4]), "timestamp": old}
        self.assertFalse(turn_usage.store(self.db, self.att, turn))
        self.assertTrue(turn_usage.store(self.db, self.att, {**turn, "timestamp": time.time() - 100}))
        with self.db.lock:
            self.db.conn.execute("UPDATE turn_usage SET timestamp=?", (old,))
        other = {**turn, "response_id": "fresh", "timestamp": time.time()}
        turn_usage.store(self.db, self.att, other)  # a new response prunes the expired one
        self.assertEqual([row["response_id"] for row in self.rows()], ["fresh"])
        turn_usage.prune(self.db, now=time.time() + turn_usage.RETENTION_SECONDS + 10)
        self.assertEqual(self.rows(), [])

    def test_deleting_the_line_deletes_its_usage(self):
        turn_usage.store(self.db, self.att, ClaudeTurns().feed(fx.CLAUDE_STREAMED[4]))
        self.db.delete_conversation("line")
        self.assertEqual(self.rows(), [])

    def test_the_callback_stores_on_a_thread(self):
        runtime = ChatRuntime(self.db)
        noted = turn_usage.turn_usage_callback(runtime, self.att)
        self.assertTrue(asyncio.run(noted(ClaudeTurns().feed(fx.CLAUDE_STREAMED[4]))))
        self.assertEqual(len(self.rows()), 1)


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        for line in ("line", "sub", "other"):
            self.db.create_conversation(line, line)
        set_parent(self.db, "sub", "line")
        self.n = 0

    def put(self, conv, att, calls, tokens, adapter="claude"):
        self.n += 1
        turn = {"response_id": f"r{self.n}", "timestamp": time.time() - 5, "model": None, "input": tokens,
                "cache_read": 0, "cache_write": 0, "output": 0, "reasoning": 0, "context": tokens,
                "window": None, "calls": calls}
        turn_usage.store(self.db, {"id": att, "conv_id": conv, "adapter": adapter}, turn)

    def test_nearest_rank_percentiles(self):
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        self.assertEqual((percentile(values, .5), percentile(values, .95)), (50, 100))
        self.assertEqual(percentile([7], .95), 7)

    def test_per_tool_totals_count_whole_turns(self):
        for tokens in (100, 200, 300, 400):
            self.put("line", "a1", ["Bash"], tokens)
        self.put("line", "a1", ["extras:turn_usage", "Bash"], 1000)
        self.put("line", "a1", ["extras:blender_exec", "extras:turn_usage"], 50)
        self.put("line", "a2", [], 20)
        found = {(row.tool, row.sub_op): row for row in
                 summary(self.db, "line", ["line"], 0).rows}
        bash = found[("Bash", "")]
        self.assertEqual((bash.turns, bash.p50_total_tokens, bash.p95_total_tokens, bash.max_total_tokens,
                          bash.total_tokens), (5, 300, 1000, 1000, 2000))
        self.assertEqual(found[("extras", "")].turns, 2)
        usage = found[("extras", "turn_usage")]
        self.assertEqual((usage.turns, usage.total_tokens), (2, 1050))
        self.assertEqual(found[("extras", "blender_exec")].total_tokens, 50)
        self.assertEqual(found[("(no tool)", "")].turns, 1)
        merged = {(row.tool, row.sub_op) for row in summary(self.db, "line", ["line"], 0, "tool").rows}
        self.assertNotIn(("extras", "tool_usage"), merged)
        self.assertIn(("extras", ""), merged)

    def test_line_and_attachment_totals_do_not_double_count_multi_tool_turns(self):
        self.put("line", "a1", ["Bash", "Read", "Grep"], 100)
        self.put("line", "a1", ["Bash"], 40)
        self.put("sub", "a2", ["Read"], 60, adapter="codex")
        self.put("other", "a3", ["Read"], 999)
        result = summary(self.db, "line", ["line", "sub"], 0, include_descendants=True)
        self.assertEqual((result.totals.turns, result.totals.total_tokens, result.totals.max_context_tokens),
                         (3, 200, 100))
        self.assertEqual({line.conv_id: (line.turns, line.total_tokens) for line in result.lines},
                         {"line": (2, 140), "sub": (1, 60)})
        self.assertEqual([(a.attachment_id, a.adapter, a.total_tokens) for a in result.attachments],
                         [("a1", "claude", 140), ("a2", "codex", 60)])
        self.assertEqual(sum(row.total_tokens for row in result.rows if not row.sub_op), 100 * 3 + 40 + 60)

    def test_the_window_excludes_older_records(self):
        self.put("line", "a1", ["Bash"], 100)
        self.assertEqual(summary(self.db, "line", ["line"], time.time() + 60).totals.turns, 0)
        self.assertEqual(summary(self.db, "line", ["line"], 0).totals.turns, 1)


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        for line in ("line", "sub", "other"):
            self.db.create_conversation(line, line)
        set_parent(self.db, "sub", "line")
        self.att = {"id": "a1", "conv_id": "sub", "adapter": "codex"}
        turn_usage.store(self.db, self.att, {
            "response_id": "r", "timestamp": time.time() - 1, "model": None, "input": 5, "cache_read": 0,
            "cache_write": 0, "output": 5, "reasoning": 0, "context": 5, "window": None, "calls": ["exec"]})
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(turn_usage_router(ChatRuntime(self.db)))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        person = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        token = auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), person["id"])
        self.person = {"Authorization": f"Bearer {token}"}

    def user(self):
        return self.person

    def machine(self, ident, conv_id):
        self.db.add_attachment(ident, conv_id, ident, "raw", ["sh"], self.directory.name, f"owner-{ident}")
        return {"Authorization": f"Bearer {auth_store.ensure_api_token(self.db, ident)}"}

    def test_a_person_reads_any_line(self):
        reply = self.client.get("/api/telemetry/turns/summary", headers=self.user(),
                                params={"conv_id": "sub"})
        self.assertEqual(reply.status_code, 200, reply.text)
        body = reply.json()
        self.assertEqual(body["totals"]["turns"], 1)
        self.assertEqual(body["rows"][0]["tool"], "exec")
        self.assertEqual(self.client.get("/api/telemetry/turns/summary", params={"conv_id": "nope"},
                                         headers=self.user()).status_code, 404)
        tree = self.client.get("/api/telemetry/turns/summary", headers=self.user(),
                               params={"conv_id": "line", "include_descendants": "true"}).json()
        self.assertEqual(tree["totals"]["turns"], 1)
        self.assertEqual(self.client.get("/api/telemetry/turns/summary", headers=self.user(),
                                         params={"conv_id": "line"}).json()["totals"]["turns"], 0)

    def test_a_process_reads_its_own_line_and_descendants_only(self):
        mine = self.machine("lead", "line")
        get = lambda conv: self.client.get(  # noqa: E731
            "/api/telemetry/turns/summary", headers=mine, params={"conv_id": conv})
        self.assertEqual(get("line").status_code, 200)
        self.assertEqual(get("sub").json()["totals"]["turns"], 1)
        self.assertEqual(get("other").status_code, 403)

    def test_requires_credentials(self):
        self.assertIn(self.client.get("/api/telemetry/turns/summary", params={"conv_id": "sub"}).status_code,
                      (401, 403))


class SeamTest(unittest.IsolatedAsyncioTestCase):
    def adapter(self, **att):
        class Probe(TurnUsage):
            turn_parser = ClaudeTurns

        probe = Probe.__new__(Probe)
        probe.att, probe.spawned_at = att, fx.NOW - 1
        return probe

    async def test_without_a_callback_nothing_happens(self):
        await self.adapter().note_turn_usage(fx.CLAUDE_STREAMED[0])

    async def test_a_response_is_handed_over_once_and_stale_ones_are_not(self):
        noted = AsyncMock()
        probe = self.adapter(on_turn_usage=noted)
        await probe.note_turn_usage(fx.CLAUDE_STREAMED[0])
        await probe.note_turn_usage(fx.CLAUDE_STREAMED[0])
        noted.assert_awaited_once()
        old = fx.claude_line("old", [fx.TEXT], fx.usage(1, 1, 1, 1), offset=-3600)
        await probe.note_turn_usage(old)
        noted.assert_awaited_once()

    async def test_a_failing_callback_never_breaks_the_tail(self):
        probe = self.adapter(on_turn_usage=AsyncMock(side_effect=RuntimeError("db gone")))
        await probe.note_turn_usage(fx.CLAUDE_STREAMED[0])

    async def test_only_the_three_adapters_use_it(self):
        self.assertTrue(all(issubclass(cls, TurnUsage) for cls in (Claude, Codex, OpenCode)))
        root = Path(__file__).parents[1] / "partyline" / "adapters" / "bundled"
        users = {path.parent.name for path in root.glob("*/*.py") if "note_turn_usage" in path.read_text()}
        self.assertEqual(users, {"claude", "codex", "opencode"})
        for kind in ("antigravity", "cursor", "deepseek", "grok", "hermes", "muse", "pi", "raw"):
            self.assertNotIn("TurnUsage", (root / kind / "adapter.py").read_text())


class AdapterWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_claude_tail_reports_each_streamed_response_through_the_seam(self):
        noted = AsyncMock()
        att = {"id": "a", "name": "claude", "cwd": "/work", "resume": True, "on_turn_usage": noted}
        adapter = Claude(att, AsyncMock(), AsyncMock())
        event_clock(adapter)
        adapter._silent_until_wake = False
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: False  # speech is not what this tests
        adapter._recorded_our_token = lambda path: True

        async def tail(path, handle):
            for record in fx.CLAUDE_STREAMED:
                await handle(record)

        adapter._tail_jsonl = tail
        with (patch("partyline.adapters.bundled.claude.adapter.asyncio.sleep", AsyncMock()),
              patch("partyline.adapters.bundled.claude.adapter.glob.glob", return_value=["f.jsonl"])):
            await adapter._run()
        sent = {}
        for call in noted.await_args_list:
            sent[call.args[0]["response_id"]] = call.args[0]
        self.assertEqual(sent["msg_1"]["output"], 80)
        self.assertEqual(sent["msg_1"]["calls"], ["Bash", "extras:invoke"])
        self.assertEqual(sent["msg_2"]["output"], 40)

    async def test_codex_tail_reports_responses_before_the_event_filter(self):
        noted = AsyncMock()
        adapter = Codex({"command": ["codex"], "cli_session": "s", "name": "codex", "resume": True,
                         "on_turn_usage": noted}, AsyncMock(), AsyncMock())
        event_clock(adapter)
        adapter.alive = lambda: True
        adapter._fresh = lambda timestamp: True
        adapter._find_rollout = lambda: "rollout.jsonl"

        async def tail(path, handle):
            for record in fx.CODEX_ROLLOUT:
                await handle(record)

        adapter._tail_jsonl = tail
        with (patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", AsyncMock()),
              patch("builtins.open", side_effect=OSError)):
            await adapter._run()
        sent = [call.args[0]["response_id"] for call in noted.await_args_list]
        self.assertEqual(sent, ["resp_1", "resp_2"])


class ResumedCodexTest(unittest.IsolatedAsyncioTestCase):
    def home(self, *, session="s", forked="s"):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        rollout = root / "sessions" / "2026" / "01" / "01" / "rollout-x.jsonl"
        rollout.parent.mkdir(parents=True)
        meta = fx.codex("session_meta", {"id": session, "forked_from_id": forked})
        lines = [json.dumps(record) for record in [meta, *fx.CODEX_ROLLOUT]]
        rollout.write_text("\n".join(lines) + "\n{partial")
        return str(root)

    def adapter(self, noted):
        adapter = Codex({"command": ["codex"], "cli_session": "s", "name": "codex", "resume": True,
                         "on_turn_usage": noted}, AsyncMock(), AsyncMock())
        event_clock(adapter)
        adapter.alive = lambda: True
        adapter.spawned_at = fx.NOW - 1
        return adapter

    async def test_a_resumed_process_reports_usage_from_its_rollout_beside_thread_history(self):
        from partyline.adapters.bundled.codex import resume_usage

        seen = []
        both = asyncio.Event()

        async def noted(turn):
            seen.append(turn["response_id"])
            both.set() if len(seen) == 2 else None

        async def history(adapter, home, thread_id):
            await both.wait()
            return True

        adapter = self.adapter(noted)
        with patch.object(resume_usage, "tail_thread_history", history):
            self.assertTrue(await resume_usage.tail_history_with_usage(adapter, self.home(), "s"))
        self.assertEqual(seen, ["resp_1", "resp_2"])

    async def test_a_fork_created_after_the_first_read_is_followed_too(self):
        from partyline.adapters.bundled.codex import resume_usage

        seen = []
        events = {name: asyncio.Event() for name in ("first", "fork")}

        async def noted(turn):
            seen.append(turn["response_id"])
            events["first" if turn["response_id"] == "resp_2" else "fork"].set() \
                if turn["response_id"] in ("resp_2", "fork_1") else None

        adapter = self.adapter(noted)
        home = self.home()

        async def history(adapter_, home_, thread_id):
            await events["first"].wait()  # the prior rollout is read and pinned by now
            fork = Path(home) / "sessions" / "2026" / "01" / "01" / "rollout-fork.jsonl"
            fork.write_text("\n".join(json.dumps(record) for record in [
                fx.codex("session_meta", {"id": "new", "forked_from_id": "s"}),
                fx.codex("token_usage_record", {"response_id": "fork_1",
                                                "usage": fx.codex_usage(50, 0, 5)}, 20)]) + "\n")
            adapter._changes.notify()
            await events["fork"].wait()
            return True

        with patch.object(resume_usage, "tail_thread_history", history):
            self.assertTrue(await resume_usage.tail_history_with_usage(adapter, home, "s"))
        self.assertEqual(seen, ["resp_1", "resp_2", "fork_1"])

    async def test_a_rollout_of_another_session_or_a_failing_store_never_disturbs_the_relay(self):
        from partyline.adapters.bundled.codex import resume_usage

        async def history(adapter, home, thread_id):
            await asyncio.sleep(0)
            return False

        noted = AsyncMock()
        adapter = self.adapter(noted)
        adapter.note_turn_usage = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(resume_usage, "tail_thread_history", history):
            self.assertFalse(await resume_usage.tail_history_with_usage(
                adapter, self.home(session="other", forked="other"), "s"))
            self.assertFalse(await resume_usage.tail_history_with_usage(adapter, self.home(), "s"))
        noted.assert_not_awaited()

    async def test_run_uses_the_usage_aware_thread_history_tail_on_resume(self):
        adapter = self.adapter(AsyncMock())
        adapter._home = "/home"
        relay = AsyncMock(return_value=True)
        with (patch("partyline.adapters.bundled.codex.adapter.asyncio.sleep", AsyncMock()),
              patch("partyline.adapters.bundled.codex.adapter.tail_history_with_usage", relay)):
            await adapter._run()
        relay.assert_awaited_once_with(adapter, "/home", "s")


class McpOpTest(unittest.TestCase):
    def test_turn_usage_is_an_extras_op_that_reads_the_summary_route(self):
        from partyline.mcp import catalog, tools_turn_usage

        self.assertIn("turn_usage", catalog.EXTRAS_OPS)
        state = {"actions": ["read"], "role": "worker"}
        self.assertEqual(catalog.door("turn_usage", state), "extras")
        client = unittest.mock.Mock(home="line")
        client.request.return_value = {"totals": {}}
        self.assertEqual(catalog.dispatch(client, "extras", {"op": "turn_usage", "args": {
            "include_descendants": True, "group": "tool"}}, state), {"totals": {}})
        path = client.request.call_args.args[1]
        self.assertTrue(path.startswith("/api/telemetry/turns/summary?conv_id=line"))
        self.assertIn("include_descendants=true", path)
        self.assertEqual(tools_turn_usage.tool_list(state)[0]["name"], "turn_usage")
