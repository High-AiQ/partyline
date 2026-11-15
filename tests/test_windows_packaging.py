"""The Windows packaging files, checked as text on Linux: the invariants a first real build must not lose."""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

from partyline.helper_release import installer_info
from partyline_helper.chrome_identity import HOST

ROOT = Path(__file__).resolve().parent.parent
ISS = (ROOT / "packaging/windows/installer.iss").read_text()
SPEC = (ROOT / "packaging/windows/PartylineHelper.spec").read_text()
WORKFLOW = (ROOT / ".github/workflows/windows-installer.yml").read_text()
CHECKS = (ROOT / ".github/workflows/checks.yml").read_text()
VERSION_SCRIPT = ROOT / "packaging/windows/make_version_info.py"


def section(name):
    match = re.search(rf"^\[{name}\]\n(.*?)(?=^\[|\Z)", ISS, re.S | re.M)
    return match.group(1) if match else ""


def parameters(name):
    return re.findall(r'Parameters: "([^"]+)"', section(name))


class InstallerScriptTests(unittest.TestCase):
    def test_it_installs_per_user_without_elevation(self):
        self.assertIn("PrivilegesRequired=lowest", ISS)
        self.assertRegex(ISS, r"PrivilegesRequiredOverridesAllowed=\s*\n")  # no switch to all-users
        self.assertRegex(ISS, r"DefaultDirName=\{localappdata\}\\")
        self.assertNotIn("{autopf}", ISS)
        self.assertNotIn("{commonpf", ISS)
        self.assertNotIn("HKLM", ISS)

    def test_the_installer_file_name_carries_the_version(self):
        self.assertIn("OutputBaseFilename=PartylineHelper-Setup-{#AppVersion}\n", ISS)
        self.assertNotRegex(ISS, r"OutputBaseFilename=PartylineHelper-Setup\s*\n")  # no fixed name
        self.assertIn("/DAppVersion=$env:VERSION", WORKFLOW)  # the workflow passes the helper version in
        self.assertIn("PartylineHelper-Setup-$env:VERSION.exe", WORKFLOW)
        self.assertNotIn("latest/download", WORKFLOW + ISS)

    def test_the_installer_and_the_installed_exe_carry_windows_version_resources(self):
        self.assertIn("VersionInfoVersion={#VersionNumbers}", ISS)
        self.assertIn('#define VersionNumbers AppVersion + ".0"', ISS)
        self.assertIn("VersionInfoProductVersion={#AppVersion}", ISS)
        self.assertRegex(SPEC, r"\n\s+version=VERSION_FILE,")  # PyInstaller embeds the exe's version resource
        self.assertNotIn("os.path.exists(VERSION_FILE)", SPEC)  # never skipped when missing
        self.assertNotIn("version=None", SPEC)
        # The spec writes the file itself, before the EXE is declared, so every build path (CI, local) has it.
        self.assertIn("from make_version_info import main as write_version_info", SPEC)
        self.assertLess(SPEC.index("write_version_info([VERSION_FILE])"), SPEC.index("exe = EXE("))

    def test_the_download_url_and_file_name_agree_with_the_build(self):
        info = installer_info("1.2.0")
        self.assertEqual(info["filename"], "PartylineHelper-Setup-1.2.0.exe")
        for template in ("PartylineHelper-Setup-{#AppVersion}", "PartylineHelper-Setup-$env:VERSION"):
            self.assertEqual(template.replace("{#AppVersion}", "1.2.0").replace("$env:VERSION", "1.2.0")
                             + ".exe", info["filename"])
        self.assertTrue(info["url"].endswith("/helper-v1.2.0/" + info["filename"]))  # tag = helper-v<ver>

    def test_install_steps_run_in_order_stop_then_register_then_start(self):
        self.assertEqual(parameters("Run"), ["stop", "install", "start"])
        self.assertEqual(parameters("UninstallRun"), ["stop", "uninstall"])
        for line in section("Run").splitlines():
            if line.startswith("Filename"):
                self.assertIn("runhidden", line)

    def test_a_silent_install_only_starts_the_helper_when_asked(self):
        start = [line for line in section("Run").splitlines() if 'Parameters: "start"' in line][0]
        self.assertIn("Check: ShouldStartHelper", start)
        self.assertRegex(ISS, r"WizardSilent\) or \(ExpandConstant\('\{param:START\|0\}'\) = '1'\)")

    def test_an_upgrade_stops_the_installed_helper_before_replacing_files(self):
        code = ISS[ISS.index("[Code]"):]
        self.assertIn("function PrepareToInstall", code)
        self.assertRegex(code, r"Exec\(Exe, 'stop'")
        self.assertIn("and (Code = 0)", code)  # a failed stop is not ignored ...
        prepare = code[code.index("function PrepareToInstall"):]
        self.assertRegex(prepare, r"if not HelperStopped then\n\s+Result := '")  # ... it aborts the install
        uninstall = code[code.index("function InitializeUninstall"):]
        self.assertIn("Result := HelperStopped;", uninstall)  # ... and the uninstall
        self.assertIn("CloseApplications=no", ISS)

    def test_an_upgrade_from_a_helper_without_the_chrome_host_never_asks_it_to_pause_chrome(self):
        code = ISS[ISS.index("function HelperStopped"):ISS.index("function PrepareToInstall")]
        suspend = code[code.index("RegKeyExists"):code.index("'suspend-chrome'")]
        self.assertIn("Software\\Google\\Chrome\\NativeMessagingHosts\\" + HOST, suspend)
        self.assertLess(code.index("'stop'"), code.index("RegKeyExists"))  # the stop is always required

    def test_it_has_a_start_menu_entry_and_an_uninstaller(self):
        self.assertIn("{autoprograms}", section("Icons"))
        self.assertIn("UninstallDisplayIcon", ISS)  # the Apps list entry comes from Inno's own uninstaller
        self.assertIn(r'Source: "..\..\dist\PartylineHelper', section("Files"))

    def test_signing_is_one_define_away(self):
        self.assertRegex(ISS, r"#ifdef SIGN\nSignTool=signtool\nSignedUninstaller=yes\n#endif")
        self.assertGreater(ISS.index("SignTool="), ISS.index("#ifdef SIGN"))  # off unless SIGN is defined


