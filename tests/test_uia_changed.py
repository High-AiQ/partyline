"""A walk resumed after the page changed names it and never repeats or mislabels elements."""
import unittest

from partyline_helper.uia_snapshot import BUDGET, snapshot


class Tree:
    """W[A, B[B1, B2, B3], C[C1, C2]] with stable runtime ids, so a page can change between parts."""

    def __init__(self):
        self.kids = {"W": ["A", "B", "C"], "A": [], "B": ["B1", "B2", "B3"], "B1": [], "B2": [], "B3": [],
                     "C": ["C1", "C2"], "C1": [], "C2": []}

    def root(self):
        return "W"

    def runtime_id(self, node):
        return [node]

    def same_window(self, node):
        return True

    def password(self, node):
        return False

    def current(self):
        return True

    def bounds(self, node):
        return 0, 0, 1, 1

    def children(self, node):
        return list(self.kids[node])

    def properties(self, node):
        return {"control_type": "Button", "name": node, "automation_id": "", "enabled": True,
                "focused": False, "offscreen": False, "patterns": ["Invoke"]}


def names(parts):
    return [item["name"] for part in parts for item in part["elements"]]


class ChangedPageTests(unittest.TestCase):
    def first(self, tree):
        part = snapshot(tree, limit=3)  # W, A, B
        self.assertEqual(["W", "A", "B"], names([part]))
        return part

    def test_an_unchanged_page_resumes_cleanly(self):
        tree = Tree()
        first = self.first(tree)
        second = snapshot(tree, state=first["state"])
        self.assertEqual(["B1", "B2", "B3", "C", "C1", "C2"], names([second]))
        self.assertNotIn("changed", second)

    def test_a_banner_inserted_at_the_top_is_reported_not_replayed(self):
        tree = Tree()
        first = self.first(tree)
        tree.kids["W"].insert(0, "Banner")
        tree.kids["Banner"] = []
        second = snapshot(tree, state=first["state"])
        self.assertTrue(second["changed"])
        self.assertEqual([], names([second]))  # nothing is read from the shifted paths
        self.assertFalse(second["truncated"])

    def test_a_change_inside_one_section_keeps_the_others(self):
        tree = Tree()
        first = self.first(tree)
        tree.kids["B"].insert(0, "B0")
        tree.kids["B0"] = []
        second = snapshot(tree, state=first["state"])
        self.assertTrue(second["changed"])
        self.assertEqual(["C", "C1", "C2"], names([second]))

    def test_a_list_that_slides_by_one_is_noticed_though_its_count_is_the_same(self):
        tree = Tree()
        tree.kids["W"] = ["A", "B", "C", "D"]
        tree.kids["D"] = []
        part = snapshot(tree, limit=3)  # W, A, B read; C and D remain
        self.assertEqual(["W", "A", "B"], names([part]))
        tree.kids["W"] = ["B", "C", "D", "E"]  # A scrolled out, E scrolled in
        tree.kids["E"] = []
        second = snapshot(tree, state=part["state"])
        self.assertTrue(second["changed"])
        self.assertEqual([], names([second]))  # C is not read from D's position

    def test_state_ids_chain_across_three_parts(self):
        tree = Tree()
        first = snapshot(tree, limit=2)
        second = snapshot(tree, state=first["state"], limit=2)
        third = snapshot(tree, state=second["state"])
        self.assertEqual(["W", "A", "B", "B1", "B2", "B3", "C", "C1", "C2"], names([first, second, third]))
        self.assertTrue(not any("changed" in part for part in (first, second, third)))

    def test_the_root_fetch_does_not_use_up_the_part_budget(self):
        tree = Tree()
        clock = [0.0]
        original = tree.root

        def slow_root():
            clock[0] += BUDGET * 10  # a whole-window prefetch
            return original()

        tree.root = slow_root
        part = snapshot(tree, clock=lambda: clock[0])
        self.assertEqual(9, len(part["elements"]))
        self.assertFalse(part["truncated"])
