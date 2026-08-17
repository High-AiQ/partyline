"""The cockpit venv must match the lockfile before anyone restarts."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.cockpit_venv import (
    IDENTITY,
    cockpit_can_boot,
    loaded_from_cockpit,
    probe_server,
    replacement_python,
    sync_locked,
    tree_version,
)


def result(code, stderr="", stdout=""):
    return SimpleNamespace(returncode=code, stderr=stderr, stdout=stdout)


class SyncLockedTest(unittest.TestCase):
    def test_a_failed_sync_is_a_refusal_not_a_default_venv(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs.get("env", {})))
            return result(1, stderr="No solution found when resolving dependencies")

        with tempfile.TemporaryDirectory() as directory:
            refused = sync_locked(Path(directory), run=run)
        self.assertIsNotNone(refused)
        problem, fix = refused
        self.assertIn("lockfile", problem)
        self.assertIn("uv sync --locked", fix)
        self.assertEqual(calls[0][0][:3], ["uv", "sync", "--locked"])

    def test_sync_does_not_inherit_a_foreign_virtual_env(self):
        captured = {}

        def run(command, **kwargs):
            captured.update(kwargs.get("env") or {})
            return result(0)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".venv").mkdir()
            os.environ["VIRTUAL_ENV"] = "/home/gmccarthy/code/partyline/.venv"
            try:
                self.assertIsNone(sync_locked(root, run=run))
            finally:
                os.environ.pop("VIRTUAL_ENV", None)
        self.assertEqual(captured.get("VIRTUAL_ENV"), str((root / ".venv").resolve()))

    def test_a_successful_sync_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(sync_locked(Path(directory), run=lambda *_a, **_k: result(0)))


class ProbeServerTest(unittest.TestCase):
    def test_a_missing_dependency_is_the_pillow_outage(self):
        """Negative control: the exact crash from cockpit.log at 18:18:18."""

        def run(command, **kwargs):
            self.assertEqual(command[1:3], ["-P", "-c"])
            self.assertIn("partyline", command[3])
            return result(1, stderr="ModuleNotFoundError: No module named 'PIL'\n")

        error = probe_server(Path("/venv/bin/python3"), Path("/cockpit"), run=run)
        self.assertEqual(error, "ModuleNotFoundError: No module named 'PIL'")

    def test_an_editable_workbench_install_is_refused(self):
        """Opus's live finding: cockpit python loaded the workbench via .pth."""
        with tempfile.TemporaryDirectory() as directory:
            cockpit = Path(directory) / "cockpit"
            workbench = Path(directory) / "workbench"
            (cockpit / "partyline").mkdir(parents=True)
            (cockpit / "partyline" / "__init__.py").write_text('__version__ = "0.32.1"\n')
            payload = json.dumps({
                "file": str(workbench / "partyline" / "__init__.py"),
                "version": "0.32.2",
            })
            error = probe_server(
                Path("/venv/bin/python3"),
                cockpit,
                run=lambda *_a, **_k: result(0, stdout=payload),
            )
        self.assertIsNotNone(error)
        self.assertIn("not the cockpit", error)

    def test_a_version_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            cockpit = Path(directory)
            (cockpit / "partyline").mkdir()
            (cockpit / "partyline" / "__init__.py").write_text('__version__ = "0.32.1"\n')
            payload = json.dumps({
                "file": str(cockpit / "partyline" / "__init__.py"),
                "version": "0.32.2",
            })
            error = probe_server(
                Path("/venv/bin/python3"),
                cockpit,
                run=lambda *_a, **_k: result(0, stdout=payload),
            )
        self.assertEqual(error, "interpreter reports 0.32.2, cockpit tree is 0.32.1")

    def test_matching_path_and_version_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            cockpit = Path(directory)
            init = cockpit / "partyline" / "__init__.py"
            init.parent.mkdir()
            init.write_text('__version__ = "0.32.1"\n')
            payload = json.dumps({"file": str(init), "version": "0.32.1"})
            self.assertIsNone(
                probe_server(
                    Path("/venv/bin/python3"),
                    cockpit,
                    run=lambda *_a, **_k: result(0, stdout=payload),
                )
            )

    def test_replacement_python_is_the_sibling_of_the_console_script(self):
        self.assertEqual(
            replacement_python(Path("/cockpit/.venv/bin/partyline")),
            Path("/cockpit/.venv/bin/python3"),
        )

    def test_tree_version_reads_the_file_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            init = Path(directory) / "partyline" / "__init__.py"
            init.parent.mkdir()
            init.write_text('__version__ = "0.32.1"\n')
            self.assertEqual(tree_version(Path(directory)), "0.32.1")


class CockpitCanBootTest(unittest.TestCase):
    def test_a_missing_venv_is_silent_when_not_required(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(cockpit_can_boot(Path(directory)))

    def test_a_missing_venv_is_a_refusal_when_required(self):
        with tempfile.TemporaryDirectory() as directory:
            refused = cockpit_can_boot(Path(directory), required=True)
        self.assertIsNotNone(refused)
        self.assertIn("missing", refused[0])

    def test_an_unimportable_cockpit_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / ".venv" / "bin" / "python3"
            python.parent.mkdir(parents=True)
            python.write_text("")
            refused = cockpit_can_boot(
                Path(directory),
                required=True,
                run=lambda *_a, **_k: result(1, stderr="ModuleNotFoundError: No module named 'PIL'"),
            )
        self.assertIsNotNone(refused)
        self.assertIn("PIL", refused[0])


class RealImportControlTest(unittest.TestCase):
    def test_this_interpreter_loads_this_worktree(self):
        os.environ.setdefault("PARTYLINE_DB", "/tmp/partyline-test-cockpit-venv.db")
        root = Path(__file__).resolve().parents[1]
        self.assertTrue(loaded_from_cockpit(root / "partyline" / "__init__.py", root))
        self.assertIsNone(probe_server(Path(sys.executable), root, run=subprocess.run))
        self.assertIn("partyline.__file__", IDENTITY)

    def test_a_poisoned_pth_shadow_is_refused_even_from_the_cockpit_directory(self):
        """Production shape: editable .pth points at another tree.

        ``-P`` stops cwd from hiding the shadow. Without it this test would
        pass for the wrong reason — the same false green as the live cockpit.
        """
        with tempfile.TemporaryDirectory() as directory:
            cockpit = Path(directory) / "cockpit"
            workbench = Path(directory) / "workbench"
            (cockpit / "partyline").mkdir(parents=True)
            (workbench / "partyline").mkdir(parents=True)
            (cockpit / "partyline" / "__init__.py").write_text(
                '__version__ = "0.32.0"\n', encoding="utf-8"
            )
            (workbench / "partyline" / "__init__.py").write_text(
                '__version__ = "0.32.2"\n', encoding="utf-8"
            )
            os.environ.setdefault("PARTYLINE_DB", "/tmp/partyline-test-cockpit-venv.db")

            def run(command, **kwargs):
                env = {**os.environ, "PYTHONPATH": str(workbench)}
                return subprocess.run(
                    [sys.executable, "-P", "-c", command[command.index("-c") + 1]],
                    cwd=kwargs.get("cwd"),
                    env=env,
                    capture_output=True,
                    text=True,
                )

            error = probe_server(Path(sys.executable), cockpit, run=run)
        self.assertIsNotNone(error)
        self.assertTrue(
            "not the cockpit" in error or "0.32.2" in error,
            error,
        )
