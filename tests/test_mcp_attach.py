"""Per-invocation MCP wiring: private config files and argv merge precedence."""

import builtins
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

from unittest.mock import patch

from partyline import mcp_attach
from partyline.adapters.base import Adapter as BaseAdapter
from partyline.adapters.bundled.claude.adapter import PartylineAdapter as ClaudeAdapter
from partyline.adapters.bundled.codex.adapter import PartylineAdapter as CodexAdapter
from partyline.adapters.bundled.opencode.v2 import PartylineAdapter as OpenCodeAdapter
from partyline.agent_connection import provision_connection, remove_connection
from partyline.mcp_attach import (
    claude_command, codex_overrides, config_path, opencode_config_content, remove_config,
)


class McpConfigFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / "test.db")
        self.att = {"id": "agent-one", "conv_id": "line-one", "name": "lead",
                    "api_token": "private-test-token", "hook_url": "http://0.0.0.0:8643/api/hooks/a"}
        provision_connection(self.db, self.att)
        self.connection = Path(self.db + ".agent-connections/agent-one.json")
        self.config = config_path(self.db, "agent-one")

    def test_private_file_names_the_connection_not_the_token(self):
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.config.parent.stat().st_mode & 0o777, 0o700)
        text = self.config.read_text()
        self.assertNotIn(self.att["api_token"], text)
        entry = json.loads(text)["mcpServers"]["partyline"]
        self.assertEqual(entry["args"], ["-P", "-m", "partyline.mcp"])
        self.assertEqual(entry["command"], sys.executable)
        self.assertEqual(entry["env"]["PARTYLINE_MCP_CONNECTION"], str(self.connection))
        self.assertEqual(self.att["mcp_config"], str(self.config))

    def test_probe_scratch_creates_a_fresh_connection_directory(self):
        from docs.mcp.fixture.probe_common import probe_attachment

        source_dir = Path(self.db + ".agent-connections")
        source_dir.mkdir(mode=0o700, exist_ok=True)
        (source_dir / "probe.json").write_text(json.dumps({
            "token": "probe-token", "attachment_id": "probe",
            "handle": "probe-agent",
        }), encoding="utf-8")
        scratch = Path(self.temp.name) / "fresh-scratch"
        with patch.dict(os.environ, {
            "PARTYLINE_TOKEN": "probe-token",
            "PARTYLINE_DB": self.db,
            "PARTYLINE_PROBE_SCRATCH": str(scratch),
        }, clear=True):
            attachment = probe_attachment()
        generated_dir = scratch / "partyline-mcp-probe.agent-connections"
        self.assertTrue(generated_dir.is_dir())
        self.assertEqual(Path(attachment["mcp_config"]).parent, generated_dir)
        self.assertTrue(Path(attachment["mcp_config"]).is_file())

    def test_generated_helper_loads_service_package_from_any_cwd(self):
        import partyline

        entry = json.loads(self.config.read_text())["mcpServers"]["partyline"]
        env = {**os.environ, **entry["env"]}
        stale = Path(self.temp.name) / "stale-checkout"
        stale_package = stale / "partyline"
        stale_package.mkdir(parents=True)
        (stale_package / "__init__.py").write_text("__version__ = 'stale'\n")
        shadow = Path(self.temp.name) / "shadow-checkout"
        shadow_package = shadow / "partyline"
        (shadow_package / "mcp").mkdir(parents=True)
        (shadow_package / "__init__.py").write_text("__version__ = 'shadow'\n")
        (shadow_package / "mcp" / "__main__.py").write_text(
            "raise SystemExit('shadow package was imported')\n")
        working_dirs = (stale, Path(self.temp.name), shadow)
        for cwd in working_dirs:
            with self.subTest(cwd=cwd):
                result = subprocess.run(
                    [entry["command"], *entry["args"]], cwd=cwd, env=env,
                    input='{"jsonrpc":"2.0","id":1,"method":"initialize",'
                          '"params":{"protocolVersion":"2024-11-05"}}\n',
                    capture_output=True, text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                reply = json.loads(result.stdout.splitlines()[0])
                self.assertEqual(reply["result"]["serverInfo"], {
                    "name": "partyline", "version": partyline.__version__})

    def test_resume_regenerates_and_detach_removes(self):
        self.config.unlink()
        provision_connection(self.db, self.att)  # the resume path provisions again
        self.assertTrue(self.config.exists())
        remove_connection(self.db, "agent-one")
        self.assertFalse(self.config.exists())
        self.assertFalse(self.connection.exists())
        remove_config(self.db, "agent-one")  # idempotent

    def test_invalid_attachment_id_is_refused(self):
        with self.assertRaises(ValueError):
            config_path(self.db, "../escape")


class ClaudeMergeTests(unittest.TestCase):
    def test_no_config_leaves_command_untouched(self):
        cmd = ["claude", "--model", "x"]
        self.assertEqual(claude_command(cmd, {}), cmd)

    def test_adds_config_when_user_has_none(self):
        cmd = claude_command(["claude"], {"mcp_config": "/p/a.mcp.json"})
        self.assertEqual(cmd, ["claude", "--mcp-config", "/p/a.mcp.json"])
        self.assertNotIn("--strict-mcp-config", cmd)

    def test_user_run_keeps_order_and_gains_ours_at_its_end(self):
        cmd = claude_command(
            ["claude", "--mcp-config", "/u/one.json", "/u/two.json", "--model", "x"],
            {"mcp_config": "/p/a.mcp.json"})
        self.assertEqual(cmd, ["claude", "--mcp-config", "/u/one.json", "/u/two.json",
                               "/p/a.mcp.json", "--model", "x"])

    def test_user_strict_flag_survives_and_our_config_still_loads(self):
        cmd = claude_command(["claude", "--strict-mcp-config", "--mcp-config", "/u/one.json"],
                             {"mcp_config": "/p/a.mcp.json"})
        self.assertEqual(cmd, ["claude", "--strict-mcp-config", "--mcp-config",
                               "/u/one.json", "/p/a.mcp.json"])

    def test_equals_form_is_kept_and_ours_is_a_separate_option(self):
        cmd = claude_command(["claude", "--mcp-config=/u/one.json"], {"mcp_config": "/p/a.mcp.json"})
        self.assertEqual(cmd, ["claude", "--mcp-config=/u/one.json", "--mcp-config", "/p/a.mcp.json"])

    def test_already_present_config_is_not_added_twice(self):
        cmd = ["claude", "--mcp-config", "/p/a.mcp.json"]
        self.assertEqual(claude_command(cmd, {"mcp_config": "/p/a.mcp.json"}), cmd)


class CodexMergeTests(unittest.TestCase):
    ATT = {"_agent_connection_file": "/c/agent.json"}

    def test_adds_entry_fields_as_toml_values(self):
        overrides = codex_overrides(["codex"], self.ATT)
        self.assertEqual(overrides[0::2], ["-c", "-c", "-c"])
        entry = mcp_attach.server_for(self.ATT)
        for override in overrides[1::2]:
            parsed = tomllib.loads(override)
            field, value = override.split("=", 1)
            key = field.rsplit(".", 1)[1]
            self.assertEqual(parsed["mcp_servers"]["partyline"][key], entry[key])
            self.assertEqual(tomllib.loads(f"probe = {value}")["probe"], entry[key])

    def test_codex_toml_values_escape_awkward_environment_paths(self):
        att = {"_agent_connection_file": '/c/worker "one"\\agent.json'}
        overrides = codex_overrides(["codex"], att)[1::2]
        env = next(value for value in overrides if value.startswith("mcp_servers.partyline.env="))
        parsed = tomllib.loads("probe = " + env.split("=", 1)[1])["probe"]
        self.assertEqual(parsed, mcp_attach.server_for(att)["env"])

    def test_user_keys_win_and_are_not_overridden(self):
        cmd = ["codex", "-c", 'mcp_servers.partyline.command="/mine"',
               "--config=mcp_servers.partyline.env={}"]
        names = [arg.split("=", 1)[0] for arg in codex_overrides(cmd, self.ATT)[1::2]]
        self.assertEqual(names, ["mcp_servers.partyline.args"])

    def test_user_disabled_or_url_server_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text('[mcp_servers.partyline]\nenabled = false\n')
            self.assertEqual(codex_overrides(["codex"], self.ATT, str(config)), [])
            self.assertEqual(codex_overrides(
                ["codex", "-c", "mcp_servers.partyline.enabled=false"], self.ATT), [])
            config.write_text('[mcp_servers.partyline]\nurl = "https://user.example/mcp"\n')
            self.assertEqual(codex_overrides(["codex"], self.ATT, str(config)), [])
            self.assertEqual(codex_overrides(
                ["codex", "--config=mcp_servers.partyline.url=\"https://user.example/mcp\""],
                self.ATT), [])

    def test_partial_user_config_and_argv_values_keep_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text('[mcp_servers.partyline]\nargs = ["--user-arg"]\n')
            overrides = codex_overrides(
                ["codex", "-c", 'mcp_servers.partyline.command="/user-codex"'],
                self.ATT, str(config))[1::2]
        self.assertEqual(len(overrides), 1)
        parsed = tomllib.loads(overrides[0])
        self.assertEqual(parsed["mcp_servers"]["partyline"]["env"],
                         mcp_attach.server_for(self.ATT)["env"])

    def test_without_connection_file_nothing_is_added(self):
        self.assertEqual(codex_overrides(["codex"], {}), [])


class CodexCommandIsolationMixin:
    def setUp(self):
        from partyline.adapters.bundled.codex import adapter as codex

        self.codex = codex
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_roots = (codex.HOME_ROOT, codex.SHARED_HOME)
        self.addCleanup(self._restore_codex_roots)
        codex.HOME_ROOT = str(Path(self.temp.name) / "homes")
        codex.SHARED_HOME = str(Path(self.temp.name) / "shared")
        shared = Path(codex.SHARED_HOME)
        shared.mkdir()
        for name in codex.SHARED:
            path = shared / name
            if name == "config.toml":
                path.write_text('[ui]\ntheme = "synthetic"\n', encoding="utf-8")
            elif name in {"plugins", "skills"}:
                path.mkdir()
            else:
                path.write_text("synthetic auth fixture\n", encoding="utf-8")

        # All command construction in this class is confined to temporary roots.
        # This assertion makes the real user Codex and Partyline homes an explicit
        # forbidden target for the regression.
        user_codex = Path.home() / ".codex"
        user_partyline = Path.home() / ".partyline"
        self.assertFalse(Path(codex.SHARED_HOME).is_relative_to(user_codex))
        self.assertFalse(Path(codex.HOME_ROOT).is_relative_to(user_partyline))

        def guard(path):
            if not isinstance(path, (str, bytes, os.PathLike)):
                return
            candidate = Path(os.fsdecode(path))
            if any(candidate == root or root in candidate.parents
                   for root in (user_codex, user_partyline)):
                raise AssertionError("Codex command test accessed a real user home")

        def guarded(function):
            def call(path, *args, **kwargs):
                guard(path)
                for value in args:
                    guard(value)
                return function(path, *args, **kwargs)
            return call

        for owner, name in (
            (builtins, "open"), (io, "open"), (os, "open"), (os, "stat"),
            (os, "lstat"), (os, "makedirs"), (os, "symlink"), (os, "unlink"),
            (os, "chmod"), (os, "replace"), (os, "rename"),
            (os.path, "exists"), (os.path, "lexists"), (os.path, "isfile"),
            (os.path, "isdir"), (os.path, "islink"),
        ):
            original = getattr(owner, name)
            patcher = patch.object(owner, name, guarded(original))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _restore_codex_roots(self):
        self.codex.HOME_ROOT, self.codex.SHARED_HOME = self.old_roots


class AdapterCommandTests(CodexCommandIsolationMixin, unittest.TestCase):
    def test_claude_adapter_command_carries_the_config(self):
        adapter = ClaudeAdapter.__new__(ClaudeAdapter)
        adapter.att = {"command": ["claude"], "id": "a1", "name": "c", "conv_name": "l",
                       "cwd": "/w", "conv_id": "c1", "mcp_config": "/p/a1.mcp.json",
                       "adapter_metadata": {"capabilities": {"transcript": True}}}
        adapter.resume = False
        command = adapter.build_command()
        index = command.index("--mcp-config")
        self.assertEqual(command[index + 1], "/p/a1.mcp.json")

    def test_codex_overrides_precede_resume_subcommand(self):
        adapter = CodexAdapter.__new__(CodexAdapter)
        adapter.att = {"command": ["codex"], "id": "a1", "cli_session": "s1",
                       "_agent_connection_file": "/c/agent.json", "auto_compact_tokens": 100}
        adapter.resume = True
        adapter._startup_prompt = ""
        command = adapter.build_command()
        self.assertEqual(command[1], "-c")
        self.assertLess(command.index("mcp_servers.partyline.command=" + json.dumps(sys.executable)),
                        command.index("resume"))
        self.assertEqual(command[command.index("resume") + 1], "s1")


class OpenCodeMergeTests(unittest.TestCase):
    ENTRY = {"command": "/py", "args": ["-P", "-m", "partyline.mcp"],
             "env": {"PARTYLINE_MCP_CONNECTION": "/c.json"}}

    def test_merge_adds_partyline_and_keeps_user_servers(self):
        existing = json.dumps({"model": "glm", "mcp": {"other": {"type": "local", "command": ["x"]}}})
        merged = json.loads(opencode_config_content(existing, self.ENTRY))
        self.assertEqual(merged["model"], "glm")
        self.assertEqual(merged["mcp"]["other"], {"type": "local", "command": ["x"]})
        self.assertEqual(merged["mcp"]["partyline"], {
            "type": "local", "command": ["/py", "-P", "-m", "partyline.mcp"],
            "environment": {"PARTYLINE_MCP_CONNECTION": "/c.json"}})

    def test_partyline_entry_replaces_only_a_stale_partyline_entry(self):
        existing = json.dumps({"mcp": {"partyline": {"type": "local", "command": ["old"]}}})
        merged = json.loads(opencode_config_content(existing, self.ENTRY))
        self.assertEqual(merged["mcp"]["partyline"]["command"],
                         ["/py", "-P", "-m", "partyline.mcp"])

    def test_empty_input_starts_fresh(self):
        merged = json.loads(opencode_config_content("", self.ENTRY))
        self.assertEqual(list(merged), ["mcp"])

    def test_unusable_user_value_is_left_alone(self):
        self.assertIsNone(opencode_config_content("{not json", self.ENTRY))
        self.assertIsNone(opencode_config_content("[1, 2]", self.ENTRY))
        self.assertIsNone(opencode_config_content(json.dumps({"mcp": ["list"]}), self.ENTRY))


class OpenCodeAdapterTests(unittest.TestCase):
    def make_adapter(self, *, resume: bool, provisioned: bool = True):
        adapter = OpenCodeAdapter.__new__(OpenCodeAdapter)
        adapter.att = {"command": ["opencode2"], "id": "a1", "cwd": "/w", "conv_id": "c1",
                       "name": "lead", "conv_name": "line", "cli_session": "s1",
                       "adapter_metadata": {}}
        if provisioned:
            adapter.att["_agent_connection_file"] = "/c/a1.json"
        adapter.resume = resume
        return adapter

    def test_fresh_and_resume_spawn_env_carry_the_server(self):
        for resume in (False, True):
            with self.subTest(resume=resume), patch.dict(os.environ, {}, clear=True):
                env = self.make_adapter(resume=resume).spawn_env()
                content = json.loads(env["OPENCODE_CONFIG_CONTENT"])
                self.assertEqual(content["mcp"]["partyline"]["environment"],
                                 {"PARTYLINE_MCP_CONNECTION": "/c/a1.json",
                                  "PYTHONPATH": str(Path(mcp_attach.__file__).resolve().parents[1])})
                self.assertIn("OPENCODE_DB", env)

    def test_user_inline_config_is_merged_not_replaced(self):
        user = json.dumps({"mcp": {"mine": {"type": "local", "command": ["m"]}}})
        with patch.dict(os.environ, {"OPENCODE_CONFIG_CONTENT": user}, clear=True):
            content = json.loads(self.make_adapter(resume=False).spawn_env()["OPENCODE_CONFIG_CONTENT"])
        self.assertIn("mine", content["mcp"])
        self.assertIn("partyline", content["mcp"])

    def test_unprovisioned_or_unusable_input_adds_nothing(self):
        with patch.dict(os.environ, {}, clear=True):
            adapter = self.make_adapter(resume=False, provisioned=False)
            self.assertNotIn("OPENCODE_CONFIG_CONTENT", adapter.spawn_env())
        with patch.dict(os.environ, {"OPENCODE_CONFIG_CONTENT": "{bad"}, clear=True):
            env = self.make_adapter(resume=False).spawn_env()
        self.assertNotIn("OPENCODE_CONFIG_CONTENT", env)


class UnsupportedAdapterTests(CodexCommandIsolationMixin, unittest.TestCase):
    def test_base_hooks_leave_command_and_env_unchanged(self):
        self.assertEqual(BaseAdapter.mcp_argv(None, ["tool", "--flag"]), ["tool", "--flag"])
        self.assertEqual(BaseAdapter.mcp_env(None), {})

    def test_claude_resume_still_gets_config_and_keeps_resume_flag(self):
        adapter = ClaudeAdapter.__new__(ClaudeAdapter)
        adapter.att = {"command": ["claude"], "id": "a1", "name": "c", "conv_name": "l",
                       "cwd": "/w", "conv_id": "c1", "mcp_config": "/p/a1.mcp.json",
                       "adapter_metadata": {"capabilities": {"transcript": True}}}
        adapter.resume = True
        command = adapter.build_command()
        self.assertIn("--resume", command)
        self.assertEqual(command[command.index("--mcp-config") + 1], "/p/a1.mcp.json")

    def test_codex_fresh_command_puts_overrides_before_user_args(self):
        adapter = CodexAdapter.__new__(CodexAdapter)
        adapter.att = {"command": ["codex", "--model", "m"], "id": "a1",
                       "_agent_connection_file": "/c/agent.json"}
        adapter.resume = False
        command = adapter.build_command()
        self.assertEqual(command[0], "codex")
        self.assertEqual(command[1], "-c")
        self.assertEqual(command[-2:], ["--model", "m"])


if __name__ == "__main__":
    unittest.main()
