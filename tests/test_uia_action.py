"""UIA action validation stays inside the latest selected tree."""
import unittest

from partyline_helper.uia_action import prepare
from partyline_helper.uia_identity import element_id
from tests.test_uia_snapshot import Provider


class ActionProvider(Provider):
    def properties(self, node):
        result = super().properties(node)
        result.update(enabled=self.nodes[node].get("enabled", True),
                      patterns=self.nodes[node].get("patterns", ["Value"]))
        return result

    def read_only(self, node):
        return self.nodes[node].get("readonly", False)


class UIAActionTests(unittest.TestCase):
    def setUp(self):
        self.tree = ActionProvider([{"rect": (0, 0, 10, 10), "children": [1]},
                                    {"rect": (0, 0, 5, 5)}])
        self.target = element_id(self.tree, 1, [0])

    def test_target_and_moved_or_foreign_element(self):
        self.assertEqual(1, prepare(self.tree, self.target, "set_value", "x")[0])
        self.tree.nodes[0]["children"] = []
        with self.assertRaisesRegex(ValueError, "stale"):
            prepare(self.tree, self.target, "set_value", "x")
        self.tree.nodes[0]["children"] = [1]
        self.tree.nodes[1]["same"] = False
        with self.assertRaisesRegex(ValueError, "stale"):
            prepare(self.tree, self.target, "set_value", "x")

    def test_refusals(self):
        for change, error in [({"enabled": False}, "disabled"), ({"patterns": []}, "support"),
                              ({"password": True}, "password"), ({"readonly": True}, "read-only")]:
            with self.subTest(change=change):
                self.tree.nodes[1].update(change)
                with self.assertRaisesRegex(ValueError, error):
                    prepare(self.tree, self.target, "set_value", "x")
                for key in change:
                    del self.tree.nodes[1][key]
        with self.assertRaisesRegex(ValueError, "requires"):
            prepare(self.tree, self.target, "set_value")

    def test_runtime_identity_and_path_are_both_required(self):
        self.tree.nodes.append({"rect": (0, 0, 3, 3)})
        self.tree.nodes[0]["children"] = [2, 1]
        with self.assertRaisesRegex(ValueError, "stale"):
            prepare(self.tree, self.target, "set_value", "x")
        self.assertNotEqual(self.target, element_id(self.tree, 1, [1]))
