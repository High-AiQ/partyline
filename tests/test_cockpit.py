"""Unit coverage for the cockpit preflight.

The checks that matter here are the ones that answer "is the thing on disk
actually the thing that was built" — a question with a real wrong answer that
has already cost a restart. They are pure functions over a directory, so they
are tested against temp directories rather than a git fixture.
"""

import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cockpit import (  # noqa: E402
    CommandResult,
    Finding,
    PendingPlanInspection,
    arm_restart,
    check_adapter_tests,
    check_bundle_present,
    check_tree_clean,
    referenced_assets,
    resolve_line,
    restart_needed,
    schedule_restart_plan,
    parse_systemd_exec_start,
)
from partyline.contracts import ConversationResponse


class StaticTree:
    """A throwaway checkout with a `partyline/static/` in a chosen state."""

    def __init__(self, index_html=None, assets=()):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        static = self.root / "partyline" / "static"
        (static / "assets").mkdir(parents=True)
        if index_html is not None:
            (static / "index.html").write_text(index_html)
        for name in assets:
            (static / "assets" / name).write_text("/* built */")

    def __enter__(self):
        return self.root

    def __exit__(self, *exc):
        self.dir.cleanup()


INDEX = ('<!DOCTYPE html><html><head>'
         '<script type="module" src="/assets/index-ABC123.js"></script>'
         '<link rel="stylesheet" href="/assets/index-DEF456.css">'
         '</head><body><div id="root"></div></body></html>')


class ReferencedAssetsTest(unittest.TestCase):
    def test_it_finds_every_hashed_asset_the_page_asks_for(self):
        with StaticTree(INDEX) as root:
            found = referenced_assets(root / "partyline" / "static")
        self.assertEqual(sorted(found), ["index-ABC123.js", "index-DEF456.css"])

    def test_a_missing_index_is_no_references_rather_than_a_crash(self):
        with StaticTree(index_html=None) as root:
            self.assertEqual(referenced_assets(root / "partyline" / "static"), [])

    def test_it_ignores_urls_that_are_not_assets(self):
        page = '<link href="https://fonts.googleapis.com/css2?family=X"><script src="/assets/a.js">'
        with StaticTree(page) as root:
            self.assertEqual(referenced_assets(root / "partyline" / "static"), ["a.js"])


class BundlePresentTest(unittest.TestCase):
    def test_a_complete_bundle_passes(self):
        with StaticTree(INDEX, ["index-ABC123.js", "index-DEF456.css"]) as root:
            self.assertEqual(check_bundle_present(root, "workbench"), [])

    def test_no_built_frontend_at_all_is_reported(self):
        with StaticTree(index_html=None) as root:
            findings = check_bundle_present(root, "cockpit")
        self.assertEqual(len(findings), 1)
        self.assertIn("no built frontend", findings[0].problem)
        self.assertIn("npm", findings[0].fix)

    def test_a_referenced_asset_that_is_missing_is_reported(self):
        """The blank-page case: the server starts, the HTML is served, and the
        browser silently fails to fetch a script nobody committed."""
        with StaticTree(INDEX, ["index-ABC123.js"]) as root:
            findings = check_bundle_present(root, "cockpit")
        self.assertEqual(len(findings), 1)
        self.assertIn("index-DEF456.css", findings[0].problem)
        self.assertNotIn("index-ABC123.js", findings[0].problem)

    def test_the_label_names_which_checkout_is_wrong(self):
        with StaticTree(index_html=None) as root:
            self.assertIn("cockpit", check_bundle_present(root, "cockpit")[0].problem)
            self.assertIn("workbench", check_bundle_present(root, "workbench")[0].problem)


class TreeCleanTest(unittest.TestCase):
    """`check_tree_clean` shells out to git; these stub it to pin the flags."""

    def setUp(self):
        import scripts.cockpit as cockpit

        self.cockpit = cockpit
        self.real_git = cockpit.git
        self.calls = []

    def tearDown(self):
        self.cockpit.git = self.real_git

    def stub(self, output):
        def fake(*args, **kwargs):
            self.calls.append(args)
            return output
        self.cockpit.git = fake

    def test_the_workbench_counts_untracked_files(self):
        # A new source file nobody committed cannot reach the cockpit, which is
        # the whole thing this script exists to catch.
        self.stub("?? frontend/src/lib/new.js")
        self.assertTrue(check_tree_clean(Path("/tmp"), "workbench", untracked=True))
        self.assertNotIn("--untracked-files=no", self.calls[0])

    def test_the_cockpit_ignores_untracked_files(self):
        # It is a deployment target: it accumulates logs and databases, and a
        # stray cockpit.log must not look like unfinished work.
        self.stub("")
        self.assertEqual(check_tree_clean(Path("/tmp"), "cockpit", untracked=False), [])
        self.assertIn("--untracked-files=no", self.calls[0])

    def test_a_modified_tracked_file_stops_either_checkout(self):
        self.stub(" M partyline/server.py")
        for untracked in (True, False):
            self.assertTrue(check_tree_clean(Path("/tmp"), "cockpit", untracked=untracked))


