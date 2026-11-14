"""An explicit override for UIA's disabled report retains evidence and never synthesizes input."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from partyline.screen_element_actions import ElementAction
from partyline.screen_tree import Snapshot
from partyline.screen_tree_answer import answer
from partyline_helper.uia_force import forced_call
from partyline_helper.uia_patterns import ActionRefused
from partyline_helper.uia_snapshot import snapshot
from tests.test_uia_dropdown import run
from tests.uia_dropdown_fakes import Chrome, Node


class DisabledChrome(Chrome):
    def __init__(self, fallback=False):
        super().__init__()
        self.link = Node(30, 0, 50005, "Manage A+ Content", ("Invoke", "Value", "LegacyIAccessible"),
                         value="https://kdp.amazon.com/aplus/content-manager")
        self.link.props.update(IsEnabled=False, AriaProperties="disabled=true")
        self.window.kids.append(self.link)
        self.fallback = fallback

    def navigate(self):
        self.link.props["HasKeyboardFocus"] = True
        self.window.props["Name"] = "A+ Content Manager"

    def action_call(self, node, action, arg):
        if node is not self.link:
            return super().action_call(node, action, arg)
        def invoke():
            self.calls.append((node.ident, action, arg))
            if self.fallback:
                raise RuntimeError("UIA provider refused Invoke")
            self.navigate()
        return invoke

    def pattern(self, node, ident, name):
        assert (ident, name) == (10018, "LegacyIAccessible")
        return SimpleNamespace(DoDefaultAction=self.navigate)


class DisabledTests(unittest.TestCase):
    def test_disabled_line_includes_raw_aria_and_ancestor_evidence_without_extra_reads(self):
        app = DisabledChrome()
        for inherited in (False, True):
            app.window.props["IsEnabled"] = not inherited
            tree = Snapshot("s", 0)
            tree.add(snapshot(app, clock=lambda: 0)["elements"])
            reply = answer(tree, {}, {"query": "Manage A+ Content"})
            self.assertIn("IsEnabled=false", reply["lines"])
            self.assertIn("aria:disabled=true", reply["lines"])
            root = tree.order[0]
            self.assertIn("ancestor=" + root if inherited else ";self;", reply["lines"])

    def test_nonforced_refusal_explains_when_to_use_force(self):
        app = DisabledChrome()
        result = run(app, app.link, "invoke")
        self.assertEqual("failed", result["status"])
        self.assertIn("force=true", result["error"])
        self.assertIn("person confirms", result["error"])
        self.assertEqual([], app.calls)

    def test_force_tries_invoke_and_legacy_fallback_and_reports_observations(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback):
                app = DisabledChrome(fallback=fallback)
                result = run(app, app.link, "invoke", force=True)
                self.assertEqual("completed", result["status"])
                self.assertTrue(result["reported_disabled"])
                self.assertTrue(result["focus_changed"])
                self.assertTrue(result["focused_after"])
                self.assertTrue(result["window_title_changed"])
                self.assertEqual("A+ Content Manager", result["window_title_after"])
                self.assertFalse(result["value_changed"])
                self.assertEqual("LegacyIAccessible.DoDefaultAction" if fallback else "pattern",
                                 result["action_method"])
                self.assertEqual(["invoke"], [call[1] for call in app.calls])

    def test_force_expand_can_fall_back_when_pattern_binding_is_refused(self):
        app = DisabledChrome()
        app.action_call = Mock(side_effect=RuntimeError("provider refused pattern binding"))
        result = run(app, app.link, "expand", force=True)
        self.assertEqual("completed", result["status"])
        self.assertEqual("LegacyIAccessible.DoDefaultAction", result["action_method"])
        self.assertTrue(result["window_title_changed"])

    def test_missing_invoke_can_use_legacy_but_other_actions_and_revocation_still_refuse(self):
        app = DisabledChrome(fallback=True)
        app.link.patterns = ("LegacyIAccessible",)
        self.assertEqual("completed", run(app, app.link, "invoke", force=True)["status"])
        self.assertIn("force is supported only", run(app, app.combo, "collapse", force=True)["error"])
        with self.assertRaisesRegex(ValueError, "force is supported only"):
            ElementAction(element_id="x", action="set_value", force=True, value="x").parameters()
        app.default_action = Mock()
        check = Mock(side_effect=[None, ActionRefused("revoked")])
        call = forced_call(app, app.link, "invoke", {}, app.properties(app.link), check)
        with self.assertRaisesRegex(ActionRefused, "revoked"):
            call()
        app.default_action.assert_not_called()
