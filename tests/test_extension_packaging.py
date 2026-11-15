"""Execute the freeze recipe against build doubles, including the console native host."""
import runpy
import sys
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
        self.assertEqual(names, {'manifest.json', 'worker.js', 'relay.js', 'attachments.js', 'wire.js'})
        self.assertTrue(all((root / 'partyline_chrome' / name).exists() for name in names))
        self.assertFalse(exe.call_args_list[0].kwargs['console'])
        self.assertTrue(exe.call_args_list[1].kwargs['console'])
        self.assertEqual(exe.call_args_list[1].kwargs['name'], 'PartylineChromeHost')
        self.assertIn('native_entry.py', analysis.call_args_list[1].args[0][0])
        collect.assert_called_once()
