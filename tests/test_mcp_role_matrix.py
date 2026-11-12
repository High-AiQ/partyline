"""Nothing a role may call became impossible when the catalog stopped listing every tool.

`tests/fixtures/mcp_role_matrix.json` was frozen from the full catalog before the split: for each
role, the capability state and every tool name it could call. Each of those names must still
be reachable: listed itself, or run through the one door the listing names for it.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.mcp import catalog, tools_captain
from partyline.mcp.client import ApiError

MATRIX = json.loads((Path(__file__).parent / "fixtures" / "mcp_role_matrix.json").read_text())
HIDDEN_FROM_EVERYONE = {"blender_exec", "render_check", "upload_3d_model", "offer_handover"}


class Recorder:
    home = "home"


def run(state, name, args):
    """Dispatch with every tool module and captain operation stubbed to report what ran."""
    stubs = {module: (lambda client, tool, tool_args, tool_state, _m=module.__name__:
                      (_m.rsplit(".", 1)[-1], tool))
             for module in catalog.DISPATCH}
    with patch.object(catalog, "validate_arguments", lambda *args: None), \
            patch.multiple(tools_captain, validate=lambda op, operation_args: operation_args), \
            patch.object(tools_captain.captain_ops, "execute",
                         lambda client, op, operation_args, op_state: ("captain_ops", op)):
        for module, stub in stubs.items():
            if module is not tools_captain:
                patch.object(module, "call", stub).start()
        try:
            return catalog.dispatch(Recorder(), name, args, state)
        finally:
            patch.stopall()


class RoleMatrixTest(unittest.TestCase):
    def test_every_tool_a_role_may_call_is_still_reachable(self):
        for role, entry in MATRIX.items():
            state = entry["state"]
            shown = {tool["name"]: tool for tool in catalog.listed(state)}
            with self.subTest(role=role):
                for name in entry["callable"]:
                    way = catalog.door(name, state)
                    if way is None:
                        self.assertIn(name, shown, f"{role}: {name} is neither listed nor behind a door")
                        if name != catalog.CAPTAIN:  # the door itself: run through the ops below
                            self.assertEqual(run(state, name, {})[1], name)
                    elif way in (catalog.EXTRAS, catalog.CAPTAIN):
                        self.assertIn(way, shown, f"{role}: {name} needs {way}, which is not listed")
                        self.assertIn(name, shown[way]["description"])
                        result = run(state, way, {"op": name, "args": {}})
                        self.assertEqual(result[1], name, f"{role}: {way}(op={name}) ran {result}")
                self.assertTrue({"whoami", "guide"} <= set(shown))

    def test_guide_names_every_callable_tool_and_how_to_call_it(self):
        for role, entry in MATRIX.items():
            state = entry["state"]
            index = {row["name"]: row for row in catalog.guide_index(state)["tools"]}
            with self.subTest(role=role):
                self.assertEqual(set(index), set(entry["callable"]))
                for name in entry["callable"]:
                    full = catalog.guide_entry(state, name)
                    self.assertEqual(full["name"], name)
                    self.assertTrue(full["inputSchema"])

    def test_the_door_runs_only_what_it_names(self):
        state = MATRIX["participant"]["state"]
        with self.assertRaisesRegex(ValueError, "specialist ops"):
            run(state, catalog.EXTRAS, {"op": "whoami", "args": {}})
        with self.assertRaisesRegex(ValueError, "specialist ops"):
            run(state, catalog.EXTRAS, {"op": catalog.EXTRAS, "args": {}})
        with self.assertRaisesRegex(ValueError, "exactly op and args"):
            run(state, catalog.EXTRAS, {"op": "render_check"})

    def test_a_tool_the_role_cannot_call_is_refused_through_the_door_too(self):
        reader = MATRIX["participant_read_only"]["state"]
        for name in HIDDEN_FROM_EVERYONE - {"offer_handover"}:
            with self.assertRaises(ValueError):
                run(reader, catalog.EXTRAS, {"op": name, "args": {}})
        with self.assertRaises(ValueError):
            run(reader, "retire_child", {})

    def test_an_unlisted_screen_tool_without_a_share_is_the_old_refusal(self):
        state = MATRIX["participant_dynamic_screen_none"]["state"]
        with self.assertRaises(ApiError):
            run(state, "screen_click", {})

    def test_the_listing_is_a_fraction_of_the_full_catalog(self):
        for role, entry in MATRIX.items():
            state = entry["state"]
            full = len(json.dumps(catalog.every_tool(state)))
            slim = len(json.dumps(catalog.listed(state)))
            with self.subTest(role=role):
                self.assertLess(slim, full * 0.7 if full > 20000 else full)


if __name__ == "__main__":
    unittest.main()
