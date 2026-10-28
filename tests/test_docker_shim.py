import os
import runpy
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.docker_shim_env import configure

SHIM = Path(__file__).resolve().parents[1] / "partyline/docker_shim/docker"
shim = runpy.run_path(str(SHIM))
rewrite = shim["rewrite"]


class DockerShimTests(unittest.TestCase):
    def test_rewrite(self):
        injected = ["--memory", "123", "--memory-swap", "123"]
        self.assertEqual(rewrite(["--host", "tcp://host", "container", "run", "image", "-m"], "123"),
                         ["--host", "tcp://host", "container", "run", *injected, "image", "-m"])
        for args in (["run", "-m", "1g", "image"], ["create", "--memory=1g", "image"],
                     ["container", "create", "-m1g", "image"], ["compose", "up"], ["ps"]):
            self.assertEqual(rewrite(args, "123"), args)
        self.assertEqual(rewrite(["run", "--env", "-m", "image"], "123"),
                         ["run", *injected, "--env", "-m", "image"])

    def test_configuration(self):
        env = {"PATH": "/bin"}
        with patch.dict(os.environ, {"PARTYLINE_DOCKER_MEMORY_FRACTION": "0.25"}):
            configure(env, "1G")
        self.assertEqual(env["PARTYLINE_DOCKER_MEMORY_BYTES"], str(256 * 1024**2))
        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(SHIM.parent))
        with patch.dict(os.environ, {"PARTYLINE_DOCKER_MEMORY_FRACTION": "bad"}):
            with self.assertRaises(ValueError):
                configure({}, "1G")
        with patch.dict(os.environ, {"PARTYLINE_DOCKER_MEMORY_FRACTION": "0"}):
            with self.assertRaises(ValueError):
                configure({}, "1G")
        with patch.dict(os.environ, {"PARTYLINE_DOCKER_MEMORY_FRACTION": "0.001"}):
            env = {}
            configure(env, "256M")
            self.assertEqual(env["PARTYLINE_DOCKER_MEMORY_BYTES"], str(6 * 1024**2))

    @unittest.skipIf(os.name == "nt", "the executable shim is POSIX-only")
    def test_exec_and_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            real = Path(temp) / "docker"
            real.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            real.chmod(0o755)
            (Path(temp) / "python3").symlink_to(sys.executable)
            path = os.pathsep.join([str(SHIM.parent), str(SHIM.parent), temp])
            env = {"PATH": path, "PARTYLINE_DOCKER_MEMORY_BYTES": "123"}
            done = subprocess.run([str(SHIM), "run", "image"], env=env, text=True, capture_output=True)
            self.assertEqual(done.returncode, 0)
            self.assertEqual(done.stdout.splitlines(),
                             ["run", "--memory", "123", "--memory-swap", "123", "image"])
            self.assertEqual(shim["real_docker"](str(SHIM.parent), str(SHIM)), None)
            real.unlink()
            done = subprocess.run([str(SHIM), "ps"], env=env, text=True, capture_output=True)
            self.assertEqual(done.returncode, 127)
            self.assertIn("real docker executable not found", done.stderr)
            real.write_text("#!/bin/sh\nexit 0\n")
            real.chmod(0o755)
            env.pop("PARTYLINE_DOCKER_MEMORY_BYTES")
            done = subprocess.run([str(SHIM), "ps"], env=env, text=True, capture_output=True)
            self.assertEqual(done.returncode, 1)
            self.assertIn("invalid memory limit", done.stderr)
