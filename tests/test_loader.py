"""Coverage for adapter discovery: the registry, the package loader, and import.

Everything here works on real files in a temp directory, because that is exactly
what the loader's contract is about — manifests, entrypoints, and checkouts on
disk. Nothing sleeps and nothing races: the only concurrency is git, and git is
run against a local repository we created ourselves.
"""

import os
import subprocess
import shutil
import tempfile
import textwrap
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("PARTYLINE_DB", "/tmp/partyline-test-loader.db")

from partyline.adapters import loader, registry
from partyline.adapters.base import Adapter

ENTRYPOINT = textwrap.dedent("""
    from partyline.adapters.base import Adapter

    class PartylineAdapter(Adapter):
        marker = "probe"
""")

MANIFEST_FIELDS = {
    "name": "Probe",
    "version": "1.0.0",
    "description": "A test adapter.",
    "entrypoint": "adapter.py",
    "command": ["probe"],
}


def write_package(directory: Path, source=ENTRYPOINT, **overrides) -> Path:
    """Write a minimal valid adapter package, with fields overridden or removed.

    An override of None drops the field, which is how the missing-field cases
    are built without hand-writing a manifest per test.
    """
    directory.mkdir(parents=True, exist_ok=True)
    fields = {**MANIFEST_FIELDS, **overrides}
    lines = ["[adapter]"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key} = [" + ", ".join(f'"{item}"' for item in value) + "]")
        elif isinstance(value, dict):
            inner = ", ".join(f"{k} = {str(v).lower()}" for k, v in value.items())
            lines.append(f"{key} = {{ {inner} }}")
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        else:
            lines.append(f'{key} = "{value}"')
    (directory / "adapter.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if source is not None:
        (directory / "adapter.py").write_text(source, encoding="utf-8")
    return directory


@contextmanager
def isolated_registry():
    """The registry is process-global; no test may leak into another."""
    adapters = dict(registry.ADAPTERS)
    metadata = dict(registry.ADAPTER_METADATA)
    paths = dict(loader._LOADED_PATHS)
    try:
        yield
    finally:
        registry.ADAPTERS.clear(), registry.ADAPTERS.update(adapters)
        registry.ADAPTER_METADATA.clear(), registry.ADAPTER_METADATA.update(metadata)
        loader._LOADED_PATHS.clear(), loader._LOADED_PATHS.update(paths)


class RegistryTest(unittest.TestCase):
    def test_registering_stores_the_class_and_stamps_the_id_into_metadata(self):
        with isolated_registry():
            registry.register_adapter("  PROBE  ", Adapter, {"name": "Probe"})
            self.assertIs(registry.ADAPTERS["probe"], Adapter)
            self.assertEqual(registry.ADAPTER_METADATA["probe"],
                             {"id": "probe", "name": "Probe"})

    def test_registering_with_no_metadata_still_yields_an_id(self):
        with isolated_registry():
            registry.register_adapter("probe", Adapter)
            self.assertEqual(registry.ADAPTER_METADATA["probe"], {"id": "probe"})

    def test_an_id_that_is_not_a_lowercase_slug_is_refused(self):
        for bad in ("", "   ", "has space", "Punctuation!", "sl/ash"):
            with self.subTest(bad=bad), isolated_registry():
                with self.assertRaises(ValueError):
                    registry.register_adapter(bad, Adapter)

    def test_a_class_that_is_not_an_adapter_is_refused(self):
        with isolated_registry():
            with self.assertRaises(TypeError):
                registry.register_adapter("probe", dict)

    def test_unregistering_is_idempotent_and_case_insensitive(self):
        with isolated_registry():
            registry.register_adapter("probe", Adapter)
            registry.unregister_adapter("  PROBE ")
            registry.unregister_adapter("probe")  # already gone: must not raise
            self.assertNotIn("probe", registry.ADAPTERS)
            self.assertNotIn("probe", registry.ADAPTER_METADATA)

    def test_make_adapter_hands_the_instance_its_own_metadata(self):
        with isolated_registry():
            registry.register_adapter("probe", Adapter, {"env_unset": ["X"]})
            built = registry.make_adapter(
                "probe", {"id": "a", "name": "n", "command": ["cat"], "cwd": "/tmp"},
                _post, _status)
            self.assertEqual(built.att["adapter_metadata"]["env_unset"], ["X"])

    def test_make_adapter_does_not_mutate_the_attachment_it_was_given(self):
        with isolated_registry():
            registry.register_adapter("probe", Adapter, {})
            attachment = {"id": "a", "name": "n", "command": ["cat"], "cwd": "/tmp"}
            registry.make_adapter("probe", attachment, _post, _status)
            self.assertNotIn("adapter_metadata", attachment)

    def test_an_unknown_adapter_is_a_readable_error(self):
        with isolated_registry():
            with self.assertRaises(ValueError) as caught:
                registry.make_adapter("nope", {}, _post, _status)
            self.assertIn("unknown adapter: nope", str(caught.exception))


async def _post(sender, sender_type, body):
    pass


async def _status(status):
    pass


class ManifestValidationTest(unittest.TestCase):
    def _load_expecting_failure(self, **package):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            path = write_package(Path(directory) / "probe", **package)
            with self.assertRaises(ValueError) as caught:
                loader.load_adapter(path)
            return str(caught.exception)

    def test_a_directory_with_no_manifest_is_not_an_adapter(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            empty = Path(directory) / "empty"
            empty.mkdir()
            with self.assertRaises(ValueError) as caught:
                loader.load_adapter(empty)
            self.assertIn("invalid adapter package", str(caught.exception))

    def test_a_manifest_with_no_adapter_table_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            path = Path(directory) / "probe"
            path.mkdir()
            (path / "adapter.toml").write_text('[something_else]\nname = "x"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                loader.load_adapter(path)

    def test_unparseable_toml_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            path = Path(directory) / "probe"
            path.mkdir()
            (path / "adapter.toml").write_text("this is not = = toml\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                loader.load_adapter(path)

    def test_every_required_field_is_named_when_it_is_missing(self):
        for field in ("name", "version", "description", "entrypoint", "command"):
            with self.subTest(field=field):
                message = self._load_expecting_failure(**{field: None})
                self.assertIn("missing", message)
                self.assertIn(field, message)

    def test_a_command_that_is_not_an_argv_array_is_rejected(self):
        self.assertIn("argv array", self._load_expecting_failure(command="probe --flag"))

    def test_an_update_command_that_is_not_an_argv_array_is_rejected(self):
        self.assertIn(
            "argv array", self._load_expecting_failure(update_command="grok update")
        )

    def test_a_missing_update_command_is_none(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            loader.load_adapter(write_package(Path(directory) / "probe"))
            self.assertIsNone(registry.ADAPTER_METADATA["probe"]["update_command"])

    def test_capabilities_must_be_a_table(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            path = Path(directory) / "probe"
            write_package(path)
            manifest = (path / "adapter.toml").read_text(encoding="utf-8")
            (path / "adapter.toml").write_text(manifest + 'capabilities = "resume"\n',
                                               encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                loader.load_adapter(path)
            self.assertIn("capabilities must be a table", str(caught.exception))

    def test_a_missing_entrypoint_file_is_rejected(self):
        message = self._load_expecting_failure(entrypoint="nowhere.py")
        self.assertIn("entrypoint must be a file", message)

    def test_an_entrypoint_outside_its_package_is_rejected(self):
        """Otherwise a manifest could point at any file on the machine."""
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            outside = Path(directory) / "outside.py"
            outside.write_text(ENTRYPOINT, encoding="utf-8")
            path = write_package(Path(directory) / "probe", entrypoint="../outside.py")
            with self.assertRaises(ValueError) as caught:
                loader.load_adapter(path)
            self.assertIn("entrypoint must be a file", str(caught.exception))

    def test_a_class_that_does_not_inherit_adapter_is_rejected(self):
        message = self._load_expecting_failure(
            source="class PartylineAdapter:\n    pass\n")
        self.assertIn("must inherit Adapter", message)

    def test_a_missing_class_is_rejected(self):
        message = self._load_expecting_failure(source="x = 1\n")
        self.assertIn("must inherit Adapter", message)


class LoadAdapterTest(unittest.TestCase):
    def test_loading_registers_the_package_under_its_directory_name(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            path = write_package(Path(directory) / "probe")
            adapter_id = loader.load_adapter(path)
            self.assertEqual(adapter_id, "probe")
            self.assertIn("probe", registry.ADAPTERS)
            self.assertEqual(registry.ADAPTER_METADATA["probe"]["source"], str(path.resolve()))
            self.assertFalse(registry.ADAPTER_METADATA["probe"]["overrides_bundled"])

    def test_imported_package_reports_when_it_overrides_a_bundle(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            root = Path(directory)
            bundled_root = root / "bundled"
            write_package(bundled_root / "probe")
            imported = write_package(root / "imported" / "probe")
            with patch.object(loader, "BUNDLED_ROOT", bundled_root):
                with self.assertLogs("partyline.adapters.loader", level="WARNING") as logs:
                    loader.load_adapter(imported)
            metadata = registry.ADAPTER_METADATA["probe"]
            self.assertTrue(metadata["overrides_bundled"])
            self.assertIn("overrides bundled adapter", logs.output[0])

    def test_an_explicit_id_in_the_manifest_wins_over_the_directory_name(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            path = write_package(Path(directory) / "some-folder", id="Renamed")
            self.assertEqual(loader.load_adapter(path), "renamed")

    def test_bundled_packages_are_labelled_bundled_not_by_path(self):
        with isolated_registry():
            loader.load_bundled_adapters()
            self.assertEqual(registry.ADAPTER_METADATA["raw"]["source"], "bundled")
            self.assertEqual(registry.ADAPTER_METADATA["muse"]["source"], "bundled")
            self.assertTrue(registry.ADAPTER_METADATA["muse"]["capabilities"]["resume"])

    def test_reloading_re_executes_the_file_rather_than_reusing_the_module(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            path = write_package(Path(directory) / "probe")
            loader.load_adapter(path)
            self.assertEqual(registry.ADAPTERS["probe"].marker, "probe")

            (path / "adapter.py").write_text(ENTRYPOINT.replace("probe", "edited"),
                                             encoding="utf-8")
            loader.reload_adapter("probe")

            self.assertEqual(registry.ADAPTERS["probe"].marker, "edited")

    def test_reloading_something_that_was_never_loaded_is_an_error(self):
        with isolated_registry():
            with self.assertRaises(ValueError) as caught:
                loader.reload_adapter("never-loaded")
            self.assertIn("not loaded", str(caught.exception))

    def test_reloading_restores_the_bundle_when_an_imported_source_vanished(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            root = Path(directory)
            bundled_root = root / "bundled"
            write_package(bundled_root / "probe", source=ENTRYPOINT.replace('"probe"', '"bundled"'))
            imported = write_package(root / "imported" / "probe")
            with patch.object(loader, "BUNDLED_ROOT", bundled_root):
                loader.load_adapter(imported)
                shutil.rmtree(imported)
                self.assertEqual(loader.reload_adapter("probe"), "probe")
            self.assertEqual(registry.ADAPTERS["probe"].marker, "bundled")
            self.assertEqual(registry.ADAPTER_METADATA["probe"]["source"], "bundled")
            self.assertFalse(registry.ADAPTER_METADATA["probe"]["overrides_bundled"])

    def test_reloading_a_vanished_non_bundled_source_refuses(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            imported = write_package(Path(directory) / "imported" / "probe")
            loader.load_adapter(imported)
            shutil.rmtree(imported)
            with self.assertRaisesRegex(ValueError, "source is missing"):
                loader.reload_adapter("probe")
            self.assertNotIn("probe", registry.ADAPTERS)
            self.assertNotIn("probe", loader._LOADED_PATHS)

    def test_reloading_a_corrupt_source_keeps_the_existing_adapter(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            path = write_package(Path(directory) / "probe")
            loader.load_adapter(path)
            (path / "adapter.py").write_text("def broken(:\n", encoding="utf-8")
            with self.assertRaises(SyntaxError):
                loader.reload_adapter("probe")
            self.assertEqual(registry.ADAPTERS["probe"].marker, "probe")
            self.assertEqual(loader._LOADED_PATHS["probe"], path.resolve())

    def test_reloading_all_restores_a_bundle_for_a_vanished_import(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            root = Path(directory)
            bundled_root = root / "bundled"
            write_package(bundled_root / "probe")
            imported = write_package(root / "imported" / "probe")
            with patch.object(loader, "BUNDLED_ROOT", bundled_root):
                loader._LOADED_PATHS.clear()
                loader.load_adapter(imported)
                shutil.rmtree(imported)
                self.assertEqual(loader.reload_adapters(), ["probe"])
            self.assertEqual(registry.ADAPTER_METADATA["probe"]["source"], "bundled")

    def test_reload_adapters_refreshes_everything_known(self):
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            loader._LOADED_PATHS.clear()
            write_package(Path(directory) / "one")
            write_package(Path(directory) / "two")
            loader.load_adapter(Path(directory) / "one")
            loader.load_adapter(Path(directory) / "two")

            self.assertEqual(sorted(loader.reload_adapters()), ["one", "two"])


class AdapterStoreTest(unittest.TestCase):
    def test_the_store_location_follows_the_environment(self):
        original = os.environ.get("PARTYLINE_ADAPTERS_DIR")
        try:
            os.environ["PARTYLINE_ADAPTERS_DIR"] = "/tmp/probe-store"
            self.assertEqual(loader.adapter_store(), Path("/tmp/probe-store"))
            os.environ.pop("PARTYLINE_ADAPTERS_DIR")
            self.assertEqual(loader.adapter_store(), Path("~/.partyline/adapters").expanduser())
        finally:
            if original is None:
                os.environ.pop("PARTYLINE_ADAPTERS_DIR", None)
            else:
                os.environ["PARTYLINE_ADAPTERS_DIR"] = original

    def test_a_single_package_checkout_yields_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_package(Path(directory) / "solo")
            self.assertEqual(list(loader.adapter_packages(path)), [path])

    def test_a_collection_checkout_yields_each_package_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "collection"
            write_package(root / "adapters" / "beta")
            write_package(root / "adapters" / "alpha")
            self.assertEqual([p.name for p in loader.adapter_packages(root)], ["alpha", "beta"])

    def test_a_checkout_that_is_neither_yields_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(list(loader.adapter_packages(Path(directory))), [])


class InstalledAdaptersTest(unittest.TestCase):
    @contextmanager
    def _store(self):
        original = os.environ.get("PARTYLINE_ADAPTERS_DIR")
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            os.environ["PARTYLINE_ADAPTERS_DIR"] = directory
            try:
                yield Path(directory)
            finally:
                if original is None:
                    os.environ.pop("PARTYLINE_ADAPTERS_DIR", None)
                else:
                    os.environ["PARTYLINE_ADAPTERS_DIR"] = original

    def test_a_store_that_does_not_exist_yet_loads_nothing(self):
        original = os.environ.get("PARTYLINE_ADAPTERS_DIR")
        try:
            os.environ["PARTYLINE_ADAPTERS_DIR"] = "/tmp/definitely-not-a-real-store-dir"
            self.assertEqual(loader.load_installed_adapters(), [])
        finally:
            if original is None:
                os.environ.pop("PARTYLINE_ADAPTERS_DIR", None)
            else:
                os.environ["PARTYLINE_ADAPTERS_DIR"] = original

    def test_previously_imported_checkouts_are_re_registered(self):
        with self._store() as store:
            write_package(store / "checkout" / "adapters" / "probe")
            self.assertEqual(loader.load_installed_adapters(), ["probe"])
            self.assertIn("probe", registry.ADAPTERS)

    def test_startup_logs_an_imported_adapter_that_overrides_a_bundle(self):
        with self._store() as store:
            bundled_root = store.parent / "bundled"
            write_package(bundled_root / "probe")
            write_package(store / "checkout" / "adapters" / "probe")
            with patch.object(loader, "BUNDLED_ROOT", bundled_root):
                with self.assertLogs("partyline.adapters.loader", level="WARNING") as logs:
                    self.assertEqual(loader.load_installed_adapters(), ["probe"])
            self.assertIn("overrides bundled adapter", logs.output[0])

    def test_one_broken_checkout_does_not_stop_the_others(self):
        """A bad package on disk must never make partyline unstartable."""
        with self._store() as store:
            (store / "broken").mkdir()
            (store / "broken" / "adapter.toml").write_text("[adapter]\n", encoding="utf-8")
            write_package(store / "good")

            self.assertEqual(loader.load_installed_adapters(), ["good"])

    def test_a_package_whose_entrypoint_does_not_compile_is_skipped(self):
        with self._store() as store:
            write_package(store / "syntax", source="def broken(:\n")
            write_package(store / "good")

            self.assertEqual(loader.load_installed_adapters(), ["good"])

    def test_loose_files_in_the_store_are_ignored(self):
        with self._store() as store:
            (store / "README.md").write_text("not a checkout", encoding="utf-8")
            self.assertEqual(loader.load_installed_adapters(), [])

    def test_hidden_checkouts_are_skipped_and_logged(self):
        with self._store() as store:
            write_package(store / ".disabled" / "adapters" / "probe")
            with self.assertLogs("partyline.adapters.loader", level="INFO") as logs:
                self.assertEqual(loader.load_installed_adapters(), [])
            self.assertIn("skipping hidden adapter checkout", logs.output[0])


class ImportRepositoryTest(unittest.TestCase):
    """Import runs git for real, but only ever against a local repo we build."""

    @contextmanager
    def _store(self):
        original = os.environ.get("PARTYLINE_ADAPTERS_DIR")
        with tempfile.TemporaryDirectory() as directory, isolated_registry():
            os.environ["PARTYLINE_ADAPTERS_DIR"] = str(Path(directory) / "store")
            try:
                yield Path(directory)
            finally:
                if original is None:
                    os.environ.pop("PARTYLINE_ADAPTERS_DIR", None)
                else:
                    os.environ["PARTYLINE_ADAPTERS_DIR"] = original

    def _make_repo(self, root: Path, name="partyline-probes") -> Path:
        repo = root / name
        write_package(repo / "adapters" / "probe")
        git = ["git", "-C", str(repo)]
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                       capture_output=True)
        subprocess.run(git + ["config", "user.email", "test@example.com"], check=True,
                       capture_output=True)
        subprocess.run(git + ["config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
        subprocess.run(git + ["commit", "-qm", "probe"], check=True, capture_output=True)
        return repo

    def test_an_empty_repository_argument_is_refused(self):
        with self.assertRaises(ValueError):
            loader.import_repository("   ")

    def test_a_repository_name_that_slugifies_to_nothing_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            loader.import_repository("https://example.com/...")
        self.assertIn("usable name", str(caught.exception))

    def test_cloning_a_repository_loads_every_package_it_contains(self):
        with self._store() as directory:
            repo = self._make_repo(directory)
            self.assertEqual(loader.import_repository(str(repo)), ["probe"])
            self.assertIn("probe", registry.ADAPTERS)
            self.assertTrue((loader.adapter_store() / "partyline-probes" / ".git").is_dir())

    def test_importing_a_second_time_refreshes_the_existing_checkout(self):
        with self._store() as directory:
            repo = self._make_repo(directory)
            loader.import_repository(str(repo))

            # Change the source and re-import: the checkout must move with it.
            (repo / "adapters" / "probe" / "adapter.py").write_text(
                ENTRYPOINT.replace("probe", "second"), encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "commit", "-qam", "edit"], check=True,
                           capture_output=True)

            self.assertEqual(loader.import_repository(str(repo)), ["probe"])
            self.assertEqual(registry.ADAPTERS["probe"].marker, "second")

    def test_a_ref_can_be_pinned_on_clone(self):
        with self._store() as directory:
            repo = self._make_repo(directory)
            subprocess.run(["git", "-C", str(repo), "branch", "pinned"], check=True,
                           capture_output=True)
            self.assertEqual(loader.import_repository(str(repo), "pinned"), ["probe"])

    def test_a_repository_with_no_packages_is_refused(self):
        with self._store() as directory:
            repo = directory / "empty-repo"
            repo.mkdir()
            (repo / "README.md").write_text("nothing here", encoding="utf-8")
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                           capture_output=True)
            git = ["git", "-C", str(repo)]
            subprocess.run(git + ["config", "user.email", "test@example.com"], check=True,
                           capture_output=True)
            subprocess.run(git + ["config", "user.name", "Test"], check=True, capture_output=True)
            subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
            subprocess.run(git + ["commit", "-qm", "readme"], check=True, capture_output=True)

            with self.assertRaises(ValueError) as caught:
                loader.import_repository(str(repo))
            self.assertIn("no adapter.toml packages", str(caught.exception))

    def test_a_failing_clone_surfaces_gits_own_error(self):
        with self._store() as directory:
            with self.assertRaises(subprocess.CalledProcessError):
                loader.import_repository(str(directory / "not-a-repository"))


class CompatibilityShimTest(unittest.TestCase):
    def test_the_old_raw_import_path_still_resolves(self):
        from partyline.adapters.raw import RawAdapter
        self.assertTrue(issubclass(RawAdapter, Adapter))


if __name__ == "__main__":
    unittest.main()
