"""Owned Chrome popup scope, genuine selection, effect reporting and rooted after reads."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.screen_element_actions import ElementAction, Then, element_action
from partyline.screen_elements import ElementsHub
from partyline.screen_tree_answer import size
from partyline_helper.uia_action import prepare
from partyline_helper.uia_action_worker import audit, run_action
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.uia_identity import element_id
from partyline_helper.uia_patterns import ActionRefused, check_argument
from partyline_helper.uia_options import containers
from partyline_helper.uia_popups import PopupEvents, sender_in_scope
from partyline_helper.uia_selection import effect, option
from partyline_helper.uia_snapshot import snapshot
from tests.uia_dropdown_fakes import Chrome, Node, SiblingChrome


def run(app, node, action, **fields):
    grant = {"hwnd": 1, "pid": 10}
    gate = DispatchGate()
    generation = gate.grant()
    access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
    tree = snapshot(app, clock=lambda: 0)
    path = next(path for ident, path in tree["paths"].items()
                if ident == element_id(app, node, path))
    return run_action(access, grant, generation,
                      {"element_id": element_id(app, node, path), "action": action, **fields},
                      factory=lambda _: app)


class DropdownTests(unittest.TestCase):
    def test_expand_reveals_only_visible_owned_popups_and_collapse_removes_them(self):
        app = Chrome()
        self.assertEqual(["Chrome dropdown fixture", "Choose a marketplace…"],
                         [item["name"] for item in snapshot(app, clock=lambda: 0)["elements"]])
        self.assertEqual("changed", run(app, app.combo, "expand")["effect"])
        app.refresh()
        opened = snapshot(app, clock=lambda: 0)
        self.assertEqual(["Chrome dropdown fixture", "Choose a marketplace…", "popup: List",
                          "Amazon.com", "Amazon.co.uk"], [item["name"] for item in opened["elements"]])
        option_id = next(item["id"] for item in opened["elements"] if item["name"] == "Amazon.co.uk")
        prepare(app, option_id, "select", path=opened["paths"][option_id])
        self.assertEqual("changed", run(app, app.combo, "collapse")["effect"])
        # Even a retained provider cache must reject the now-hidden popup root.
        self.assertEqual(2, len(snapshot(app, clock=lambda: 0)["elements"]))
        with self.assertRaisesRegex(ActionRefused, "stale"):
            prepare(app, option_id, "select", path=opened["paths"][option_id])

    def test_legacy_fallback_does_not_retain_ordinary_unnamed_wrappers(self):
        app = Chrome()
        wrapper = Node(50, 0, 50033, "", ("LegacyIAccessible",))
        wrapper.kids = [app.combo]
        app.window.kids = [wrapper]
        self.assertEqual(["Chrome dropdown fixture", "Choose a marketplace…"],
                         [item["name"] for item in snapshot(app, clock=lambda: 0)["elements"]])

    def test_live_sibling_list_is_found_despite_stale_expand_state(self):
        app = SiblingChrome()
        expanded = run(app, app.combo, "expand")
        self.assertEqual(2, expanded["options_found"])
        self.assertTrue(expanded["options_appeared"])
        self.assertEqual("collapsed", expanded["element"]["reported_expand_state"])
        self.assertNotIn("expand_state", expanded["element"])
        # A second expand finds the already-open List without claiming it newly appeared.
        self.assertFalse(run(app, app.combo, "expand")["options_appeared"])
        result = run(app, app.combo, "select", value="Amazon.co.uk")
        self.assertTrue(result["value_changed"])
        self.assertEqual("Amazon.co.uk", result["selected_option"])
        self.assertEqual([app.combo], app.group.kids)
        self.assertEqual([], app.popups())

    def test_owner_chains_reject_unrelated_foreign_hidden_and_cyclic_windows(self):
        app = Chrome()
        scope = app.scope
        self.assertTrue(scope.owns(4))  # popup owned by another popup owned by the grant
        for hwnd in (3, 5, 6, 7, 999):
            self.assertFalse(scope.owns(hwnd), hwnd)
        self.assertFalse(scope.accepts(2))
        self.assertFalse(app.same_window(app.other))
        app.user32.visible.add(2)
        app.user32.visible.add(4)
        self.assertEqual([2, 4], scope.popups())
        snapshot(app, clock=lambda: 0)  # records that handleless option nodes came from a popup
        app.second.props["ProcessId"] = 20
        self.assertFalse(app.same_window(app.second))
        app.user32.pids[8] = 20
        app.user32.GetAncestor = lambda hwnd, flag: 1 if hwnd == 8 else hwnd
        self.assertFalse(scope.accepts(8))  # cross-process child HWND beneath the granted root

    def test_granted_subtree_preserves_hosted_process_content_but_popups_do_not(self):
        app = Chrome()
        app.combo.props["ProcessId"] = 20  # WebView-style handleless hosted content
        hosted = Node(80, 8, 50000, "Hosted button", ("Invoke",))
        hosted.props["ProcessId"] = 20
        app.user32.pids[8] = 20
        original = app.user32.GetAncestor
        app.user32.GetAncestor = lambda hwnd, flag: 1 if hwnd == 8 else original(hwnd, flag)
        app.window.kids.append(hosted)
        tree = snapshot(app, clock=lambda: 0)
        self.assertEqual(3, len(tree["elements"]))
        for node, action in ((app.combo, "set_value"), (hosted, "invoke")):
            self.assertTrue(app.same_window(node))
            self.assertEqual("completed", run(app, node, action, **(
                {"value": "Amazon.co.uk"} if action == "set_value" else {}))["status"])
        self.assertFalse(app.same_window(app.other))
        app.user32.visible.add(2)
        app.refresh()
        app.popup.props["ProcessId"] = 20
        self.assertEqual([], app.popups())  # the hosted-process exception does not widen popup scope

    def test_popup_already_in_main_uia_tree_still_enforces_descendant_process_scope(self):
        app = Chrome()
        app.user32.visible.add(2)
        app.window.kids.append(app.popup)
        app.popup_roots = []  # discovered by the native UIA tree, not by the appended root walk
        app.second.props["ProcessId"] = 20
        names = [item["name"] for item in snapshot(app, clock=lambda: 0)["elements"]]
        self.assertIn("Amazon.com", names)
        self.assertNotIn("Amazon.co.uk", names)

    def test_nearby_search_never_climbs_past_the_granted_or_popup_root(self):
        app = Chrome()
        parent = app.parent
        def scoped_parent(node):
            if node in (app.window, app.popup):
                raise AssertionError("tried to walk into the desktop")
            return parent(node)
        app.parent = scoped_parent
        result = run(app, app.combo, "select", value="Amazon.co.uk")
        self.assertEqual("completed", result["status"])
        run(app, app.combo, "expand")
        app.refresh()
        self.assertEqual([app.popup], containers(app, app.first))

    def test_collapse_failure_retains_selection_and_does_not_mask_the_original_error(self):
        for name in ("Amazon.co.uk", "missing"):
            app = Chrome()
            action_call = app.action_call
            def bind(node, action, arg, original=action_call):
                if action == "collapse":
                    raise RuntimeError("popup already destroyed")
                return original(node, action, arg)
            app.action_call = bind
            result = run(app, app.combo, "select", value=name)
            if name == "missing":
                self.assertEqual("failed", result["status"])
                self.assertIn("option not found", result["error"])
            else:
                self.assertEqual("completed", result["status"])
                self.assertTrue(result["collapse_failed"])
                self.assertTrue(result["value_changed"])
                self.assertEqual("Amazon.co.uk", result["selected_option"])
                self.assertEqual("Amazon.co.uk", app.combo.state["value"])

    def test_selection_survives_target_destruction_before_value_reread_and_collapse(self):
        app = Chrome()
        original_properties, action_call = app.properties, app.action_call
        destroyed = [False]
        def properties(node):
            if destroyed[0] and node in (app.combo, app.first, app.second):
                raise RuntimeError("element was destroyed by navigation")
            return original_properties(node)
        def bind(node, action, arg):
            if destroyed[0] and action == "collapse":
                raise RuntimeError("ComboBox destroyed")
            original = action_call(node, action, arg)
            def call():
                original()
                if action == "select":
                    destroyed[0] = True
            return call
        app.properties, app.action_call = properties, bind
        result = run(app, app.combo, "select", value="Amazon.co.uk")
        self.assertEqual("completed", result["status"])
        self.assertEqual("Amazon.co.uk", result["selected_option"])
        self.assertTrue(result["collapse_failed"])
        self.assertIsNone(result["value_changed"])
        self.assertEqual("unknown", result["effect"])
        self.assertIn("state_unavailable", result)

    def test_unchanged_and_changed_pattern_states(self):
        app = Chrome()
        app.noop = True
        for action, fields in (("expand", {}), ("collapse", {}),
                               ("set_value", {"value": "Amazon.com"})):
            result = run(app, app.combo, action, **fields)
            self.assertEqual(("completed", "none"), (result["status"], result["effect"]))
            self.assertIn("select", result["hint"])
        for action, key, before, after in (("toggle", "toggle", 0, 1),
                                            ("select", "selected", False, True),
                                            ("set_value", "value", "a", "b")):
            self.assertEqual("changed", effect(action, {key: before}, {key: after})["effect"])
            self.assertEqual("none", effect(action, {key: before}, {key: before})["effect"])
        self.assertEqual("unknown", effect("expand", {}, {})["effect"])
        self.assertEqual({}, effect("invoke", {}, {}))

    def test_select_by_name_and_direct_option_use_selection_item(self):
        app = Chrome()
        result = run(app, app.combo, "select", value="Amazon.co.uk")
        self.assertEqual("completed", result["status"])
        self.assertEqual("Amazon.co.uk", result["selected_option"])
        self.assertTrue(result["value_changed"])
        self.assertEqual("changed", result["effect"])
        self.assertEqual("collapsed", result["element"]["expand_state"])
        self.assertEqual(["expand", "select", "collapse"], [call[1] for call in app.calls])
        run(app, app.combo, "expand")
        app.refresh()
        result = run(app, app.first, "select")
        self.assertEqual("changed", result["effect"])
        self.assertEqual("Amazon.com", app.combo.state["value"])
        self.assertEqual("none", run(app, app.first, "select")["effect"])

    def test_unchanged_named_selection_and_dismissed_popup(self):
        app = Chrome()
        result = run(app, app.combo, "select", value="Amazon.com")
        self.assertFalse(result["value_changed"])
        self.assertEqual("none", result["effect"])
        app.destroy_on_select = True
        result = run(app, app.combo, "select", value="Amazon.co.uk")
        self.assertEqual("changed", result["effect"])
        self.assertEqual("collapsed", result["element"]["expand_state"])

    def test_missing_disabled_ambiguous_and_invalid_names_fail_clearly(self):
        for name, setup, error in (
                ("missing", lambda app: None, "option not found"),
                ("Amazon.co.uk", lambda app: app.second.props.update(IsEnabled=False), "disabled"),
                ("Amazon.com", lambda app: app.second.props.update(Name="Amazon.com"), "ambiguous")):
            app = Chrome()
            setup(app)
            result = run(app, app.combo, "select", value=name)
            self.assertEqual("failed", result["status"])
            self.assertIn(error, result["error"])
            self.assertEqual("collapsed", app.combo.state["expand_state"])
        app = Chrome()
        self.assertIn("requires value", run(app, app.combo, "select")["error"])
        with self.assertRaisesRegex(ActionRefused, "nonempty"):
            check_argument("select", "")
        run(app, app.combo, "expand")
        app.refresh()
        self.assertIn("requires a ComboBox", run(app, app.first, "select", value="Amazon.com")["error"])
        self.assertEqual("Amazon.com", ElementAction(element_id="x", action="select",
                                                     value="Amazon.com").parameters()["value"])

    def test_named_selection_is_audited_without_treating_text_as_parameter_dict(self):
        sink = Mock()
        audit(SimpleNamespace(tools=SimpleNamespace(audit=sink)), {},
              {"action": "select", "value": "Amazon.co.uk"}, {}, {"status": "completed"})
        self.assertIn("Amazon.co.uk", sink.append.call_args.args[-1])

    def test_popup_events_and_handleless_uia_events_stay_in_scope(self):
        app, changes = Chrome(), []
        events = PopupEvents(app.scope, lambda: changes.append("change"))
        events.event(3, 0)
        events.event(5, 0)
        events.event(2, -4)
        events.event(0, 0)
        self.assertEqual([], changes)
        app.user32.visible.add(2)
        events.event(2, 0)
        app.user32.visible.discard(2)
        app.user32.owners.pop(2)
        events.event(2, 0)  # destroyed sender no longer has Win32 ownership
        self.assertEqual(["change", "change"], changes)
        app.user32.owners[2] = 1
        app.user32.visible.add(2)
        parents = {app.second: app.popup}
        app.walker = SimpleNamespace(GetParentElement=lambda node: parents.get(node))
        self.assertTrue(sender_in_scope(app, app.second))
        self.assertFalse(sender_in_scope(app, app.other))
        app.second.props["ProcessId"] = 20
        self.assertFalse(sender_in_scope(app, app.second))
        self.assertFalse(sender_in_scope(app, object()))
        self.assertIsNone(option(app, [app.other], "Amazon.com"))


class DropdownTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = Chrome()
        self.grant = {"id": "g", "hwnd": 1, "pid": 10, "title": "Chrome dropdown fixture",
                      "process": "chrome.exe"}
        self.principal = SimpleNamespace(name="agent", kind="machine", attachment_id="a")
        self.elements = ElementsHub(SimpleNamespace(devices={}), clock=lambda: 0)
        self.elements.settle = AsyncMock()
        self.gate = DispatchGate()
        self.generation = self.gate.grant()
        self.access = SimpleNamespace(gate=self.gate, list_windows=lambda: [self.grant])

        async def exchange(principal, grant, device, kind, **fields):
            if kind == "read_window_elements":
                self.app.refresh()
                result = snapshot(self.app, clock=lambda: 0)
                result["snapshot_id"] = "00000000-0000-0000-0000-000000000000"
                self.access.paths = result["paths"]
                return result
            return run_action(self.access, grant, self.generation, fields, factory=lambda _: self.app)

        self.elements.exchange = exchange
        self.hub = SimpleNamespace(elements=self.elements,
                                   window_grants=SimpleNamespace(spend=lambda grant: None))
        for module, target, result in (
                ("screen_elements", "resolve_window", (self.grant, {})),
                ("screen_elements", "require_window", None),
                ("screen_element_actions", "resolve_window", (self.grant, {})),
                ("screen_element_actions", "request_principal", self.principal),
                ("screen_element_actions", "deny_unless", None)):
            patcher = patch(f"partyline.{module}.{target}", return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def act(self, action, then=None, **fields):
        ident = next(key for key, node in self.elements.snapshots["g"].nodes.items()
                     if node.type == "ComboBox")
        return await element_action(SimpleNamespace(db=None), self.hub, "line",
                                    ElementAction(element_id=ident, action=action, then=then, **fields), None)

    async def test_then_root_is_kept_even_when_filters_match_no_children(self):
        await self.elements.read(self.principal)
        ident = next(key for key, node in self.elements.snapshots["g"].nodes.items()
                     if node.type == "ComboBox")
        result = await self.act("set_value", value="Amazon.com", then=Then(root=ident, query="absent"))
        self.assertEqual(1, result["after"]["total"])
        self.assertIn(ident, result["after"]["lines"])

    async def test_then_root_includes_leaf_and_tokens_remain_compact(self):
        closed = await self.elements.read(self.principal)
        filtered = await self.elements.read(self.principal, options={"query": "marketplace"})
        plain = await self.act("set_value", value="Amazon.com")
        await self.elements.read(self.principal)
        ident = next(key for key, node in self.elements.snapshots["g"].nodes.items()
                     if node.type == "ComboBox")
        rooted = await self.act("expand", then=Then(root=ident, depth=2))
        self.assertGreaterEqual(rooted["after"]["total"], 1)
        self.assertIn("ComboBox", rooted["after"]["lines"])
        opened = await self.elements.read(self.principal, options={"control_type": "ListItem"})
        self.assertIn("Amazon.co.uk", opened["lines"])
        opened_summary = await self.elements.read(self.principal)
        await self.act("collapse")
        again = await self.elements.read(self.principal)
        self.assertEqual(size(closed), size(again))  # a closed popup adds no bytes to subsequent reads
        self.assertLess(size(filtered), size(closed))
        self.assertLess(size(rooted), 4096)
        self.metrics = {key: (size(value), size(value) / 4) for key, value in (
            ("no query", closed), ("filtered", filtered), ("action", plain),
            ("action then root", rooted), ("popup options", opened), ("open summary", opened_summary))}
