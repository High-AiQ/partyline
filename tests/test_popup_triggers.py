"""Bench-style role-less triggers follow ARIA on both transports, including scoped ComboBox queries."""
import json
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from partyline.screen_tree import Snapshot
from partyline.screen_tree_answer import answer
from partyline_helper.cdp_dom_nodes import candidate
from partyline_helper.cdp_recipes import STATE, normalize
from partyline_helper.popup_triggers import controlled_types, uia_popup
from partyline_helper.uia_query import condition, snapshot as query_snapshot
from partyline_helper.uia_snapshot import snapshot
from tests.cdp_fakes import Fixture
from tests.test_cdp_hidden_files import dom
from tests.uia_dropdown_fakes import Chrome, Node


class FixtureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attributes = {}
        self.feed(Path("tests/fixtures/popup-triggers.html").read_text())

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            self.attributes[attrs["id"]] = attrs


def states():
    attributes = FixtureParser().attributes
    script = r'''
const attributes=ATTRIBUTES;
const elements=Object.fromEntries(Object.entries(attributes).map(([id,attrs])=>[id,{
 tagName:'DIV',tabIndex:attrs.tabindex===undefined?-1:Number(attrs.tabindex),
 closest:()=>null,matches:()=>false,getAttribute:k=>attrs[k]??null,
 getRootNode:()=>({getElementById:id=>elements[id]}),
 getBoundingClientRect:()=>({left:0,top:0,right:100,bottom:20,width:100,height:20}),
 ownerDocument:{activeElement:null}}]));
console.log(JSON.stringify(Object.fromEntries(Object.entries(elements).map(([id,e])=>[id,(STATE).call(e)]))));
'''.replace("ATTRIBUTES", json.dumps(attributes)).replace("STATE", STATE)
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class TriggerTests(unittest.TestCase):
    def test_uia_idrefs_share_one_target_index_for_many_triggers(self):
        targets = ["menu", "list", "foreign"]
        found = SimpleNamespace(Length=len(targets), GetElement=targets.__getitem__)
        root = SimpleNamespace(FindAllBuildCache=Mock(return_value=found))
        automation = Mock()
        def prop(node, name):
            if name == "ControllerFor":
                return None
            if name == "AutomationId":
                return node
            return 50008 if node == "list" else 50009
        provider = SimpleNamespace(prop=prop, automation=automation, request=Mock(return_value="cache"),
                                   root=lambda: root, same_window=lambda n: n != "foreign")
        for _ in range(100):
            self.assertEqual(["Menu"], controlled_types(provider, object(), "owns=menu"))
            self.assertEqual(["List"], controlled_types(provider, object(), "controls=list"))
        root.FindAllBuildCache.assert_called_once()
        self.assertEqual([], controlled_types(provider, object(), "controls=foreign"))

    def test_native_widget_roles_survive_popup_hints_on_both_transports(self):
        for tag, role, expected in (("BUTTON", "button", "Button"), ("A", "link", "Hyperlink"),
                                    ("INPUT", "textbox", "Edit"), ("DIV", "treeitem", "TreeItem")):
            item = normalize({"backendDOMNodeId": 2, "role": {"value": role}}, "id", None,
                             {"tag": tag, "popup": True, "expanded": "false"})
            self.assertEqual(expected, item["control_type"])
            self.assertEqual("true", item["popup"])
            props = uia_popup({"control_type": expected}, "expanded=false")
            self.assertEqual(expected, props["control_type"])
        app = Chrome()
        button = Node(41, 0, 50000, "Toggle section", ("Invoke",))
        button.props["AriaProperties"] = "expanded=false"
        props = app.properties(button)
        self.assertEqual("Button", props["control_type"])
        self.assertEqual("collapsed", props["expand_state"])
        props = uia_popup({"control_type": "Group", "aria_role": "button"}, "expanded=false")
        self.assertEqual("Group", props["control_type"])

    def test_dom_recipe_and_mapping_cover_has_popup_expanded_controls_and_owns(self):
        observed = states()
        attributes = FixtureParser().attributes
        for ident in ("haspopup", "expanded", "controls", "owns", "ordinary"):
            with self.subTest(ident=ident):
                state = observed[ident]
                self.assertEqual(ident != "ordinary", state["popup"])
                self.assertTrue(candidate("DIV", attributes[ident]))
                item = normalize({"backendDOMNodeId": 2, "role": {"value": "generic"}}, "i", None, state)
                self.assertEqual("Group" if ident == "ordinary" else "ComboBox", item["control_type"])
                self.assertNotIn("set_value", item["actions"])
                self.assertNotIn("select", item["actions"])
                self.assertIn("invoke", item["actions"])
        for hint in ("menu", "true", "listbox"):
            props = uia_popup({"control_type": "Custom"}, f"haspopup={hint}")
            self.assertEqual("ComboBox", props["control_type"])
        self.assertEqual("Group", uia_popup({"control_type": "Group"}, "haspopup=dialog")["control_type"])
        self.assertEqual("TreeItem", uia_popup({"control_type": "TreeItem"}, "expanded=true")["control_type"])

    def test_uia_native_mapping_and_query_do_not_filter_out_custom_trigger_types(self):
        app = Chrome()
        trigger = Node(40, 0, 50025, "Choices")
        trigger.props["AriaProperties"] = "haspopup=listbox;expanded=false"
        app.window.kids = [trigger]
        raw = snapshot(app, clock=lambda: 0)
        item = next(item for item in raw["elements"] if item["name"] == "Choices")
        self.assertEqual("ComboBox", item["control_type"])
        self.assertEqual("collapsed", item["expand_state"])
        trigger.props["AriaProperties"] = ""
        trigger.props["ControllerFor"] = SimpleNamespace(Length=1, GetElement=lambda _: app.popup)
        item = app.properties(trigger)
        self.assertEqual("ComboBox", item["control_type"])
        automation = Mock()
        condition(SimpleNamespace(automation=automation), {"control_type": "ComboBox"})
        automation.CreatePropertyCondition.assert_called_once_with(30003, 50003)
        self.assertEqual(4, automation.CreateOrCondition.call_count)
        self.assertEqual(["haspopup=", "expanded=", "controls=", "owns="],
                         [call.args[1] for call in automation.CreatePropertyConditionEx.call_args_list])
        raw = query_snapshot(app, {"control_type": "ComboBox"}, finder=lambda *_: [trigger])
        tree = Snapshot("s", 0)
        tree.add(raw["elements"])
        response = answer(tree, {}, {"control_type": "ComboBox"})
        self.assertEqual(1, response["total"])
        self.assertIn("Choices", response["lines"])


class CDPTriggerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ignored_roleless_dom_trigger_is_discovered_and_found_as_combobox(self):
        fixture = Fixture()
        self.addAsyncCleanup(fixture.close)
        fixture.socket.document = dom("#document", 1, [dom("DIV", 12, **{"aria-haspopup": "listbox"})])
        fixture.socket.nodes.append({"nodeId": "ignored", "backendDOMNodeId": 12, "ignored": True})
        fixture.socket.states[12] = {**states()["haspopup"], "short_text": "Choices"}
        raw = await fixture.read()
        tree = Snapshot("s", 0)
        tree.add(raw["elements"])
        response = answer(tree, {}, {"control_type": "ComboBox", "query": "Choices"})
        self.assertEqual(1, response["total"])
        self.assertIn("Choices", response["lines"])
