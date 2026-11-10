import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import tests
from partyline import process_exit, scope_sweep, startup_state


def unit(letter):
    return f"partyline-process-{letter * 32}.scope"


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


class SweepTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=tests._SANDBOX))
        self.stopped = []

    def group(self, name, events):
        path = self.root / "app" / name
        path.mkdir(parents=True, exist_ok=True)
        if events is not None:
            (path / "cgroup.events").write_text(events)
        return f"/app/{name}"

    def runner(self, names, groups, listing_code=0):
        def run(argv, **_):
            if "list-units" in argv:
                return done("".join(f"{name} loaded active running Memory scope\n" for name in names),
                            listing_code)
            shown = [f"Id={name}\nControlGroup={groups.get(name, '')}\n" for name in argv if name in groups]
            return done("\n".join(shown))
        return run

    def sweep(self, names, groups, keep=(), **kwargs):
        with patch.object(scope_sweep, "stop_scope", side_effect=self.stopped.append):
            return tests.REAL_SCOPE_SWEEP(
                keep, run=self.runner(names, groups, **kwargs), root=self.root, platform="linux")

    def test_stops_only_empty_unowned_scopes(self):
        names = [unit(c) for c in "abcdefg"]
        groups = {
            names[0]: self.group("empty", "populated 0\nfrozen 0\n"),
            names[1]: self.group("live", "populated 1\nfrozen 0\n"),
            names[2]: self.group("owned", "populated 0\n"),
            names[3]: "/app/removed",
            names[5]: "",
        }
        with self.assertLogs("partyline.scope_sweep", "INFO") as logs:
            count = self.sweep(names[:6] + ["not-a-partyline.scope"], groups, keep=[names[2], None])
        self.assertEqual(count, 2)
        self.assertEqual(self.stopped, [names[0], names[3]])
        self.assertIn("stopped 2 empty", logs.output[-1])

    def test_a_scope_with_any_process_is_never_stopped(self):
        busy = unit("a")
        groups = {busy: self.group("busy", "populated 1\n")}
        self.assertEqual(self.sweep([busy], groups), 0)
        self.assertEqual(self.stopped, [])
        self.assertFalse(scope_sweep.cgroup_empty("/app/busy", self.root))
        with patch.object(Path, "read_text", side_effect=PermissionError):
            self.assertFalse(scope_sweep.cgroup_empty("/app/busy", self.root))

    def test_nothing_listed_or_listing_failure_stops_nothing(self):
        self.assertEqual(self.sweep([], {}), 0)
        self.assertEqual(self.sweep([unit("a")], {}, listing_code=1), 0)
        self.assertEqual(self.stopped, [])

    def test_systemctl_trouble_is_logged_not_raised(self):
        with self.assertLogs("partyline.scope_sweep", "WARNING"):
            count = tests.REAL_SCOPE_SWEEP(run=Mock(side_effect=OSError("no systemctl")),
                                           platform="linux")
        self.assertEqual(count, 0)

    def test_other_platforms_do_nothing(self):
        run = Mock()
        self.assertEqual(tests.REAL_SCOPE_SWEEP(run=run, platform="darwin"), 0)
        run.assert_not_called()


class ScopeStopTest(unittest.TestCase):
    def test_release_stops_then_clears_failed_state(self):
        scope = process_exit.new_scope()
        with patch.object(process_exit.subprocess, "run") as run:
            process_exit.release_scope(scope)
            process_exit.stop_scope("other.scope")
            process_exit.stop_scope(None)
        self.assertEqual([call.args[0][2] for call in run.call_args_list], ["stop", "reset-failed"])
        self.assertIn("--no-block", run.call_args_list[0].args[0])

    def test_a_stop_that_cannot_run_is_logged(self):
        with patch.object(process_exit.subprocess, "run", side_effect=OSError("gone")), \
                self.assertLogs("partyline.process_exit", "WARNING"):
            process_exit.stop_scope(process_exit.new_scope())

    def test_named_scopes_still_keep_failed_results(self):
        from partyline import process_memory
        with patch.object(process_memory.shutil, "which", return_value="systemd-run"):
            argv = process_memory.scope_argv(["tool"], "4G", unit=process_exit.new_scope())
        self.assertNotIn("--collect", argv)


class ExitStopsScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_unreadable_diagnostics_still_stop_the_scope(self):
        adapter = SimpleNamespace(memory_scope=process_exit.new_scope(), memory_limit="4G",
                                  _stopping=False, on_status=AsyncMock(),
                                  att={"name": "worker"}, post=AsyncMock())
        evidence = process_exit.ProcessExit(code=-15, limit_bytes=1024)
        with patch.object(process_exit, "inspect_exit", return_value=evidence), \
                patch.object(process_exit, "release_scope") as release, \
                patch.object(process_exit, "stop_scope") as stop:
            await process_exit.report_exit(adapter, -15)
        release.assert_not_called()
        stop.assert_called_once_with(adapter.memory_scope)


class StartupAndTestHygieneTest(unittest.IsolatedAsyncioTestCase):
    async def test_startup_sweeps_while_sparing_live_attachment_scopes(self):
        live = SimpleNamespace(memory_scope=unit("a"))
        runtime = SimpleNamespace(db=Mock(), live={"att": live})
        sweep = Mock(return_value=0)
        with patch.object(startup_state, "post_interruption_notices", AsyncMock()), \
                patch.object(startup_state, "sweep_orphaned_worktrees"), \
                patch.object(startup_state, "reap_legacy_temp"), \
                patch.object(startup_state, "reap_previous_tmp_root"), \
                patch.object(scope_sweep, "sweep_empty_scopes", sweep):
            await startup_state.engage_startup(runtime)
            sweep.side_effect = RuntimeError("boom")
            with self.assertLogs("partyline.startup_state", "ERROR"):
                await startup_state.engage_startup(runtime)
        sweep.assert_called_with([unit("a")])

    def test_ordinary_tests_never_sweep_and_stop_what_they_name(self):
        self.assertIsNot(scope_sweep.sweep_empty_scopes, tests.REAL_SCOPE_SWEEP)
        self.assertEqual(scope_sweep.sweep_empty_scopes(["x"]), 0)
        name = process_exit.new_scope()
        self.assertIn(name, tests.SCOPES_CREATED)
        run = Mock()
        self.assertGreaterEqual(tests.stop_created_scopes(run), 1)
        self.assertIn(name, run.call_args.args[0])
        tests.stop_created_scopes(Mock(side_effect=OSError("no systemctl")))
