"""Transport caps apply to point deltas independently of the full tree size and DOM state."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from partyline.screen_point_changes import apply
from partyline.screen_tree import Snapshot
from partyline.screen_tree_ids import IdSpace
from partyline_helper.point_delta import MAX_BYTES, MAX_CHANGES, compact
from tests.test_point_feedback import rows


class CompactTests(unittest.TestCase):
    def test_large_cdp_observation_never_sends_whole_trees_or_dom_state(self):
        before = {"elements": [{"id": str(i), "name": "Row " + str(i), "control_type": "Button",
                                "dom": {"value": "x" * 1000}, "enabled": True} for i in range(6000)]}
        after = {"elements": [{**item, "enabled": False} for item in before["elements"]]}
        self.assertGreater(len(json.dumps({"before": before, "after": after})), 4 * 1024 * 1024)
        result = compact(before, after)
        self.assertLessEqual(len(json.dumps(result).encode()), MAX_BYTES)
        self.assertEqual(MAX_CHANGES, len(result["after"]["elements"]))
        self.assertEqual(6000 - MAX_CHANGES, result["more"])
        self.assertTrue(all("dom" not in item for item in result["after"]["elements"]))

    def test_unchanged_rows_are_omitted_and_disappeared_rows_are_explicit(self):
        result = compact(rows(True), rows())
        self.assertNotIn("root", {item["id"] for item in result["before"]["elements"]})
        self.assertEqual({"trigger", "list", "option"},
                         {item["id"] for item in result["before"]["elements"]})
        self.assertEqual(["trigger"], [item["id"] for item in result["after"]["elements"]])
        partial = rows()
        partial["truncated"] = True
        result = compact(rows(True), partial)
        self.assertNotIn("list", {item["id"] for item in result["before"]["elements"]})
        self.assertTrue(result["after"]["truncated"])

    def test_unicode_and_many_options_still_fit_and_keep_the_actual_option_count(self):
        before, after = rows(), rows(True)
        after["elements"] += [{"id": f"option{i}", "parent": "list", "control_type": "ListItem",
                               "name": "選" * 1000} for i in range(50)]
        result = compact(before, after)
        self.assertLessEqual(len(json.dumps(result).encode()), MAX_BYTES)
        self.assertEqual(51, result["options"]["list"])
        options = [item for item in result["after"]["elements"] if item.get("parent") == "list"]
        self.assertGreaterEqual(len(options), 5)
        self.assertIn("list", {item["id"] for item in result["after"]["elements"]})

    def test_byte_limit_also_caps_many_large_changed_labels(self):
        before = {"elements": [{"id": str(i), "name": "選" * 1000, "value": "選" * 600,
                                "control_type": "Edit", "enabled": True} for i in range(100)]}
        after = {"elements": [{**item, "enabled": False} for item in before["elements"]]}
        result = compact(before, after)
        self.assertLessEqual(len(json.dumps(result).encode()), MAX_BYTES)
        self.assertGreater(result["more"], 80)

    def test_large_option_samples_shrink_before_the_changed_container_is_dropped(self):
        items = [{"id": "list", "control_type": "List", "name": "𐍈" * 1000,
                  "value": "𐍈" * 600, "expand_state": "collapsed"}]
        items += [{"id": str(i), "parent": "list", "control_type": "ListItem",
                   "name": "𐍈" * 1000, "value": "𐍈" * 600} for i in range(5)]
        before = {"elements": items}
        after = {"elements": [{**item, "expand_state": "expanded"} if item["id"] == "list" else item
                              for item in items]}
        result = compact(before, after)
        self.assertLessEqual(len(json.dumps(result).encode()), MAX_BYTES)
        self.assertIn("list", {item["id"] for item in result["after"]["elements"]})
        self.assertLess(len(result["after"]["elements"]), 6)

    def test_compact_server_ids_reuse_known_ids_and_survive_the_next_full_read(self):
        space = IdSpace()
        previous = Snapshot("old", 0, space)
        previous.add(rows()["elements"])
        trigger = previous.by_helper["trigger"]
        hub = SimpleNamespace(spaces={"g": space}, snapshots={"g": previous}, clock=lambda: 0,
                              change_versions={}, remember=Mock())
        result = {"point_observation": compact(rows(), rows(True))}
        self.assertTrue(apply(hub, "g", result))
        tree = hub.remember.call_args.args[1]
        self.assertTrue(tree.scoped)
        self.assertEqual(trigger, tree.by_helper["trigger"])
        self.assertIn(f"[{trigger}]", result["changes"])
        self.assertEqual("option", tree.by_helper["option"])
        refreshed = Snapshot("new", 0, space)
        refreshed.add(rows(True)["elements"])
        # New scoped IDs are helper IDs, accepted by node_for even after a fresh ordinary capture.
        self.assertIn("option", refreshed.by_helper)
        self.assertEqual(trigger, refreshed.by_helper["trigger"])

    def test_changed_existing_list_also_names_unchanged_option_samples(self):
        before, after = rows(True), rows(True)
        before["elements"][2]["offscreen"] = True
        after["elements"][2]["offscreen"] = False
        hub = SimpleNamespace(spaces={}, snapshots={}, clock=lambda: 0, change_versions={}, remember=Mock())
        result = {"point_observation": compact(before, after)}
        apply(hub, "g", result)
        self.assertIn("changed: [list] List", result["changes"])
        self.assertIn('1 options: [option] ListItem "A"', result["changes"])

    def test_compact_tree_drops_proven_disappeared_action_ids_and_reports_more(self):
        previous = Snapshot("old", 0)
        previous.add(rows(True)["elements"])
        hub = SimpleNamespace(spaces={"g": previous.space}, snapshots={"g": previous}, clock=lambda: 0,
                              change_versions={}, remember=Mock())
        packet = compact(rows(True), rows())
        packet["more"] = 10
        result = {"point_observation": packet}
        apply(hub, "g", result)
        tree = hub.remember.call_args.args[1]
        self.assertNotIn(previous.by_helper["option"], tree.action_ids)
        self.assertIn("more: 10", result["changes"])