class AdapterStoreTest(unittest.TestCase):
    """The server executes imported adapters, so they are part of the deployment.

    A restart once ran an adapter that existed only as an uncommitted local
    edit: the running behaviour was in no repository, the preflight said
    "ready", and re-importing would have reverted the fix without a trace. Same
    failure as a cockpit three commits behind — the code being run was not the
    code anyone had reviewed.
    """

    def setUp(self):
        import scripts.cockpit as cockpit

        self.cockpit = cockpit
        self.real_git = cockpit.git

    def tearDown(self):
        self.cockpit.git = self.real_git

    def stub(self, responses):
        """`responses` maps a git subcommand to its output, or an exception."""
        def fake(*args, **kwargs):
            answer = responses.get(args[0], "")
            if isinstance(answer, Exception):
                raise answer
            return answer.pop(0) if isinstance(answer, list) else answer
        self.cockpit.git = fake

    def test_no_store_is_not_a_finding(self):
        nowhere = Path("/nonexistent/store")
        self.assertEqual(self.cockpit.check_adapter_store(nowhere, nowhere), [])

    def test_a_dirty_adapter_checkout_blocks_a_restart(self):
        self.stub({"status": " M adapters/codex/adapter.py", "branch": "  origin/master"})
        with tempfile.TemporaryDirectory() as store:
            (Path(store) / "partyline-adapters" / ".git").mkdir(parents=True)
            findings = self.cockpit.check_adapter_store(Path(store), Path("/nonexistent/sources"))
        self.assertTrue(findings)
        self.assertIn("partyline-adapters", findings[0].problem)

    def test_a_clean_published_adapter_checkout_passes(self):
        # Detached at a commit some remote has: the normal, correct state of a
        # deployment target. Demanding a tracking branch here was this guard's
        # own first false positive.
        self.stub({"status": "", "branch": "  origin/master", "rev-parse": "samesha"})
        with tempfile.TemporaryDirectory() as store:
            (Path(store) / "partyline-adapters" / ".git").mkdir(parents=True)
            self.assertEqual(self.cockpit.check_adapter_store(Path(store), Path("/nonexistent/sources")), [])

    def test_the_top_level_check_actually_invokes_drift(self):
        """The helper existed and was tested for a while before anything called
        it. A tested helper nobody invokes is decorative: it proves the function
        works, not that the preflight uses it."""
        self.stub({"status": "", "branch": "  origin/master",
                   "rev-parse": ["installed", "source"]})
        with tempfile.TemporaryDirectory() as store, tempfile.TemporaryDirectory() as root:
            (Path(store) / "partyline-adapters" / ".git").mkdir(parents=True)
            (Path(root) / "partyline-adapters" / ".git").mkdir(parents=True)
            findings = self.cockpit.check_adapter_store(Path(store), Path(root))
        self.assertTrue(any("its source at" in f.problem for f in findings), findings)

    def test_a_missing_source_checkout_is_not_a_finding(self):
        # Deploying without the source present is legitimate; only disagreement
        # between two present copies is evidence of anything.
        self.stub({"status": "", "branch": "  origin/master", "rev-parse": "same"})
        with tempfile.TemporaryDirectory() as store, tempfile.TemporaryDirectory() as root:
            (Path(store) / "partyline-adapters" / ".git").mkdir(parents=True)
            self.assertEqual(self.cockpit.check_adapter_store(Path(store), Path(root)), [])

    def test_a_commit_no_remote_has_blocks_a_restart(self):
        self.stub({"status": "", "branch": "", "rev-parse": "same"})
        with tempfile.TemporaryDirectory() as store, tempfile.TemporaryDirectory() as root:
            (Path(store) / "partyline-adapters" / ".git").mkdir(parents=True)
            findings = self.cockpit.check_adapter_store(Path(store), Path(root))
        self.assertTrue(any("no remote has" in f.problem for f in findings), findings)

    def test_drift_between_installed_and_source_is_reported(self):
        self.stub({"rev-parse": ["installedsha", "sourcesha"]})
        findings = self.cockpit.check_adapter_drift(Path("/installed"), Path("/source"))
        self.assertEqual(len(findings), 1)
        self.assertIn("re-import", findings[0].fix)

    def test_matching_installed_and_source_is_silent(self):
        self.stub({"rev-parse": "samesha"})
        self.assertEqual(self.cockpit.check_adapter_drift(Path("/installed"), Path("/source")), [])


