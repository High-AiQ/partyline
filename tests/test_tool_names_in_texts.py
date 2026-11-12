"""Texts that name a tool the reader cannot see listed must give the route to it.

The catalog lists only the everyday tools; the rest run as `captain(op, args)` or
`extras(op, args)`. A pack, notice or error that said `restart_implementer(conv_id)` or
`accept_handover(id)` pointed a captain at a name its `tools/list` does not contain.
The test walks every string constant of the modules that write such text for any such name
and fails unless the same sentence carries the route.
"""

import ast
import json
import re
import unittest
from pathlib import Path

from partyline.mcp import catalog, tools_captain

ROOT = Path(__file__).resolve().parent.parent / "partyline"
MATRIX = json.loads((Path(__file__).parent / "fixtures" / "mcp_role_matrix.json").read_text())
# The modules whose strings are pasted or returned to a process.
TEXTS = (
    "captain_docs.py", "captain_handover.py", "captain_idle.py", "line_process_routes.py",
    "mention_fallbacks.py", "orchestrator_revive.py", "orchestrator_store.py", "orchestrator_pack.py",
    "pack_blocks.py", "reattach_queue.py", "task_ghost_mentions.py", "role_briefing.py", "goal.py",
    "screen_hints.py", "screen_window_grants.py", "screen_share_notices.py", "hierarchy_routes.py",
    "adapters/briefing.py", "role_delivery.py", "handover_state.py",
)
ROUTES = {catalog.CAPTAIN: "captain(op", catalog.EXTRAS: "extras(op"}


def hidden_names() -> dict[str, str]:
    """Tool name -> the door it needs, for names some role cannot see listed."""
    found = {}
    for entry in MATRIX.values():
        for name in entry["callable"]:
            way = catalog.door(name, entry["state"])
            if way in ROUTES and "_" in name:
                found[name] = way
    return found


def sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+|\n", text)


def violations() -> list[str]:
    names = hidden_names()
    pattern = re.compile(r"(?<![.\w\"'=-])(" + "|".join(sorted(names, key=len, reverse=True)) + r")\b")
    bad = []
    for relative in TEXTS:
        tree = ast.parse((ROOT / relative).read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if node.value.strip() in names:  # a bare identifier: a dict key or column, not prose
                continue
            for sentence in sentences(node.value):
                for match in pattern.finditer(sentence):
                    if ROUTES[names[match.group(1)]] not in sentence:
                        bad.append(f"{relative}:{node.lineno} {match.group(1)}: {sentence.strip()[:100]}")
    return bad


class ToolNamesInTextsTest(unittest.TestCase):
    def test_the_hidden_set_is_the_one_the_catalog_hides(self):
        names = hidden_names()
        for expected in ("set_goal", "restart_implementer", "restart_reviewer", "share_ref", "retire_child",
                         "retirement_preview", "accept_handover", "complete_handover", "docs_read"):
            self.assertIn(expected, names)
        self.assertNotIn("create_task", names)  # listed itself

    def test_every_text_names_hidden_tools_only_with_their_route(self):
        self.assertEqual(violations(), [])

    def test_the_captain_guide_explains_both_doors(self):
        state = MATRIX["root_captain"]["state"]
        doors = tools_captain.guide(state)["doors"]
        self.assertIn("captain(op, args)", doors["captain"])
        self.assertIn("extras(op, args)", doors["extras"])

    def test_an_unknown_captain_op_says_where_the_valid_ones_are_listed(self):
        state = MATRIX["root_captain"]["state"]
        with self.assertRaisesRegex(ValueError, r"guide\(topic=\"captain\"\)"):
            tools_captain.call(object(), "captain", {"op": "nope", "args": {}}, state)


if __name__ == "__main__":
    unittest.main()
