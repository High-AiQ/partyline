"""Controls for the exact-generation cockpit restart executable."""

import signal
import tempfile
import unittest
from pathlib import Path

import os

from scripts.restart_server import (
    EXIT_ALREADY_GONE,
    EXIT_BAD_ARGUMENTS,
    EXIT_COMMAND_LINE_UNREADABLE,
    EXIT_COVERAGE_CHANGED,
    EXIT_ENVIRONMENT_UNREADABLE,
    EXIT_REPLACEMENT_UNIMPORTABLE,
    EXIT_WRONG_GENERATION,
    RestartRefused,
    main,
    process_cmdline,
    process_cwd,
    process_environment,
    process_generation,
    run_restart,
    with_server_config,
    wait_for_generation_exit,
)


class GenerationParserTest(unittest.TestCase):
    def test_field_22_is_parsed_without_shell_quoting(self):
        """The negative control for the failed inline ``awk '$22'`` unit."""
        with tempfile.TemporaryDirectory() as directory:
            stat = Path(directory) / "42" / "stat"
            stat.parent.mkdir()
            suffix = ["S", *map(str, range(4, 23))]
            stat.write_text(f"42 (party line worker) {' '.join(suffix)}\n")
            self.assertEqual(process_generation(42, Path(directory)), "22")

    def test_missing_or_malformed_stat_is_not_a_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(process_generation(42, root))
            stat = root / "42" / "stat"
            stat.parent.mkdir()
            stat.write_text("not a proc stat")
            self.assertIsNone(process_generation(42, root))


class EnvironmentParserTest(unittest.TestCase):
    def test_the_old_generations_environ_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            environ = Path(directory) / "42" / "environ"
            environ.parent.mkdir()
            environ.write_bytes(b"PATH=/home/g/.local/bin:/usr/bin\0EMPTY=\0\0junk\0")
            self.assertEqual(
                process_environment(42, Path(directory)),
                {"PATH": "/home/g/.local/bin:/usr/bin", "EMPTY": ""},
            )

    def test_a_missing_or_empty_environ_is_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(process_environment(42, root))
            environ = root / "42" / "environ"
            environ.parent.mkdir()
            environ.write_bytes(b"")
            self.assertIsNone(process_environment(42, root))

    def test_the_old_generations_cmdline_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            cmdline = Path(directory) / "42" / "cmdline"
            cmdline.parent.mkdir()
            cmdline.write_bytes(b"/usr/bin/python3\0/home/g/.venv/bin/partyline\0--port\09000\0")
            self.assertEqual(
                process_cmdline(42, Path(directory)),
                ["/usr/bin/python3", "/home/g/.venv/bin/partyline", "--port", "9000"],
            )

    def test_a_missing_or_empty_cmdline_is_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(process_cmdline(42, root))
            cmdline = root / "42" / "cmdline"
            cmdline.parent.mkdir()
            cmdline.write_bytes(b"")
            self.assertIsNone(process_cmdline(42, root))


