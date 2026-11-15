"""UIA runtime-and-path IDs can change without the controls appearing or disappearing."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from partyline.screen_point_changes import apply
from partyline.screen_tree import Snapshot
from partyline_helper.point_delta import compact
from partyline_helper.uia_identity import element_id


def window(popup=False, value="before", remove_cancel=False):
    provider = SimpleNamespace(runtime_id=lambda node: [node])
    specs = [("root", 1, None, [], "Window", "Fixture", ""),
             ("trigger", 2, "root", [0], "ComboBox", "Choices", "trigger"),
             ("save", 3, "root", [1], "Button", "Save", ""),
             ("cancel", 4, "root", [2], "Button", "Cancel", ""),
             ("group", 5, "root", [3], "Group", "Actions", ""),
             ("edit", 6, "group", [3, 0], "Edit", "Name", "name"),
             ("save2", 7, "root", [4], "Button", "Save", ""),
             ("save3", 8, "root", [5], "Button", "Save", "")]
    shifted = []
    for key, runtime, parent, path, kind, name, auto in specs:
        if remove_cancel and key == "cancel":
            continue
        path = list(path)
        if path:
            path[0] += int(popup and path[0] >= 1) - int(remove_cancel and path[0] > 2)
        shifted.append((key, runtime, parent, path, kind, name, auto))
    if popup:
        shifted[2:2] = [("list", 20, "root", [1], "List", "Options", "options"),
                        ("option", 21, "list", [1, 0], "ListItem", "A", "")]
    ids = {key: element_id(provider, runtime, path) for key, runtime, _, path, *_ in shifted}
    elements = []
    for key, _, parent, _, kind, name, auto in shifted:
        item = {"id": ids[key], "parent": ids.get(parent), "control_type": kind,
                "name": name, "automation_id": auto, "enabled": True}
        if key == "trigger":
            item["expand_state"] = "expanded" if popup else "collapsed"
        if key == "edit":
            item["value"] = value
        elements.append(item)
    return {"elements": elements, "source": "uia"}, ids


class IdentityTests(unittest.TestCase):
    def render(self, before, after):
        previous = Snapshot("old", 0)
        previous.add(before["elements"])
        hub = SimpleNamespace(spaces={"g": previous.space}, snapshots={"g": previous}, clock=lambda: 0,
                              change_versions={}, remember=Mock())
        packet = compact(before, after)
        result = {"point_observation": packet}
        self.assertTrue(apply(hub, "g", result))
        return result["changes"], packet, previous, hub.remember.call_args.args[1]

    def test_popup_inserted_before_siblings_does_not_report_controls_vanished(self):
        before, old_ids = window()
        after, new_ids = window(popup=True)
        for key in ("save", "cancel", "group", "edit", "save2", "save3"):
            self.assertNotEqual(old_ids[key], new_ids[key])
        text, packet, _, _ = self.render(before, after)
        self.assertIn('List "Options"', text)
        self.assertIn('ListItem "A"', text)
        self.assertIn("collapsed→expanded", text)
        for label in ('Button "Save"', 'Button "Cancel"', 'Group "Actions"', 'Edit "Name"'):
            self.assertNotIn(label, text)
        self.assertNotIn("disappeared:", text)
        self.assertEqual({new_ids[key] for key in ("trigger", "list", "option")},
                         {item["id"] for item in packet["after"]["elements"]})
        self.assertEqual(old_ids["save"], before["elements"][2]["id"])  # diagnostics never mutate input IDs

    def test_shifted_subtree_state_change_uses_the_real_after_id_without_rebinding_old_actions(self):
        before, old_ids = window()
        after, new_ids = window(popup=True, value="after")
        text, packet, previous, tree = self.render(before, after)
        self.assertIn(f'changed: [{new_ids["edit"]}] Edit "Name" value before→after', text)
        self.assertNotIn("disappeared:", text)
        self.assertEqual(new_ids["edit"], tree.nodes[tree.by_helper[new_ids["edit"]]].helper)
        old_action_id = previous.by_helper[old_ids["edit"]]
        self.assertEqual(old_ids["edit"], tree.action_ids[old_action_id])
        self.assertNotIn(old_ids["edit"], {item["id"] for item in packet["before"]["elements"]})

    def test_a_genuine_disappearance_is_still_reported_amid_path_shifts(self):
        before, _ = window()
        after, _ = window(popup=True, remove_cancel=True)
        text, _, _, _ = self.render(before, after)
        gone = [line for line in text.splitlines() if line.startswith("disappeared:")]
        self.assertEqual(1, len(gone))
        self.assertIn('Button "Cancel"', gone[0])
        self.assertNotIn('Button "Save"', text)

    def test_shifted_option_samples_reference_the_current_parent_and_child_ids(self):
        before, old_ids = window()
        after, new_ids = window(popup=True)
        for raw, ids, offscreen in ((before, old_ids, True), (after, new_ids, False)):
            by_id = {item["id"]: item for item in raw["elements"]}
            by_id[ids["group"]].update(control_type="List", offscreen=offscreen)
            by_id[ids["edit"]]["control_type"] = "ListItem"
        text, packet, _, _ = self.render(before, after)
        self.assertIn(f'changed: [{new_ids["group"]}] List "Actions"', text)
        self.assertIn(f'1 options: [{new_ids["edit"]}] ListItem "Name"', text)
        child = next(item for item in packet["before"]["elements"] if item["id"] == new_ids["edit"])
        self.assertEqual(new_ids["group"], child["parent"])

    def test_provider_identity_changes_remain_appearances_and_disappearances(self):
        before = {"elements": [{"id": "old", "provider_identity": "old", "control_type": "Button",
                                "name": "Save"}]}
        after = {"elements": [{"id": "new", "provider_identity": "new", "control_type": "Button",
                               "name": "Save"}]}
        text, _, _, _ = self.render(before, after)
        self.assertIn("appeared:", text)
        self.assertIn("disappeared:", text)

    def test_automation_id_and_duplicate_ordinal_pair_the_correct_controls(self):
        for autos in (("first", "second"), ("", "")):
            with self.subTest(autos=autos):
                old = [{"id": f"old{i}", "control_type": "Button", "name": "Save",
                        "automation_id": auto, "enabled": i == 1} for i, auto in enumerate(autos)]
                new = [{**item, "id": f"new{i}", "enabled": False} for i, item in enumerate(old)]
                if autos[0]:
                    new.reverse()  # AutomationId takes precedence over ordering when it distinguishes names
                text, packet, _, _ = self.render({"elements": old}, {"elements": new})
                self.assertIn("changed: [new1]", text)
                self.assertNotIn("appeared:", text)
                self.assertNotIn("disappeared:", text)
                self.assertEqual(["new1"], [item["id"] for item in packet["after"]["elements"]])
