"""Execute the freeze recipe against build doubles, including the console native host."""
import re
import runpy
import sys
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class ExtensionPackagingTests(unittest.TestCase):
    def test_windows_freeze_includes_native_console_host_and_all_production_extension_assets(self):
        root = Path.cwd()
        spec = root / 'packaging/windows/PartylineHelper.spec'
        analysis = Mock(side_effect=lambda *a, **kw:
                        SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[]))
        exe, collect = Mock(side_effect=lambda *a, **kw: kw), Mock()
        hooks = SimpleNamespace(collect_submodules=lambda name: [name])
        versions = SimpleNamespace(main=Mock())
        original = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), original))
        with patch.dict(sys.modules, {'PyInstaller.utils.hooks': hooks, 'make_version_info': versions}):
            runpy.run_path(str(spec), init_globals={'SPECPATH': str(spec.parent), 'Analysis': analysis,
                                                   'PYZ': Mock(), 'EXE': exe, 'COLLECT': collect})
        self.assertEqual(analysis.call_count, 2)
        names = {Path(source).name for source, dest in analysis.call_args_list[0].kwargs['datas']}
        self.assertEqual(names, {path.name for path in (root / 'partyline_chrome').glob('*.js')
                                 if not path.name.endswith('.test.js')} | {'manifest.json'})
        self.assertTrue(all((root / 'partyline_chrome' / name).exists() for name in names))
        self.assertFalse(exe.call_args_list[0].kwargs['console'])
        self.assertTrue(exe.call_args_list[1].kwargs['console'])
        self.assertEqual(exe.call_args_list[1].kwargs['name'], 'PartylineChromeHost')
        self.assertIn('native_entry.py', analysis.call_args_list[1].args[0][0])
        collect.assert_called_once()

    def test_wheel_and_windows_packages_include_all_production_extension_files_and_worker_imports(self):
        root = Path.cwd()
        extension = root / 'partyline_chrome'
        production = {path.name for path in extension.glob('*.js') if not path.name.endswith('.test.js')}
        config = tomllib.loads((root / 'pyproject.toml').read_text())
        wheel = config['tool']['hatch']['build']['targets']['wheel']
        wheel_names = {Path(source).name for source in wheel['force-include']
                       if source.startswith('partyline_chrome/')}
        spec = root / 'packaging/windows/PartylineHelper.spec'
        analysis = Mock(side_effect=lambda *a, **kw:
                        SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[]))
        with patch.dict(sys.modules, {
            'PyInstaller.utils.hooks': SimpleNamespace(collect_submodules=lambda name: [name]),
            'make_version_info': SimpleNamespace(main=Mock()),
        }):
            runpy.run_path(str(spec), init_globals={
                'SPECPATH': str(spec.parent), 'Analysis': analysis, 'PYZ': Mock(),
                'EXE': Mock(), 'COLLECT': Mock(),
            })
        windows_names = {Path(source).name for source, _ in analysis.call_args_list[0].kwargs['datas']}
        self.assertEqual(wheel_names, production | {'manifest.json'})
        self.assertEqual(windows_names, production | {'manifest.json'})

        reached = set()
        pending = ['worker.js']
        while pending:
            name = pending.pop()
            if name in reached:
                continue
            reached.add(name)
            source = (extension / name).read_text()
            pending.extend(imported for imported in re.findall(
                r"\bimport\s+(?:[^;]*?\s+from\s+)?['\"]\./([^'\"]+\.js)['\"]", source
            ) if imported not in reached)
        self.assertTrue(reached <= wheel_names)
        self.assertTrue(reached <= windows_names)
