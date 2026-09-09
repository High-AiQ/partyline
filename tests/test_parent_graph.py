"""Concurrent graph changes cannot pass two independent cycle checks."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from partyline.db import Db
from partyline.hierarchy import HierarchyError, set_parent


class ParentGraphTest(unittest.TestCase):
    def test_opposite_links_cannot_both_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(directory + "/graph.db")
            try:
                db.create_conversation("a", "A")
                db.create_conversation("b", "B")
                def link(pair):
                    try:
                        set_parent(db, *pair)
                        return 200
                    except HierarchyError as exc:
                        return exc.status_code
                with ThreadPoolExecutor(max_workers=2) as pool:
                    statuses = list(pool.map(link, [("a", "b"), ("b", "a")]))
                self.assertEqual(sorted(statuses), [200, 400])
                self.assertFalse(db.get_conversation("a")["parent_id"] and
                                 db.get_conversation("b")["parent_id"])
            finally:
                db.close()