class AdapterTestEnforcementTest(unittest.TestCase):
    def test_a_missing_enforcing_runner_blocks_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            findings = check_adapter_tests(Path(directory))
        self.assertEqual(len(findings), 1)
        self.assertIn("run_tests.py", findings[0].problem)

    def test_a_green_runner_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "run_tests.py").write_text("raise SystemExit(0)\n")
            self.assertEqual(check_adapter_tests(source), [])

    def test_a_red_runner_reports_its_adapter_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "run_tests.py").write_text(
                "import sys\nprint('FAIL: pi has no tests', file=sys.stderr)\nraise SystemExit(1)\n"
            )
            findings = check_adapter_tests(source)
        self.assertEqual(len(findings), 1)
        self.assertIn("pi has no tests", findings[0].problem)


class PendingPlanTest(unittest.TestCase):
    """A planned restart that never happened must not stay invisible.

    Two of them did. A supervisor reaped before it fired, then a systemd unit
    whose inline quoting broke its own generation check — both left a plan
    persisted at `attempt_count` 0 with the old server still serving, and both
    were discovered by a person asking why a version number had not changed.
    The second sat unnoticed for ten hours.
    """

    NOW = 1_000_000.0

    def plan(self, **overrides):
        return {"attempt_count": 0, "created_at": self.NOW - 1, **overrides}

    def test_no_plan_is_not_a_finding(self):
        self.assertEqual(self.cockpit_check(None), [])

    def test_a_fresh_plan_is_a_restart_in_flight_not_a_failure(self):
        # Arming waits 90 seconds; complaining before then would train people
        # to ignore this.
        self.assertEqual(self.cockpit_check(self.plan(created_at=self.NOW - 30)), [])

    def test_a_plan_unclaimed_for_hours_is_reported(self):
        findings = self.cockpit_check(self.plan(created_at=self.NOW - 36_000))
        self.assertEqual(len(findings), 1)
        self.assertIn("600 minutes", findings[0].problem)
        self.assertIn("journalctl", findings[0].fix)

    def test_a_claimed_plan_is_not_stale_however_old(self):
        """The trigger fired; whatever happened next is the coordinator's
        business and has its own reporting. This check is only about a restart
        that never started."""
        old = self.plan(attempt_count=1, created_at=self.NOW - 36_000)
        self.assertEqual(self.cockpit_check(old), [])

    @staticmethod
    def cockpit_check(plan):
        import scripts.cockpit as cockpit

        return cockpit.check_pending_plan(PendingPlanTest.NOW, plan)


class PendingPlanInspectionTest(unittest.TestCase):
    def test_missing_database_has_no_plan_and_no_finding(self):
        import scripts.cockpit as cockpit

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.db"
            inspected = cockpit.inspect_pending_plan(database)
        self.assertIsNone(inspected.plan)
        self.assertEqual(inspected.findings, [])
        self.assertFalse(database.exists(), "read-only inspection created the database")

    def test_existing_plan_is_read_without_mutating_its_schema(self):
        import scripts.cockpit as cockpit

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "partyline.db"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE restart_plan("
                "singleton INTEGER PRIMARY KEY, conversation_id TEXT, token TEXT, mode TEXT, "
                "attempt_count INTEGER, created_at REAL)"
            )
            connection.execute(
                "INSERT INTO restart_plan VALUES(1,'line','token','automatic',0,123)"
            )
            connection.commit()
            before = connection.execute("PRAGMA schema_version").fetchone()[0]
            connection.close()

            inspected = cockpit.inspect_pending_plan(database)

            connection = sqlite3.connect(database)
            after = connection.execute("PRAGMA schema_version").fetchone()[0]
            columns = [row[1] for row in connection.execute("PRAGMA table_info(restart_plan)")]
            connection.close()
        self.assertEqual(inspected.plan["conversation_id"], "line")
        self.assertEqual(before, after)
        self.assertEqual(
            columns,
            ["singleton", "conversation_id", "token", "mode", "attempt_count", "created_at"],
            "preflight migrated the database it was meant only to inspect",
        )

    def test_unreadable_existing_database_is_an_actionable_finding(self):
        import scripts.cockpit as cockpit

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "broken.db"
            database.write_text("not sqlite")
            inspected = cockpit.inspect_pending_plan(database)
        self.assertIsNone(inspected.plan)
        self.assertEqual(len(inspected.findings), 1)
        self.assertIn("cannot be inspected", inspected.findings[0].problem)
        self.assertIn(str(database), inspected.findings[0].fix)


class ArmRestartTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cockpit = Path(self.directory.name)
        for relative in (
            "scripts/restart_server.py",
            ".venv/bin/python3",
            ".venv/bin/partyline",
        ):
            path = self.cockpit / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("present")
        self.calls = []

    def tearDown(self):
        self.directory.cleanup()

    @property
    def inspection(self):
        return PendingPlanInspection(
            {
                "conversation_id": "line-1",
                "token": "token",
                "mode": "automatic",
                "attempt_count": 0,
                "created_at": 1,
            },
            [],
        )

    def fake_run(self, args):
        self.calls.append(args)
        if args[0] == "systemd-run":
            return CommandResult(0, "scheduled")
        if args[:3] == ["systemctl", "--user", "show"] and args[3].endswith(".timer"):
            return CommandResult(
                0,
                "LoadState=loaded\nActiveState=active\nSubState=waiting\n"
                "Triggers=partyline-restart-test.service\n",
            )
        if args[:3] == ["systemctl", "--user", "list-timers"]:
            return CommandResult(
                0,
                "Thu 2026-08-06 19:30:00 EDT 1min - - "
                "partyline-restart-test.timer partyline-restart-test.service\n",
            )
        if args[:3] == ["systemctl", "--user", "show"]:
            python = str(self.cockpit / ".venv/bin/python3")
            service_argv = self.calls[0][self.calls[0].index(python) :]
            return CommandResult(
                0,
                "ExecStart={ path=/python ; argv[]=" + " ".join(service_argv) + " "
                "; ignore_errors=no ; start_time=[n/a] ; }",
            )
        return CommandResult(0)

    def test_arm_schedules_the_reviewed_script_without_inline_shell(self):
        result = arm_restart(
            self.cockpit,
            42,
            90,
            "http://127.0.0.1:8642",
            unit="partyline-restart-test",
            run=self.fake_run,
            inspection=self.inspection,
            generation=lambda _pid: "1234",
        )
        self.assertEqual(result, 0)
        scheduled = self.calls[0]
        self.assertEqual(scheduled[0], "systemd-run")
        self.assertNotIn("/bin/bash", scheduled)
        self.assertIn(str(self.cockpit / "scripts/restart_server.py"), scheduled)
        self.assertIn("--failure-ws", scheduled)
        self.assertIn("ws://127.0.0.1:8642/ws/line-1", scheduled)
        self.assertTrue(any(call[:3] == ["systemctl", "--user", "list-timers"]
                            for call in self.calls), "arm never read its timer back")

    def test_an_unverified_timer_is_stopped_and_refused(self):
        def missing_timer(args):
            self.calls.append(args)
            if args[0] == "systemd-run":
                return CommandResult(0, "scheduled")
            return CommandResult(0, "")

        result = arm_restart(
            self.cockpit,
            42,
            90,
            "http://127.0.0.1:8642",
            unit="partyline-restart-test",
            run=missing_timer,
            inspection=self.inspection,
            generation=lambda _pid: "1234",
        )
        self.assertEqual(result, 1)
        self.assertIn(
            ["systemctl", "--user", "stop", "partyline-restart-test.timer"],
            self.calls,
        )

    def test_explicit_server_config_is_preflighted_and_read_back(self):
        config = self.cockpit / "cockpit.toml"
        config.write_text(
            "[server]\nhost = '0.0.0.0'\nport = 8642\n\n[instance]\nname = 'Cockpit'\n"
        )
        result = arm_restart(
            self.cockpit,
            42,
            90,
            "http://127.0.0.1:8642",
            unit="partyline-restart-test",
            server_config=config,
            run=self.fake_run,
            inspection=self.inspection,
            generation=lambda _pid: "1234",
        )
        self.assertEqual(result, 0)
        scheduled = self.calls[0]
        self.assertEqual(scheduled[scheduled.index("--server-config") + 1], str(config.resolve()))

    def test_invalid_server_config_refuses_before_scheduling(self):
        config = self.cockpit / "invalid.toml"
        config.write_text("[server]\nport = 0\n")
        result = arm_restart(
            self.cockpit,
            42,
            90,
            "http://127.0.0.1:8642",
            server_config=config,
            run=self.fake_run,
            inspection=self.inspection,
            generation=lambda _pid: "1234",
        )
        self.assertEqual(result, 1)
        self.assertEqual(self.calls, [])

    def test_missing_failure_warning_argument_refuses_to_claim_armed(self):
        def incomplete_readback(args):
            result = self.fake_run(args)
            if args[:3] == ["systemctl", "--user", "show"] and args[3].endswith(".service"):
                return CommandResult(0, result.stdout.replace(
                    " --failure-ws ws://127.0.0.1:8642/ws/line-1", ""
                ))
            return result

        result = arm_restart(
            self.cockpit,
            42,
            90,
            "http://127.0.0.1:8642",
            unit="partyline-restart-test",
            run=incomplete_readback,
            inspection=self.inspection,
            generation=lambda _pid: "1234",
        )
        self.assertEqual(result, 1)