class ServerConfigArgumentsTest(unittest.TestCase):
    def test_an_explicit_config_supersedes_preserved_bind_flags(self):
        """The 2026-08-20 loopback trap: pid argv `--host 127.0.0.1` outranks
        any config, so preserving it made a loopback cockpit unmovable — the
        trigger refused its own migration. Explicit config now owns the bind."""
        config = Path("/tmp/cockpit.toml")
        self.assertEqual(
            with_server_config(["--host", "127.0.0.1", "--port", "9000"], config),
            ["--config", str(config)],
        )
        self.assertEqual(
            with_server_config(
                ["--host=127.0.0.1", "--instance-name", "Old", "--flag"], config),
            ["--flag", "--config", str(config)],
        )
        self.assertEqual(
            with_server_config(["--config", "old.toml", "--port", "9000"], config),
            ["--config", str(config)],
        )
        self.assertEqual(
            with_server_config(["--config=old.toml", "--port", "9000"], config),
            [f"--config={config}"],
        )

    def test_ambiguous_or_missing_config_arguments_are_refused(self):
        # ValueError here; run_restart maps it to a RestartRefused with the
        # bad-arguments exit code, which the RestartTest suite pins.
        for arguments in (
            ["--config"],
            ["--config", "--port", "9000"],
            ["--config", "one", "--config=two"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                with_server_config(arguments, Path("replacement.toml"))


class RestartTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.server = self.root / "partyline"
        self.server.write_text("#!/bin/sh\nexit 0\n")
        self.server.chmod(0o755)
        self.log = self.root / "cockpit.log"
        self.signals = []
        self.executions = []

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self, generation, wait=lambda *_: None,
               environment=lambda _pid: {"PATH": "/old/server/path"},
               coverage=None):
        # Coverage is injected in every case: its real implementation reads a
        # database, and a unit test must never reach the developer's own.
        self.coverage_databases = []

        def record(database):
            self.coverage_databases.append(database)
            return coverage(database) if coverage else None

        return run_restart(
            42,
            "1234",
            self.server,
            self.log,
            self.root,
            generation=generation,
            environment=environment,
            command_line=lambda _pid: [str(self.server)],
            signal_process=lambda pid, sig: self.signals.append((pid, sig)),
            wait=wait,
            launch=lambda server, logfile, cwd, env, arguments: self.executions.append(
                (server, logfile, cwd, env, arguments)
            ),
            probe=lambda _cwd, _server: None,
            coverage=record,
        )

    def test_an_unreadable_generation_is_refused_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            self.invoke(lambda _pid: None)
        self.assertEqual(raised.exception.exit_code, EXIT_ALREADY_GONE)
        self.assertEqual(self.signals, [])

    def test_a_different_generation_is_refused_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            self.invoke(lambda _pid: "5678")
        self.assertEqual(raised.exception.exit_code, EXIT_WRONG_GENERATION)
        self.assertEqual(self.signals, [])

    def test_a_matching_generation_is_waited_and_execed(self):
        waited = []
        self.invoke(lambda _pid: "1234", lambda pid, start: waited.append((pid, start)))
        self.assertEqual(self.signals, [(42, signal.SIGTERM)])
        self.assertEqual(waited, [(42, "1234")])
        self.assertEqual(
            self.executions,
            [(self.server, self.log, self.root, {"PATH": "/old/server/path"}, [])],
        )

    def test_the_replacement_inherits_the_old_generations_environment(self):
        """The trigger runs under systemd's stripped PATH; the server must not."""
        self.invoke(lambda _pid: "1234")
        _server, _log, _cwd, env, _arguments = self.executions[0]
        self.assertEqual(env, {"PATH": "/old/server/path"})

    def test_the_replacement_inherits_flags_after_the_console_script(self):
        executions = []
        run_restart(
            42,
            "1234",
            self.server,
            self.log,
            self.root,
            generation=lambda _pid: "1234",
            environment=lambda _pid: {"PATH": "/old/server/path"},
            command_line=lambda _pid: [
                "/usr/bin/python3", str(self.server), "--host", "0.0.0.0", "--port", "9000"
            ],
            signal_process=lambda *_args: None,
            wait=lambda *_args: None,
            launch=lambda *args: executions.append(args),
            probe=lambda _cwd, _server: None,
            coverage=lambda _db: None,
        )
        self.assertEqual(executions[0][-1], ["--host", "0.0.0.0", "--port", "9000"])

    def test_an_outgoing_server_from_another_checkout_is_refused_without_a_source(self):
        """The old console script is the anchor for the preserved flags; a
        replacement in a new checkout has a different path, so the anchor must
        be declared rather than guessed — and the refusal must say so."""
        old_server = self.root / "old-checkout" / "partyline"
        with self.assertRaises(RestartRefused) as raised:
            run_restart(
                42, "1234", self.server, self.log, self.root,
                generation=lambda _pid: "1234",
                environment=lambda _pid: {"PATH": "/old/server/path"},
                command_line=lambda _pid: ["/usr/bin/python3", str(old_server), "--port", "8643"],
                signal_process=lambda *_args: self.signals.append(_args),
                wait=lambda *_args: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: None,
            )
        self.assertEqual(raised.exception.exit_code, EXIT_BAD_ARGUMENTS)
        self.assertIn("--source-server", str(raised.exception))
        self.assertEqual((self.signals, self.executions), ([], []))

    def test_an_explicit_source_server_anchors_the_migration(self):
        old_server = self.root / "old-checkout" / "partyline"
        run_restart(
            42, "1234", self.server, self.log, self.root,
            source_server=old_server,
            generation=lambda _pid: "1234",
            environment=lambda _pid: {"PATH": "/old/server/path"},
            command_line=lambda _pid: [
                "/usr/bin/python3", str(old_server), "--config", "/etc/lan.toml"
            ],
            signal_process=lambda pid, sig: self.signals.append((pid, sig)),
            wait=lambda *_args: None,
            launch=lambda *args: self.executions.append(args),
            probe=lambda _cwd, _server: None,
            coverage=lambda _db: None,
        )
        self.assertEqual(self.signals, [(42, signal.SIGTERM)])
        server, _log, cwd, _env, arguments = self.executions[0]
        # The NEW executable is launched, in the NEW cwd, with the OLD flags.
        self.assertEqual((server, cwd, arguments), (self.server, self.root, ["--config", "/etc/lan.toml"]))

    def test_a_source_server_the_pid_is_not_running_is_refused_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            run_restart(
                42, "1234", self.server, self.log, self.root,
                source_server=self.root / "elsewhere" / "partyline",
                generation=lambda _pid: "1234",
                environment=lambda _pid: {},
                command_line=lambda _pid: [str(self.server)],
                signal_process=lambda *_args: self.signals.append(_args),
                wait=lambda *_args: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: None,
            )
        self.assertEqual(raised.exception.exit_code, EXIT_BAD_ARGUMENTS)
        self.assertEqual(self.signals, [])

    def test_server_config_rewrites_only_argv_and_preserves_environment(self):
        executions = []
        config = self.root / "cockpit.toml"
        config.write_text("[server]\nhost = '0.0.0.0'\nport = 8642\n")
        run_restart(
            42,
            "1234",
            self.server,
            self.log,
            self.root,
            server_config=config,
            generation=lambda _pid: "1234",
            environment=lambda _pid: {"PATH": "/old/server/path", "TOKEN": "kept"},
            command_line=lambda _pid: [
                "/usr/bin/python3", str(self.server), "--config", "old.toml",
                "--host", "0.0.0.0", "--port", "8642",
            ],
            signal_process=lambda *_args: None,
            wait=lambda *_args: None,
            launch=lambda *args: executions.append(args),
            probe=lambda _cwd, _server: None,
            coverage=lambda _db: None,
        )
        self.assertEqual(executions[0][-2], {"PATH": "/old/server/path", "TOKEN": "kept"})
        # The preserved bind flags are gone: the explicit config owns the bind,
        # which is what lets a loopback-bound cockpit migrate at all.
        self.assertEqual(executions[0][-1], ["--config", str(config)])

    def test_a_higher_precedence_bind_override_refuses_before_signalling(self):
        config = self.root / "cockpit.toml"
        config.write_text("[server]\nhost = '0.0.0.0'\nport = 8642\n")
        with self.assertRaisesRegex(RestartRefused, "overrides") as raised:
            run_restart(
                42,
                "1234",
                self.server,
                self.log,
                self.root,
                server_config=config,
                generation=lambda _pid: "1234",
                environment=lambda _pid: {"PARTYLINE_HOST": "127.0.0.1"},
                command_line=lambda _pid: [str(self.server)],
                signal_process=lambda pid, sig: self.signals.append((pid, sig)),
                wait=lambda *_args: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: None,
            )
        self.assertEqual(raised.exception.exit_code, 22)
        self.assertEqual(self.signals, [])

    def test_a_config_removed_after_arming_refuses_before_signalling(self):
        missing = self.root / "removed.toml"
        with self.assertRaisesRegex(RestartRefused, "unusable") as raised:
            run_restart(
                42,
                "1234",
                self.server,
                self.log,
                self.root,
                server_config=missing,
                generation=lambda _pid: "1234",
                environment=lambda _pid: {"PATH": "/old/server/path"},
                command_line=lambda _pid: [str(self.server)],
                signal_process=lambda pid, sig: self.signals.append((pid, sig)),
                wait=lambda *_args: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: None,
            )
        self.assertEqual(raised.exception.exit_code, 22)
        self.assertEqual(self.signals, [])

    def test_an_unreadable_environ_refuses_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            self.invoke(lambda _pid: "1234", environment=lambda _pid: None)
        self.assertEqual(raised.exception.exit_code, EXIT_ENVIRONMENT_UNREADABLE)
        self.assertEqual(self.signals, [])
        self.assertEqual(self.executions, [])

    def test_an_unreadable_cmdline_refuses_before_signalling(self):
        with self.assertRaises(RestartRefused) as raised:
            run_restart(
                42,
                "1234",
                self.server,
                self.log,
                self.root,
                generation=lambda _pid: "1234",
                environment=lambda _pid: {"PATH": "/old/server/path"},
                command_line=lambda _pid: None,
                signal_process=lambda pid, sig: self.signals.append((pid, sig)),
                wait=lambda *_args: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: None,
            )
        self.assertEqual(raised.exception.exit_code, EXIT_COMMAND_LINE_UNREADABLE)
        self.assertEqual(self.signals, [])
        self.assertEqual(self.executions, [])

    def test_an_unimportable_replacement_is_refused_before_signalling(self):
        """The failing control for the v0.32.0 Pillow outage.

        A tree that imports a dep the cockpit venv does not have must not
        SIGTERM the live generation. The control error is the one from
        cockpit.log: ModuleNotFoundError: No module named 'PIL'.
        """
        with self.assertRaises(RestartRefused) as raised:
            run_restart(
                42,
                "1234",
                self.server,
                self.log,
                self.root,
                generation=lambda _pid: "1234",
                environment=lambda _pid: {"PATH": "/old/server/path"},
                command_line=lambda _pid: [str(self.server)],
                signal_process=lambda pid, sig: self.signals.append((pid, sig)),
                wait=lambda *_args: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: "ModuleNotFoundError: No module named 'PIL'",
            )
        self.assertEqual(raised.exception.exit_code, EXIT_REPLACEMENT_UNIMPORTABLE)
        self.assertIn("PIL", str(raised.exception))
        self.assertEqual(self.signals, [])
        self.assertEqual(self.executions, [])

    def test_a_bootable_replacement_is_still_signalled(self):
        run_restart(
            42,
            "1234",
            self.server,
            self.log,
            self.root,
            generation=lambda _pid: "1234",
            environment=lambda _pid: {"PATH": "/old/server/path"},
            command_line=lambda _pid: [str(self.server)],
            signal_process=lambda pid, sig: self.signals.append((pid, sig)),
            wait=lambda *_args: None,
            launch=lambda *args: self.executions.append(args),
            probe=lambda _cwd, _server: None,
            coverage=lambda _db: None,
        )
        self.assertEqual(self.signals, [(42, signal.SIGTERM)])
        self.assertEqual(len(self.executions), 1)


class WaitTest(unittest.TestCase):
    def test_a_reused_pid_counts_as_the_old_generation_exiting(self):
        generations = iter(["1234", "9999"])
        wait_for_generation_exit(
            42,
            "1234",
            generation=lambda _pid: next(generations),
            monotonic=lambda: 0,
            sleep=lambda _seconds: None,
        )

    def test_timeout_is_distinct_and_bounded(self):
        clock = iter([0.0, 0.0, 1.0])
        with self.assertRaises(RestartRefused) as raised:
            wait_for_generation_exit(
                42,
                "1234",
                generation=lambda _pid: "1234",
                monotonic=lambda: next(clock),
                sleep=lambda _seconds: None,
                timeout=0.5,
            )
        self.assertIn("did not exit", str(raised.exception))


class FailureReportingTest(unittest.TestCase):
    def test_a_pre_kill_refusal_is_posted_to_the_planned_line(self):
        import scripts.restart_server as restart

        original_run, original_post = restart.run_restart, restart.post_failure
        reports = []
        try:
            restart.run_restart = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RestartRefused("generation mismatch", EXIT_WRONG_GENERATION)
            )
            restart.post_failure = lambda url, token, message: reports.append(
                (url, token, message))
            result = restart.main([
                "42", "1234", "/bin/true", "/tmp/log", "/tmp",
                "--failure-url", "http://127.0.0.1:8642",
                "--report-token", "plan-cap-1",
            ])
        finally:
            restart.run_restart, restart.post_failure = original_run, original_post
        self.assertEqual(result, EXIT_WRONG_GENERATION)
        self.assertEqual(reports[0][0], "http://127.0.0.1:8642")
        self.assertEqual(reports[0][1], "plan-cap-1")
        self.assertIn("generation mismatch", reports[0][2])
        self.assertIn("remains unclaimed", reports[0][2])

    def test_post_failure_refuses_without_the_report_token(self):
        from scripts.restart_server import post_failure

        with self.assertRaisesRegex(RuntimeError, "report token"):
            post_failure("http://127.0.0.1:8642", "", "boom")

    def test_post_failure_posts_the_plan_capability_over_http(self):
        import io
        import json
        from unittest import mock

        from scripts.restart_server import post_failure

        dialed = {}

        def fake_urlopen(request, timeout=None):
            dialed["url"] = request.full_url
            dialed["body"] = json.loads(request.data)
            return io.BytesIO(b'{"ok": true}')

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            post_failure("http://127.0.0.1:8642/", "plan-cap-1", "boom")
        self.assertEqual(
            dialed["url"], "http://127.0.0.1:8642/api/restart-plan/failure")
        self.assertEqual(
            dialed["body"], {"token": "plan-cap-1", "message": "boom"})


