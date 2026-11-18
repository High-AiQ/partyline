"""Recording evidence stays bounded and expires against an injected clock."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


from partyline.screen_workflow_learning import (
    RETENTION,
    compact_observation,
    read_observation,
    narrate,
    record_call,
    start,
    stop,
    walkthrough_narration,
)
from partyline.screen_workflow_transcripts import _native_calls, _opencode_calls


class MemoryDb:
    def __init__(self):
        self.row = None

    def _exec(self, query, args=()):
        if query.startswith("DELETE FROM"):
            return Result(None)
        if query.startswith("SELECT id FROM"):
            return Result({"id": self.row["id"]} if self.row and self.row["state"] == "recording" else None)
        if query.startswith("INSERT INTO"):
            self.row = dict(zip(("id", "conv_id", "grant_id", "owner_id", "grant_owner_id",
                                 "grant_line_id", "started_at", "expires_at"), args, strict=True))
            self.row.update(state="recording", stopped_at=None, calls="[]", narration="[]")
        elif query.startswith("SELECT id,calls,started_at"):
            return Result({key: self.row[key] for key in ("id", "calls", "started_at")}
                          if self.row and self.row["state"] == "recording" else None)
        elif query.startswith("SELECT id,owner_id,started_at"):
            return Result([{key: self.row[key] for key in ("id", "owner_id", "started_at")}
                           ] if self.row and self.row["state"] == "recording" else [])
        elif query.startswith("UPDATE screen_workflow_demonstrations SET calls"):
            self.row["calls"], = args[:1]
        elif query.startswith("SELECT narration,started_at"):
            return Result({key: self.row[key] for key in ("narration", "started_at")}
                          if self.row and self.row["id"] == args[0] else None)
        elif query.startswith("UPDATE screen_workflow_demonstrations SET narration"):
            self.row["narration"] = args[0]
        elif query.startswith("UPDATE screen_workflow_demonstrations SET state"):
            self.row.update(state="stopped", stopped_at=args[0])
            return Result(self.row, 1)
        elif query.startswith("SELECT *"):
            return Result(self.row if self.row and self.row["id"] == args[0] else None)
        return Result(None)


class Result:
    def __init__(self, row, rowcount=0):
        self.row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row or []


class DemonstrationTests(unittest.TestCase):
    def test_native_structured_transcript_recovers_bounded_call_evidence(self):
        records = [
            {"type": "assistant", "timestamp": "2026-01-01T00:00:00Z", "message": {
                "content": [{"type": "tool_use", "id": "call-1", "name": "mcp__partyline__extras",
                             "input": {"op": "screen_window_snapshot",
                                       "args": {"window": "Editor", "refresh": False}}}],
            }},
            {"type": "user", "timestamp": "2026-01-01T00:00:01Z", "message": {
                "content": [{"type": "tool_result", "tool_use_id": "call-1",
                             "content": '{"status":"completed","elements":[{"role":"button",'
                                        '"name":"Save","path":"Editor","value":"typed text"}]}'}],
            }},
        ]
        calls = _native_calls(records)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["operation"], "screen_window_snapshot")
        self.assertEqual(calls[0]["window"], "Editor")
        self.assertEqual(calls[0]["outcome"], "completed")
        self.assertEqual(calls[0]["observation"], {
            "targets": [{"role": "button", "name": "Save", "scope": "Editor"}],
        })
        self.assertNotIn("typed text", json.dumps(calls[0]["observation"]))

    def test_opencode_history_reads_only_selected_session_from_existing_store(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.db"
            db = sqlite3.connect(path)
            try:
                db.execute("CREATE TABLE session_message(session_id TEXT,type TEXT,data TEXT,seq INTEGER)")
                row = {"time": {"created": 1767225600000, "completed": 1767225601000}, "content": [{
                    "type": "tool", "name": "screen_window_snapshot", "state": {
                        "input": {"window": "Editor"}, "status": "completed",
                        "output": {"status": "completed", "elements": [
                            {"semantic_role": "button", "name": "Save", "path": "Editor"},
                        ]},
                    },
                }]}
                db.execute("INSERT INTO session_message VALUES(?,?,?,?)",
                           ("session-a", "assistant", json.dumps(row), 1))
                db.execute("INSERT INTO session_message VALUES(?,?,?,?)",
                           ("session-b", "assistant", json.dumps(row), 2))
                db.commit()
            finally:
                db.close()
            attachment = {"cli_session": "session-a", "cwd": directory}
            with patch.dict("os.environ", {"OPENCODE_DB": str(path)}):
                calls = _opencode_calls(attachment, 1767225599, 1767225601)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["window"], "Editor")
            self.assertEqual(calls[0]["completed_at"], 1767225601)
            self.assertEqual(calls[0]["observation"]["targets"][0]["name"], "Save")
            with patch.dict("os.environ", {"OPENCODE_DB": "relative-store.db"}):
                self.assertEqual(_opencode_calls(attachment, 1767225599, 1767225601), [])

    def test_record_narration_stop_and_expiry(self):
        db = MemoryDb()
        now = 100
        ident = start(db, "line", "grant", 5, 7, now=now)
        record_call(db, "grant", "screen_elements", {}, "returned",
                    {"elements": [{"role": "button", "name": "Save", "value": "secret"}]}, now=now + 1)
        narrate(db, ident, 5, "I save the item.", at=now + 2, now=now + 2)
        item = stop(db, ident, now=now + 3)
        self.assertIsNone(item["calls"][0]["narration"])
        self.assertEqual(item["narration"][0]["text"], "I save the item.")
        self.assertNotIn("value", json.dumps(item["calls"][0]["observation"]))
        self.assertEqual(item["expires_at"], now + RETENTION)

    def test_observation_discards_tree_and_text(self):
        self.assertEqual(compact_observation({"elements": [{"role": "textbox", "name": "Title",
                                                              "text": "private", "children": [1]}]}),
                         {"targets": [{"role": "textbox", "name": "Title"}]})

    def test_read_observation_includes_only_returned_elements(self):
        from partyline.screen_tree import Snapshot
        from partyline.screen_tree_ids import IdSpace

        tree = Snapshot("s", 0, IdSpace())
        tree.add([{"id": "one", "control_type": "Button", "name": "Save"},
                  {"id": "two", "control_type": "Button", "name": "Cancel"}])
        answer = read_observation(tree, {"lines": tree.by_helper["one"] + " Button \"Save\""})
        self.assertEqual(answer, {"targets": [{"role": "button", "name": "Save"}]})

    def test_walkthrough_segments_align_only_to_the_active_line_recording(self):
        db = MemoryDb()
        start(db, "line", "grant", 5, 7, now=100)
        attached = walkthrough_narration(db, "line", 5, 101,
                                         [{"start": 1.5, "text": "I explain the action."}], now=104)
        self.assertTrue(attached)
        self.assertEqual(json.loads(db.row["narration"])[0]["at"], 102.5)


if __name__ == "__main__":
    unittest.main()
