"""Workflow validation, approval boundaries and generated skills."""

import tempfile
import unittest
from pathlib import Path

from partyline.adapters.bundled.codex.workflow_skills import install
from partyline.db import Db
from partyline.screen_workflow_audit import approval, approve
from partyline.screen_workflow_files import Checkout, load, names, parse
from partyline.screen_workflow_skills import SkillDirectory, approved_definitions

from tests.test_screen_workflows import LAB, PORTABLE


class WorkflowFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.nested = self.project / "work"
        self.nested.mkdir(parents=True)
        self.space = Checkout(self.nested, self.project, str(self.project))
        self.path = self.write(self.project, PORTABLE)

    def write(self, folder, content):
        directory = folder / ".partyline" / "workflows"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "portable.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_nearest_invalid_file_blocks_parent_and_paths_cannot_escape(self):
        original = load(self.space, "portable")
        self.assertEqual(original.path, ".partyline/workflows/portable.yaml")
        near = self.write(self.nested, PORTABLE + "\nwrong: true")
        with self.assertRaisesRegex(ValueError, "wrong"):
            load(self.space, "portable")
        near.unlink()
        try:
            near.symlink_to(self.path)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "symlinks|symlink"):
            load(self.space, "portable")
        self.assertEqual(names(self.space), ["portable"])
        with self.assertRaises(ValueError):
            load(self.space, "../portable")
        outside = self.root / "branch"
        outside.mkdir()
        with self.assertRaises(FileNotFoundError):
            load(Checkout(outside, outside, str(self.project)), "portable")

    def test_yaml_rejects_unsupported_version_duplicate_keys_aliases_and_unknown_bindings(self):
        for text, error in (
            (PORTABLE.replace("version: 1", "version: 2"), "version"),
            (PORTABLE.replace("version: 1", "version: true"), "integer"),
            (PORTABLE + "\nname: portable", "unique strings"),
            (PORTABLE.replace("value: image", "value: *anchor"), "aliases"),
            (PORTABLE.replace("param: text", "param: unknown"), "declared text"),
            (
                PORTABLE.replace(
                    "role: button, name: Edit record", "role: button, name: Edit record, ordinal: 1"
                ),
                "named scope",
            ),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                parse(text.encode(), "portable")
        with self.assertRaisesRegex(ValueError, "text exceeds"):
            parse(PORTABLE.encode(), "portable").plan({"text": "x" * 501})
        with self.assertRaisesRegex(ValueError, "record fields"):
            parse(LAB.read_bytes(), LAB.stem).plan(
                {
                    "kind": "image",
                    "title": "a",
                    "notes": "",
                    "alt_text": "",
                    "images": ["id"],
                    "rows": [{}, {}],
                }
            )

    def test_approval_and_skills_follow_the_exact_checkout_revision(self):
        db = Db(self.root / "db.sqlite3")
        self.addCleanup(db.close)
        revision = load(self.space, "portable")
        self.assertEqual(approved_definitions(db, self.space), {})
        approve(db, revision, 1)
        self.assertIsNotNone(approval(db, revision))
        copied = self.root / "copy"
        self.write(copied, PORTABLE)
        for project in (str(copied), self.space.project):
            self.assertIsNone(approval(db, load(Checkout(copied, copied, project), "portable")))
        skills = self.root / "generated"
        skills.mkdir()
        installed = {}
        SkillDirectory.sync(skills, installed, approved_definitions(db, self.space))
        path = skills / "workflow-portable" / "SKILL.md"
        rendered = path.read_text(encoding="utf-8")
        self.assertIn("screen_workflow_start", rendered)
        self.assertIn("The native editor is open.", rendered)
        self.assertIn('"type": "text"', rendered)
        self.assertNotIn("Edit record", rendered)

        replacement = self.path.with_name("replacement.yaml")
        replacement.write_text(PORTABLE, encoding="utf-8")
        replacement.replace(self.path)
        current = load(self.space, "portable")
        self.assertEqual(current.digest, revision.digest)
        self.assertIsNone(approval(db, current))
        SkillDirectory.sync(skills, installed, approved_definitions(db, self.space))
        self.assertFalse(path.exists())
        approve(db, current, 1)
        SkillDirectory.sync(skills, installed, approved_definitions(db, self.space))
        self.assertTrue(path.exists())
        db._exec("DELETE FROM screen_workflow_approvals")
        SkillDirectory.sync(skills, installed, approved_definitions(db, self.space))
        self.assertFalse(path.exists())

    def test_codex_keeps_personal_skills_and_discovers_only_its_line_projection(self):
        shared = self.root / "shared"
        home = self.root / "private"
        (shared / "skills" / "personal").mkdir(parents=True)
        home.mkdir()
        try:
            (home / "skills").symlink_to(shared / "skills", target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        generated = self.root / "generated"
        generated.mkdir()
        install(home, shared, generated)
        self.assertFalse((home / "skills").is_symlink())
        self.assertTrue((home / "skills" / "personal").is_dir())
        self.assertEqual((home / "skills" / "partyline-workflows").resolve(), generated)
        self.assertFalse((shared / "skills" / "partyline-workflows").exists())
