"""Composition checks every reachable file and expands concrete typed invocations."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.db import Db
from partyline.screen_workflow_audit import approval, approve
from partyline.screen_workflow_bundle import load_bundle
from partyline.screen_workflow_files import Checkout, parse
from partyline.screen_workflow_skills import approved_definitions

EXAMPLE = Path(__file__).parent / "fixtures/screen-workflows/publish-document"
ROOT = "publish-document"


class WorkflowBundleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.folder = root / ".partyline/workflows"
        shutil.copytree(EXAMPLE, self.folder)
        self.space = Checkout(root, root, str(root))
        self.db = Db(root / "test.db")
        self.addCleanup(self.db.close)
        self.parameters = json.loads((EXAMPLE / "parameters.json").read_text())

    def edit(self, name, transform):
        path = self.folder / f"{name}.yaml"
        path.write_text(transform(path.read_text()))

    def test_document_bundle_composes_the_selected_module_types_and_nested_cells(self):
        bundle = load_bundle(self.space, ROOT)
        plan = bundle.plan(self.parameters)
        ids = [ident for ident, _ in plan]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "title")
        self.assertEqual(ids[-1], "publish")
        self.assertIn("module[1]/image-module/attach", ids)
        self.assertIn("module[3]/table-module/cell[2][2]/text-cell/fill", ids)
        filled = dict(plan)["module[3]/table-module/cell[2][2]/text-cell/fill"]
        self.assertEqual(filled.inputs.value, "Open all year")
        self.assertEqual(filled.target.within.name, "Row 2")
        review = bundle.review()
        self.assertEqual(set(review["pieces"]), {f.stem for f in EXAMPLE.glob("*.yaml")})
        self.assertEqual(review["requires"], ["cdp.set_files"])
        confirm = review["pieces"][ROOT]["definition"]["steps"][-1]
        self.assertTrue(confirm["confirm"])
        self.assertEqual(confirm["effect"], "Publish the document and its saved modules.")
        call = review["pieces"]["text-cell"]["definition"]["steps"][0]
        self.assertEqual(call["with"]["row"], {"param": "row"})

    def test_editing_an_unselected_component_invalidates_ancestor_approval_and_skill(self):
        original = load_bundle(self.space, ROOT)
        approve(self.db, original, 7)
        self.parameters["modules"] = self.parameters["modules"][:1]
        self.assertTrue(original.plan(self.parameters))
        self.assertEqual(set(approved_definitions(self.db, self.space)), {f"workflow-{ROOT}"})
        self.edit("choose-cell", lambda text: text + "\n# Revised description.\n")
        changed = load_bundle(self.space, ROOT)
        self.assertNotEqual(changed.digest, original.digest)
        self.assertFalse(original.current())
        self.assertIsNone(approval(self.db, changed))
        self.assertFalse(approved_definitions(self.db, self.space))

    def test_receiving_declaration_is_checked_before_expansion_can_run(self):
        bundle = load_bundle(self.space, ROOT)
        self.parameters["modules"][0]["images"] = []
        with self.assertRaisesRegex(ValueError, "within its declared bounds"):
            bundle.plan(self.parameters)
        self.edit("image-module", lambda text: text.replace("alt: {type: text, max_length: 200}",
                                                           "alt: {type: media_id}")
                  .replace("inputs: {value: {param: alt}}", "inputs: {value: Fixed}")
                  .replace("expected: {param: alt}", "expected: Fixed"))
        with self.assertRaisesRegex(ValueError, "incompatible bindings"):
            load_bundle(self.space, ROOT)

    def test_missing_cycle_and_dag_call_depth_refused_even_when_branch_is_unselected(self):
        leaf = self.folder / "choose-cell.yaml"
        original = leaf.read_text()
        leaf.unlink()
        with self.assertRaisesRegex(ValueError, "missing component"):
            load_bundle(self.space, ROOT)
        leaf.write_text(
            original.split("steps:")[0]
            + "steps: [{id: again, use: table-module}]\n"
        )
        with self.assertRaisesRegex(ValueError, "cycle"):
            load_bundle(self.space, ROOT)
        leaf.write_text(original)
        for index in range(4, -1, -1):
            name = f"chain-{index}"
            destination = f"chain-{index + 1}" if index < 4 else "save-draft-module"
            (self.folder / f"{name}.yaml").write_text(
                f"version: 1\nname: {name}\ndescription: Chain.\nuse_when: Testing.\n"
                f"steps: [{{id: next, use: {destination}}}]\n"
            )
        with self.assertRaisesRegex(ValueError, "call depth"):
            load_bundle(self.space, "chain-0")

    def test_repeats_have_a_depth_and_expanded_action_limit(self):
        source = (EXAMPLE / f"{ROOT}.yaml").read_text()
        with self.assertRaisesRegex(ValueError, "repeat nesting"):
            too_deep = source.split("steps:")[0] + "steps:\n"
            lines = ["- for_each: modules\n  steps:\n"] * 5
            lines.append(
                "- id: open\n  target: {role: button, name: Open}\n  action: invoke\n"
                "  confirm: false\n  postcondition: {check: present, timeout_ms: 1}\n"
            )
            too_deep += "".join("".join(" " * (2 + i * 4) + line for line in block.splitlines(True))
                                for i, block in enumerate(lines))
            parse(too_deep.encode(), ROOT)
        bundle = load_bundle(self.space, ROOT)
        with patch("partyline.screen_workflow_plan.MAX_EXPANDED_STEPS", 3):
            with self.assertRaisesRegex(ValueError, "expanded plan exceeds 3"):
                bundle.plan(self.parameters)

    def test_example_fits_seven_modules_and_ten_rows_with_six_columns(self):
        cell = self.parameters["modules"][2]["rows"][0]["cells"][1]
        rows = [
            {
                "row": f"Row {row}",
                "reference": "Comparison item",
                "cells": [
                    {**cell, "row": f"Row {row}", "column": f"Option {column}",
                     "text_field": f"Option {column} text"}
                    for column in range(1, 6)
                ],
            }
            for row in range(1, 11)
        ]
        module = {**self.parameters["modules"][2], "rows": rows}
        self.parameters["modules"] = [module] * 7
        plan = load_bundle(self.space, ROOT).plan(self.parameters)
        self.assertEqual(len(plan), 856)