class SystemdReadbackTest(unittest.TestCase):
    def test_exec_start_preserves_complete_ordered_argv(self):
        shown = (
            "ExecStart={ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /tmp/restart.py "
            "42 1234 /tmp/server /tmp/log /tmp/cockpit --failure-ws ws://host/ws/line "
            "; ignore_errors=no ; }"
        )
        self.assertEqual(
            parse_systemd_exec_start(shown),
            [
                "/usr/bin/python3", "/tmp/restart.py", "42", "1234", "/tmp/server",
                "/tmp/log", "/tmp/cockpit", "--failure-ws", "ws://host/ws/line",
            ],
        )


class FailedRestartUnitTest(unittest.TestCase):
    def test_a_failed_unit_remains_an_actionable_finding(self):
        import scripts.cockpit as cockpit

        findings = cockpit.failed_restart_units(lambda _args: CommandResult(
            0,
            "partyline-restart-42.service loaded failed failed exact restart\n",
        ))
        self.assertEqual(len(findings), 1)
        self.assertIn("partyline-restart-42.service", findings[0].problem)
        self.assertIn("journalctl", findings[0].fix)

    def test_no_failed_units_is_clean(self):
        import scripts.cockpit as cockpit

        self.assertEqual(
            cockpit.failed_restart_units(lambda _args: CommandResult(0, "")),
            [],
        )


class ArmDispatchTest(unittest.TestCase):
    def test_the_top_level_arm_command_reaches_the_scheduler(self):
        import scripts.cockpit as cockpit

        originals = (
            cockpit.check, cockpit.git, cockpit.check_in_sync,
            cockpit.cockpit_can_boot, cockpit.arm_restart,
        )
        calls = []
        try:
            cockpit.check = lambda **_kwargs: 0
            cockpit.git = lambda *_args, **_kwargs: "same"
            cockpit.check_in_sync = lambda *_args, **_kwargs: []
            cockpit.cockpit_can_boot = lambda *_args, **_kwargs: None
            cockpit.arm_restart = lambda *args, **kwargs: calls.append((args, kwargs)) or 0
            result = cockpit.main([
                "arm",
                "--pid", "42",
                "--delay", "90",
                "--unit", "partyline-restart-test",
                "--cockpit", "/tmp/cockpit",
                "--server-config", "/tmp/cockpit.toml",
            ])
        finally:
            (cockpit.check, cockpit.git, cockpit.check_in_sync,
             cockpit.cockpit_can_boot, cockpit.arm_restart) = originals
        self.assertEqual(result, 0)
        self.assertEqual(calls[0][0][1:3], (42, 90))
        self.assertEqual(calls[0][1]["unit"], "partyline-restart-test")
        self.assertEqual(calls[0][1]["server_config"], Path("/tmp/cockpit.toml"))


