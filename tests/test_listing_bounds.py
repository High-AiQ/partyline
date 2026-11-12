"""Captain listings stop at a page of live lines and say how to read the rest."""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from partyline.db import Db
from partyline.mcp import tools_tasks
from partyline.mcp.captain_ops import execute
from partyline.orchestrator_store import tasks
from partyline.process_overview import process_overview
from partyline.staffing import LINES_LIMIT, staffing_report

RETIRED = 14


class Client:
    home = "root"

    def __init__(self, db):
        self.db, self.requests = db, []

    def request(self, method, path, body=None, **_):
        self.requests.append(path)
        return []


class ListingBoundsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "x.db"))
        self.addCleanup(self.db.close)
        db = self.db
        db.create_conversation("root", "root")
        db.create_conversation("live1", "live", "manager_tree")
        db._exec("UPDATE conversations SET parent_id='root', accepted_sha='a' WHERE id='live1'")
        for index in range(RETIRED):
            conv = f"old{index}"
            db.create_conversation(conv, conv, "manager_tree")
            db._exec("UPDATE conversations SET parent_id='root', accepted_sha=?, archived_at=? WHERE id=?",
                     (f"sha{index:02d}", 1000 + index, conv))
            db._exec("INSERT INTO task_reviews(conv_id,root_id,implementer_id,implementer_preset,"
                     "reviewer_id,policy,tag,created_at,mode,status,what,location,findings) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (conv, "root", f"i{index}", "p", f"r{index}", "adversarial", conv, 1000 + index,
                      "full", "done", "w" * 500, "l", "f" * 500))
        self.runtime = SimpleNamespace(db=db, live={}, memory_usage={}, presence=None)

    def test_staffing_lists_live_lines_first_and_pages_the_retired(self):
        first = staffing_report(self.db, "root")
        self.assertEqual(len(first["lines"]), LINES_LIMIT)
        self.assertEqual(first["lines"][0]["id"], "live1")
        self.assertEqual(first["lines_total"], RETIRED + 1)
        self.assertEqual(first["lines_next_offset"], LINES_LIMIT)
        rest = staffing_report(self.db, "root", lines_offset=first["lines_next_offset"])
        self.assertEqual(len(rest["lines"]), RETIRED + 1 - LINES_LIMIT)
        self.assertIsNone(rest["lines_next_offset"])
        self.assertTrue(all(row["retired"] for row in rest["lines"]))

    def test_the_staffing_op_passes_the_page_through(self):
        client = Client(self.db)
        state = {"kind": "machine", "role": "lead", "is_lead": True, "actions": ["assign"]}
        execute(client, "staffing", {"conv_id": "root", "limit": 3, "offset": 6}, state)
        self.assertTrue(client.requests[-1].endswith("/staffing?lines_limit=3&lines_offset=6"))

    def test_process_overview_leaves_out_retired_lines_unless_asked(self):
        self.assertEqual([line.id for line in process_overview(
            self.runtime, "root", include_retired=False).lines], ["root", "live1"])
        everything = process_overview(self.runtime, "root", limit=5)
        self.assertEqual(len(everything.lines), 5)
        self.assertEqual((everything.lines_total, everything.next_offset), (RETIRED + 2, 5))

    def test_tasks_pages_retired_tasks_newest_first_and_says_what_to_pass(self):
        class Tasks(Client):
            def request(client, method, path, body=None, **_):
                client.requests.append(path)
                if "retired_only" in path:
                    limit = int(path.split("limit=")[1].split("&")[0])
                    offset = int(path.split("offset=")[1])
                    return [json.loads(json.dumps(row, default=str))
                            for row in tasks(self.db, "root", only_retired=(limit, offset))]
                return []

        client = Tasks(self.db)
        state = {"actions": ["tasks"]}
        board = tools_tasks.call(client, "tasks", {"include_retired": True, "limit": 4}, state)
        self.assertEqual([row.get("conv_id") for row in board[:4]], ["old13", "old12", "old11", "old10"])
        self.assertEqual(board[-1], {"retired_more": "tasks(include_retired=true, offset=4)"})
        last = tools_tasks.call(client, "tasks", {"include_retired": True, "offset": 12}, state)
        self.assertEqual([row["conv_id"] for row in last], ["old1", "old0"])
        self.assertEqual(tools_tasks.call(client, "tasks", {}, state), [])
        self.assertNotIn("retired_only", client.requests[-1])

    def test_a_retired_row_drops_bookkeeping_and_cuts_prose_short(self):
        row = tasks(self.db, "root", only_retired=(1, 0))[0]
        item = tools_tasks._board([row], retired=True)[0]
        for key in ("root_id", "implementer_id", "stall_stage"):
            self.assertNotIn(key, item)
        self.assertLessEqual(len(item["what"]), tools_tasks.RETIRED_TEXT + 1)
        self.assertEqual((item["conv_id"], item["status"]), ("old13", "done"))


if __name__ == "__main__":
    unittest.main()