class DelayedTriggerCoverageTest(unittest.TestCase):
    """Arming and signalling are ~90 seconds apart; coverage can change between."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.server = self.root / "partyline"
        self.server.write_text("#!/bin/sh\nexit 0\n")
        self.server.chmod(0o755)
        self.signals = []
        self.executions = []
        self.databases = []

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self, coverage, environment):
        def record(database):
            self.databases.append(database)
            return coverage

        return run_restart(
            42,
            "1234",
            self.server,
            self.root / "cockpit.log",
            self.root,
            generation=lambda _pid: "1234",
            environment=lambda _pid: environment,
            command_line=lambda _pid: [str(self.server)],
            signal_process=lambda pid, sig: self.signals.append((pid, sig)),
            wait=lambda *_: None,
            launch=lambda *args: self.executions.append(args),
            probe=lambda _cwd, _server: None,
            coverage=record,
        )

    def test_a_process_attached_during_the_delay_stops_the_restart(self):
        with self.assertRaises(RestartRefused) as raised:
            self.invoke(
                "1 live process(es) would be stopped without recovery: @late on 'new'",
                {"PARTYLINE_DB": "/tmp/instance.db"},
            )

        self.assertEqual(raised.exception.exit_code, EXIT_COVERAGE_CHANGED)
        self.assertIn("@late", str(raised.exception))
        # The whole point: nothing was signalled, so nothing was orphaned.
        self.assertEqual(self.signals, [])
        self.assertEqual(self.executions, [])

    def test_unchanged_coverage_signals_and_launches_as_before(self):
        self.invoke(None, {"PARTYLINE_DB": "/tmp/instance.db"})

        self.assertEqual(self.signals, [(42, signal.SIGTERM)])
        self.assertEqual(len(self.executions), 1)

    def test_coverage_is_read_from_the_outgoing_servers_own_database(self):
        self.invoke(None, {"PARTYLINE_DB": "/tmp/instance.db"})

        self.assertEqual(self.databases, [Path("/tmp/instance.db")])

    def test_without_a_configured_database_the_outgoing_home_is_used(self):
        # Not the trigger's home: a transient systemd unit does not have the
        # interactive user's, and the default database hangs off it.
        self.invoke(None, {"HOME": "/home/someone"})

        self.assertEqual(self.databases, [Path("/home/someone/.partyline.db")])

    def test_coverage_is_checked_only_after_the_replacement_proves_importable(self):
        # Ordering matters: an unimportable replacement is the older, cheaper
        # refusal and must not be masked by a coverage message.
        with self.assertRaises(RestartRefused) as raised:
            run_restart(
                42, "1234", self.server, self.root / "cockpit.log", self.root,
                generation=lambda _pid: "1234",
                environment=lambda _pid: {"PARTYLINE_DB": "/tmp/instance.db"},
                command_line=lambda _pid: [str(self.server)],
                signal_process=lambda pid, sig: self.signals.append((pid, sig)),
                wait=lambda *_: None,
                launch=lambda *args: self.executions.append(args),
                probe=lambda _cwd, _server: "no module named PIL",
                coverage=lambda _db: "would orphan @late",
            )

        self.assertEqual(raised.exception.exit_code, EXIT_REPLACEMENT_UNIMPORTABLE)
        self.assertEqual(self.signals, [])


class ProcessCwdTest(unittest.TestCase):
    def test_the_working_directory_is_read_from_the_proc_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "42").mkdir()
            (root / "42" / "cwd").symlink_to("/srv/app")
            self.assertEqual(process_cwd(42, root), Path("/srv/app"))

    def test_an_unreadable_working_directory_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(process_cwd(42, Path(directory)))


class DashedOptionValueTest(unittest.TestCase):
    """A plan's report token can begin with `-`; the trigger must still parse it.

    `secrets.token_urlsafe` draws from base64url, which includes `-`, so about
    one token in 64 starts with one. The 0.63.0 cockpit restart fired its timer
    and then refused on bad arguments, before signalling anything, because the
    token had been passed as a separate argument.
    """

    def invoke(self, *token_argv):
        # Our own pid with a generation that cannot match: the run gets past
        # argument parsing and then refuses for a reason that is not parsing,
        # which is exactly the distinction under test.
        return main([
            str(os.getpid()), "not-this-generation",
            "/nonexistent/server", "/tmp/cockpit.log", "/tmp",
            *token_argv,
        ])

    def test_a_separate_dashed_value_is_read_as_an_option(self):
        self.assertEqual(
            self.invoke("--report-token", "-Xy_leading-dash"), EXIT_BAD_ARGUMENTS)

    def test_the_joined_form_carries_the_same_value_through(self):
        self.assertEqual(
            self.invoke("--report-token=-Xy_leading-dash"), EXIT_WRONG_GENERATION)

    def test_an_ordinary_token_parses_either_way(self):
        for argv in (["--report-token", "plain"], ["--report-token=plain"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.invoke(*argv), EXIT_WRONG_GENERATION)


if __name__ == "__main__":
    unittest.main()