class RestartNeededTest(unittest.TestCase):
    """`restart_needed` shells out to git for the diff, so these stub it."""

    def setUp(self):
        import scripts.cockpit as cockpit

        self.cockpit = cockpit
        self.real_git = cockpit.git

    def tearDown(self):
        self.cockpit.git = self.real_git

    def stub_diff(self, paths):
        self.cockpit.git = lambda *args, **kwargs: "\n".join(paths)

    def test_no_movement_needs_no_restart(self):
        self.assertFalse(restart_needed(Path("/tmp"), "abc", "abc"))

    def test_an_adapter_only_change_reloads_instead(self):
        self.stub_diff(["partyline/adapters/bundled/raw/adapter.py"])
        self.assertFalse(restart_needed(Path("/tmp"), "abc", "def"))

    def test_a_server_change_needs_a_restart(self):
        self.stub_diff(["partyline/server.py"])
        self.assertTrue(restart_needed(Path("/tmp"), "abc", "def"))

    def test_a_frontend_change_needs_a_restart(self):
        # The bundle is served by the running process, so a new one needs it.
        self.stub_diff(["partyline/static/assets/index-NEW.js"])
        self.assertTrue(restart_needed(Path("/tmp"), "abc", "def"))

    def test_a_mixed_change_needs_a_restart(self):
        self.stub_diff(["partyline/adapters/loader.py", "partyline/server.py"])
        self.assertTrue(restart_needed(Path("/tmp"), "abc", "def"))


class FindingTest(unittest.TestCase):
    def test_a_finding_always_carries_the_fix_as_well_as_the_problem(self):
        # The point of the preflight is that it tells you what to do, not just
        # that something is wrong.
        finding = Finding("the cockpit is behind", "run deploy")
        self.assertTrue(finding.problem and finding.fix)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def read(self):
        return self.payload


class RestartPlanTest(unittest.TestCase):
    conversations = [
        ConversationResponse(
            id="line-1",
            name="Partyline Refactoring",
            created_at=1,
            topic="",
            archived_at=None,
        ),
        ConversationResponse(
            id="line-2",
            name="Other",
            created_at=2,
            topic="",
            archived_at=None,
        ),
    ]

    def test_line_resolution_prefers_an_exact_id_then_a_unique_name(self):
        self.assertEqual(resolve_line(self.conversations, "line-2").id, "line-2")
        self.assertEqual(resolve_line(self.conversations, "partyline refactoring").id, "line-1")
        with self.assertRaisesRegex(ValueError, "no live line"):
            resolve_line(self.conversations, "missing")

    def test_an_ambiguous_name_requires_the_id(self):
        duplicate = self.conversations + [self.conversations[0].model_copy(update={"id": "line-3"})]

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            resolve_line(duplicate, "Partyline Refactoring")

    def test_plan_posts_the_resolved_line_and_debrief(self):
        requests = []
        responses = [
            FakeResponse([line.model_dump() for line in self.conversations]),
            FakeResponse(
                {
                    "conversation_id": "line-1",
                    "token": "offer-token",
                    "mode": "automatic",
                    "attachments": [{"id": "a1", "name": "sol", "adapter": "codex"}],
                    "debrief": "Continue the restart review.",
                }
            ),
        ]

        def open_url(request):
            requests.append(request)
            return responses.pop(0)

        result = schedule_restart_plan(
            "Partyline Refactoring",
            "Continue the restart review.",
            "http://127.0.0.1:8642",
            open_url,
        )

        self.assertEqual(result.token, "offer-token")
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:8642/api/conversations")
        self.assertEqual(requests[1].full_url, "http://127.0.0.1:8642/api/restart-plan")
        self.assertEqual(
            json.loads(requests[1].data),
            {
                "conversation_id": "line-1",
                "debrief": "Continue the restart review.",
                "mode": "automatic",
            },
        )

    def test_manual_mode_posts_a_human_offer_plan(self):
        requests = []
        responses = [
            FakeResponse([line.model_dump() for line in self.conversations]),
            FakeResponse(
                {
                    "conversation_id": "line-1",
                    "token": "offer-token",
                    "mode": "offer",
                    "attachments": [{"id": "a1", "name": "sol", "adapter": "codex"}],
                    "debrief": "Inspect before continuing.",
                }
            ),
        ]

        def open_url(request):
            requests.append(request)
            return responses.pop(0)

        schedule_restart_plan(
            "line-1",
            "Inspect before continuing.",
            "http://127.0.0.1:8642",
            open_url,
            mode="offer",
        )

        self.assertEqual(
            json.loads(requests[1].data),
            {
                "conversation_id": "line-1",
                "debrief": "Inspect before continuing.",
                "mode": "offer",
            },
        )


if __name__ == "__main__":
    unittest.main()
