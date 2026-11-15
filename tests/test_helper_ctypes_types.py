"""ctypes argtypes live on shared DLL function objects, so their structure types must be defined once."""
import ast
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent / "partyline_helper"


def structure_classes_inside_functions(tree):
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.ClassDef) and any(
                    ast.unparse(base).split(".")[-1] in ("Structure", "Union") for base in inner.bases):
                found.append(f"{inner.name}:{inner.lineno}")
    return found


class HelperCtypesTypes(unittest.TestCase):
    def test_no_ctypes_structure_is_defined_per_call(self):
        # A per-call class set as argtypes on a shared handle makes concurrent callers fail with
        # "expected LP_X instance instead of pointer to X"; that exception once ended the helper.
        offenders = {path.name: found for path in sorted(HELPER.glob("*.py"))
                     if (found := structure_classes_inside_functions(ast.parse(path.read_text())))}
        self.assertEqual({}, offenders)

    def test_the_guard_sees_a_function_local_structure(self):
        tree = ast.parse("import ctypes\ndef f():\n    class P(ctypes.Structure):\n        pass\n")
        self.assertEqual(["P:3"], structure_classes_inside_functions(tree))
