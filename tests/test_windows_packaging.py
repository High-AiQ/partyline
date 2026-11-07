"""The Windows packaging files, checked as text on Linux: the invariants a first real build must not lose."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISS = (ROOT / "packaging/windows/installer.iss").read_text()
SPEC = (ROOT / "packaging/windows/PartylineHelper.spec").read_text()
WORKFLOW = (ROOT / ".github/workflows/windows-installer.yml").read_text()
CHECKS = (ROOT / ".github/workflows/checks.yml").read_text()
DOWNLOAD = (ROOT / "frontend/src/lib/helper-installer.ts").read_text()


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

    def test_the_output_name_matches_the_download_link(self):
        link = re.search(r"/releases/latest/download/([\w.-]+)\"", DOWNLOAD).group(1)
        self.assertEqual(re.search(r"OutputBaseFilename=(\S+)", ISS).group(1) + ".exe", link)
        self.assertIn(link, WORKFLOW)

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
        for package in ("partyline_helper", "pynput", "pystray", "mss"):
            self.assertIn(f'collect_submodules("{package}")', SPEC)
        self.assertIn('copy_metadata("partyline")', SPEC)  # the version the helper reports
        self.assertIn("uac_admin=False", SPEC)

    def test_helper_extra_lists_every_dependency_the_spec_collects(self):
        extras = re.search(r"^helper = \[(.*?)\]", (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        for package in ("mss", "pynput", "pystray", "websockets", "pillow"):
            self.assertIn(package, extras)


class WorkflowTests(unittest.TestCase):
    def test_it_builds_on_windows_for_main_prs_and_tags(self):
        self.assertIn("runs-on: windows-latest", WORKFLOW)
        self.assertRegex(WORKFLOW, r"branches: \[main\]")
        self.assertRegex(WORKFLOW, r'tags: \["v\*"\]')
        self.assertIn("actions/upload-artifact@v4", WORKFLOW)
        self.assertIn("path: build/installer/PartylineHelper-Setup.exe", WORKFLOW)

    def test_only_a_tag_creates_a_release_asset(self):
        step = WORKFLOW[WORKFLOW.index("name: attach to the release"):]
        self.assertIn("if: ${{ env.TAG != '' }}", step)
        self.assertIn("gh release upload", step)
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", WORKFLOW)

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
        step = step[:step.index("- uses: actions/upload-artifact")].rstrip()
        self.assertTrue(step.splitlines()[-1].strip().startswith("$global:LASTEXITCODE = 0"))

    def test_the_frozen_build_is_checked_before_it_is_packed(self):
        self.assertLess(WORKFLOW.index("selfcheck"), WORKFLOW.index("build the installer"))
        self.assertIn("silently", WORKFLOW)
        self.assertIn("unins000.exe", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
