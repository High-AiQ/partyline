"""Only the fixed extension origin is registered, with unpacked assets shipped in wheels/installers."""
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline_helper import native_install
from partyline_helper.chrome_identity import EXTENSION_ID, ORIGIN
from tests.test_helper_install import FakeRegistry


class NativeInstallTests(unittest.TestCase):
    def test_public_key_derives_exact_registered_id_and_minimal_permissions(self):
        manifest = json.loads(Path('partyline_chrome/manifest.json').read_text())
        digest = hashlib.sha256(base64.b64decode(manifest['key'])).hexdigest()[:32]
        self.assertEqual(''.join(chr(ord('a') + int(c, 16)) for c in digest), EXTENSION_ID)
        self.assertEqual(manifest['permissions'], ['debugger', 'tabs', 'nativeMessaging'])
        self.assertNotIn('host_permissions', manifest)
        self.assertNotIn('content_scripts', manifest)

    def test_registration_for_every_platform_is_per_user_and_removes_only_owned_assets(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            binary = home / 'PartylineChromeHost.exe'
            binary.write_text('fake executable')
            registry = FakeRegistry()
            for system in ('Windows', 'Linux', 'Darwin'):
                with patch.object(native_install, 'config_path', return_value=home / 'config/helper.json'), \
                        patch.object(native_install, 'host_executable', return_value=binary):
                    first = native_install.install(system, home, [str(home / 'helper.exe')], registry)
                    folder, manifest = native_install.paths(system, home)
                    value = json.loads(manifest.read_text())
                    self.assertEqual(value['allowed_origins'], [ORIGIN])
                    self.assertEqual(Path(value['path']), binary)
                    self.assertTrue((folder / 'worker.js').is_file())
                    self.assertFalse(list(folder.glob('*.test.js')))
                    self.assertEqual(native_install.install(system, home, [str(home / 'helper.exe')],
                                                           registry), first)
                    if system == 'Windows':
                        self.assertEqual(registry.values[(native_install.REGISTRY_KEY, '')], str(manifest))
                    native_install.uninstall(system, home, registry)
                    self.assertFalse(manifest.exists())
                    self.assertFalse(folder.exists())
                    self.assertTrue(binary.exists())
                    self.assertTrue(all(s.startswith('not present')
                                        for s in native_install.uninstall(system, home, registry)))
            self.assertFalse(registry.values)

    def test_launcher_discovery_supports_frozen_and_tool_launchers(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            self.assertIsNone(native_install.host_executable([str(home / 'helper')], 'Windows'))
            self.assertIn('missing', native_install.install('Windows', home, [str(home / 'helper')])[0])
            for name, system in [('PartylineChromeHost.exe', 'Windows'),
                                 ('partyline-chrome-host.exe', 'Windows'),
                                 ('partyline-chrome-host', 'Linux')]:
                path = home / name
                path.write_text('')
                self.assertEqual(native_install.host_executable([str(home / 'helper')], system), path)
                path.unlink()