class FreezeSpecTests(unittest.TestCase):
    def test_it_is_windowed_onedir_and_collects_the_runtime_chosen_backends(self):
        self.assertIn("console=False", SPEC)
        self.assertIn("exclude_binaries=True", SPEC)  # onedir
        self.assertIn("COLLECT(", SPEC)
        for package in ("partyline_helper", "pynput", "pystray", "windows_capture"):
            self.assertIn(f'collect_submodules("{package}")', SPEC)
        self.assertNotIn('copy_metadata("partyline")', SPEC)
        self.assertIn("uac_admin=False", SPEC)

    def test_helper_extra_lists_every_dependency_the_spec_collects(self):
        extras = re.search(r"^helper = \[(.*?)\]", (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        for package in ("windows-capture", "pynput", "pystray", "websockets", "pillow"):
            self.assertIn(package, extras)


class VersionResourceTests(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location("make_version_info", VERSION_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_version_file_carries_the_helper_version_in_every_field(self):
        text = self.load().version_info("1.2.0")
        self.assertIn("filevers=(1, 2, 0, 0)", text)
        self.assertIn("prodvers=(1, 2, 0, 0)", text)
        self.assertIn("StringStruct('FileVersion', '1.2.0')", text)
        self.assertIn("StringStruct('ProductVersion', '1.2.0')", text)
        self.assertIn("StringStruct('OriginalFilename', 'PartylineHelper.exe')", text)

    def test_a_short_or_odd_version_still_gives_four_numbers(self):
        module = self.load()
        self.assertEqual(module.four_part("3"), (3, 0, 0, 0))
        self.assertEqual(module.four_part("1.2.3.4.5"), (1, 2, 3, 4))

    def test_it_writes_the_file_for_the_current_helper_version(self):
        from partyline_helper import __version__

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sub" / "version_info.txt"
            self.load().main([str(out)])
            self.assertIn(f"StringStruct('ProductVersion', '{__version__}')", out.read_text(encoding="utf-8"))


class WorkflowTests(unittest.TestCase):
    def test_it_builds_on_windows_for_helper_prs_and_tags(self):
        self.assertIn("runs-on: windows-latest", WORKFLOW)
        self.assertNotIn("branches: [main]", WORKFLOW)
        self.assertRegex(WORKFLOW, r'tags: \["helper-v\*"\]')
        self.assertIn("actions/upload-artifact@v4", WORKFLOW)
        self.assertIn("name: PartylineHelper-Setup-${{ env.VERSION }}-${{ github.sha }}", WORKFLOW)
        self.assertIn("path: build/installer/PartylineHelper-Setup-${{ env.VERSION }}.exe", WORKFLOW)

    def test_only_a_tag_creates_a_release_asset(self):
        step = WORKFLOW[WORKFLOW.index("name: attach to the release"):]
        self.assertIn("if: ${{ env.TAG != '' }}", step)
        self.assertIn("gh release upload", step)
        self.assertIn('"build/installer/PartylineHelper-Setup-$env:VERSION.exe"', step)  # the versioned file
        self.assertEqual(step.count("gh release upload"), 1)  # no fixed-name alias
        self.assertNotIn("PartylineHelper-Setup.exe", step)
        self.assertIn("startsWith(github.ref, 'refs/tags/helper-v')", WORKFLOW)

    def test_tags_made_by_the_tag_job_dispatch_the_build(self):
        self.assertIn("gh workflow run windows-installer.yml", CHECKS)
        self.assertIn("actions: write", CHECKS)
        self.assertIn("workflow_dispatch:", WORKFLOW)

    def test_signing_steps_are_present_and_off_until_enabled(self):
        steps = re.findall(r"- name: (sign [^\n]+)\n\s+if: (.+)\n", WORKFLOW)
        self.assertEqual([name for name, _ in steps], ["sign the helper exe", "sign the installer"])
        for _, condition in steps:
            self.assertEqual(condition, "${{ vars.WINDOWS_SIGNING == 'true' }}")
        self.assertLess(WORKFLOW.index("sign the helper exe"), WORKFLOW.index("build the installer"))
        self.assertGreater(WORKFLOW.index("sign the installer"), WORKFLOW.index("build the installer"))

    def test_the_smoke_test_does_not_fail_on_its_last_expected_failure(self):
        step = WORKFLOW[WORKFLOW.index("name: install and uninstall silently"):]
        step = step.split("\n      - ", 1)[0].rstrip()
        self.assertTrue(step.splitlines()[-1].strip().startswith("$global:LASTEXITCODE = 0"))

    def test_the_frozen_build_is_checked_before_it_is_packed(self):
        self.assertLess(WORKFLOW.index("selfcheck"), WORKFLOW.index("build the installer"))
        self.assertIn("silently", WORKFLOW)
        self.assertIn("unins000.exe", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
