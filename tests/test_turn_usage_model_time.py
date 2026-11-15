"""Model time: the gap from the previous tool result or user message to a response's completion."""

import tempfile
import time
import unittest

from partyline import turn_usage
from partyline.db import Db
from partyline.turn_usage_parse import ClaudeTurns, CodexTurns, OpenCodeTurns, model_ms
from partyline.turn_usage_summary import summary
from tests import turn_usage_fixtures as fx


def user(offset, **extra):
    content = {"content": [{"type": "tool_result"}]}
    return {"type": "user", "timestamp": fx.iso(offset), "message": content, **extra}


def reply(ident, offset, content=None, out=10):
    return fx.claude_line(ident, content or [fx.TEXT], fx.usage(1, 0, 100, out), offset=offset)


def last(parser, records):
    turns = [turn for record in records if (turn := parser.feed(record))]
    return {turn["response_id"]: turn["model_ms"] for turn in turns}


class ClaudeModelTimeTest(unittest.TestCase):
    def test_the_gap_runs_from_the_input_to_the_last_line_of_the_message(self):
        got = last(ClaudeTurns(), [
            user(0), reply("a", 2, [fx.THINKING]),
            user(3),  # a tool of this very message finishing before its later lines: not the input
            reply("a", 5, [fx.BASH], out=20), user(6), reply("b", 9)])
        self.assertEqual(got, {"a": 5000, "b": 3000})

    def test_a_person_message_counts_and_a_sidechain_does_not(self):
        got = last(ClaudeTurns(), [user(0), user(4, isSidechain=True), reply("a", 7)])
        self.assertEqual(got, {"a": 7000})

    def test_no_input_a_bad_timestamp_or_an_implausible_gap_records_nothing(self):
        self.assertEqual(last(ClaudeTurns(), [reply("a", 2)]), {"a": None})
        bad = reply("a", 2)
        bad["timestamp"] = "not a time"
        self.assertEqual(last(ClaudeTurns(), [user(0), bad]), {"a": None})
        self.assertEqual(last(ClaudeTurns(), [user(0), reply("a", 4000)]), {"a": None})
        self.assertEqual(last(ClaudeTurns(), [{**user(0), "timestamp": "x"}, reply("a", 2)]), {"a": None})
        self.assertIsNone(model_ms(5, 4))

    def test_a_later_line_that_only_extends_the_time_is_reported(self):
        parser = ClaudeTurns()
        parser.feed(user(0))
        self.assertEqual(parser.feed(reply("a", 2))["model_ms"], 2000)
        self.assertEqual(parser.feed(reply("a", 4))["model_ms"], 4000)
        self.assertIsNone(parser.feed(reply("a", 4)))


class CodexModelTimeTest(unittest.TestCase):
    def rollout(self, *records):
        return last(CodexTurns(), records)

    def test_the_gap_runs_from_the_last_tool_output_or_user_message(self):
        got = self.rollout(
            fx.codex("event_msg", {"type": "item_completed", "item": {"type": "UserMessage"}}, 1),
            fx.codex("token_usage_record", {"response_id": "r1", "usage": fx.codex_usage(10, 0, 5)}, 3),
            fx.codex("response_item", {"type": "custom_tool_call_output"}, 4),
            fx.codex("response_item", {"type": "function_call_output"}, 5),
            fx.codex("token_usage_record", {"response_id": "r2", "usage": fx.codex_usage(10, 0, 5)}, 9),
            fx.codex("event_msg", {"type": "user_message", "message": fx.SECRET}, 10),
            fx.codex("token_usage_record", {"response_id": "r3", "usage": fx.codex_usage(10, 0, 5)}, 11))
        self.assertEqual(got, {"r1": 2000, "r2": 4000, "r3": 1000})

    def test_a_response_with_no_input_before_it_or_an_old_rollout_records_nothing(self):
        done = {"response_id": "r1", "usage": fx.codex_usage(10, 0, 5)}
        self.assertEqual(self.rollout(fx.codex("token_usage_record", done, 3)), {"r1": None})
        self.assertEqual(self.rollout(
            fx.codex("response_item", {"type": "custom_tool_call_output"}, 1),
            fx.codex("token_usage_record", done, 3),
            fx.codex("token_usage_record", {**done, "response_id": "r2"}, 4)), {"r1": 2000, "r2": None})
        old = self.rollout(
            fx.codex("response_item", {"type": "custom_tool_call_output"}, 1),
            *[r for r in fx.CODEX_OLD if r["payload"].get("info")])
        self.assertTrue(old and all(value is None for value in old.values()))


class OpenCodeModelTimeTest(unittest.TestCase):
    def test_a_row_spans_its_tools_so_nothing_is_recorded(self):
        turn = OpenCodeTurns().feed(("oc", fx.opencode_row()))
        self.assertIsNone(turn["model_ms"])


class StoredModelTimeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        for line in ("line", "sub"):
            self.db.create_conversation(line, line)
        self.n = 0

    def put(self, att, calls, took, *, ident=None, conv="line"):
        self.n += 1
        turn = {"response_id": ident or f"r{self.n}", "timestamp": time.time() - 5, "model": None,
                "input": 10, "cache_read": 0, "cache_write": 0, "output": 0, "reasoning": 0,
                "context": 10, "window": None, "calls": calls, "model_ms": took}
        turn_usage.store(self.db, {"id": att, "conv_id": conv, "adapter": "claude"}, turn)

    def test_a_repeat_keeps_the_largest_known_time(self):
        self.put("a", [], 1000, ident="x")
        self.put("a", [], None, ident="x")
        self.put("a", [], 4000, ident="x")
        self.put("a", [], 2000, ident="x")
        (row,) = self.db._exec("SELECT model_ms FROM turn_usage").fetchall()
        self.assertEqual(row[0], 4000)

    def test_rows_and_totals_report_p50_and_p95_over_the_turns_that_have_one(self):
        for took in (1000, 2000, 3000, 4000):
            self.put("a", ["Bash"], took)
        self.put("a", ["Bash"], None)
        self.put("b", ["Read"], None, conv="sub")
        result = summary(self.db, "line", ["line", "sub"], 0, include_descendants=True)
        self.assertEqual((result.totals.turns, result.totals.model_time_turns, result.totals.p50_model_ms,
                          result.totals.p95_model_ms), (6, 4, 2000, 4000))
        rows = {(row.tool, row.sub_op): row for row in result.rows}
        bash = rows[("Bash", "")]
        self.assertEqual((bash.turns, bash.model_time_turns, bash.p50_model_ms, bash.p95_model_ms),
                         (5, 4, 2000, 4000))
        read = rows[("Read", "")]
        self.assertEqual((read.model_time_turns, read.p50_model_ms, read.p95_model_ms), (0, None, None))
        by_line = {line.conv_id: line.p95_model_ms for line in result.lines}
        self.assertEqual(by_line, {"line": 4000, "sub": None})
