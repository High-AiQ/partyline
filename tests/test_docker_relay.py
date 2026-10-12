import asyncio
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from partyline import docker_relay, fence
from partyline.adapters.briefing import child_env


class DockerRelayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.host = os.path.join(self.tmp.name, "host.sock")
        for target, value in (
                (docker_relay, {"RELAY_ROOT": os.path.join(self.tmp.name, "docker")}),):
            patcher = patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"DOCKER_HOST": f"unix://{self.host}"})
        env.start()
        self.addCleanup(env.stop)
        self.seen = []

        async def fake_docker(reader, writer):
            data = await reader.read()  # until the client half-closes
            self.seen.append(data)
            writer.write(b"daemon:" + data)
            await writer.drain()
            writer.close()

        self.daemon = await asyncio.start_unix_server(fake_docker, path=self.host)
        self.addAsyncCleanup(self._close_daemon)
        self.addAsyncCleanup(docker_relay.stop, "line")

    async def _close_daemon(self):
        self.daemon.close()
        await self.daemon.wait_closed()

    async def test_bytes_flow_both_ways_through_a_private_socket(self):
        path = docker_relay.start("line")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(docker_relay.RELAY_ROOT).st_mode), 0o700)
        reader, writer = await asyncio.open_unix_connection(path)
        writer.write(b"GET /_ping")
        writer.write_eof()
        self.assertEqual(await asyncio.wait_for(reader.read(), 5), b"daemon:GET /_ping")
        writer.close()
        self.assertEqual(self.seen, [b"GET /_ping"])

    async def test_stop_removes_the_relay(self):
        path = docker_relay.start("line")
        await docker_relay.stop("line")
        self.assertFalse(os.path.exists(path))
        with self.assertRaises(OSError):
            await asyncio.open_unix_connection(path)

    async def test_env_and_relay_only_for_a_line_with_the_grant(self):
        granted = {"conv_id": "line", "write_grants": [{"path": "/var/run/docker.sock"}]}
        docker_relay.prepare(granted)
        self.assertEqual(granted["docker_socket"], docker_relay.relay_socket("line"))
        self.assertEqual(child_env({}, granted)["DOCKER_HOST"],
                         f"unix://{docker_relay.relay_socket('line')}")
        plain = {"conv_id": "other", "write_grants": [{"path": "/tmp/x"}]}
        docker_relay.prepare(plain)
        self.assertNotIn("docker_socket", plain)
        self.assertNotIn("DOCKER_HOST", child_env({}, plain))
        self.assertFalse(os.path.exists(docker_relay.relay_dir("other")))

    async def test_without_a_relay_the_argv_has_no_docker_ops(self):
        base = {"cwd": self.tmp.name}
        self.assertNotIn("--tmpfs", fence._bwrap_argv(base, ["cli"]))
        self.assertFalse(os.path.exists(docker_relay.RELAY_ROOT))
        os.makedirs(docker_relay.RELAY_ROOT)  # an empty root is still no relay
        self.assertNotIn("--tmpfs", fence._bwrap_argv(base, ["cli"]))

    async def test_fence_hides_every_relay_and_binds_back_only_its_own(self):
        own = docker_relay.relay_dir("line")
        base = {"cwd": self.tmp.name}
        socket_path = docker_relay.start("line")
        plain = fence._bwrap_argv(base, ["cli"])
        hidden = plain.index("--tmpfs")
        self.assertEqual(plain[hidden + 1], docker_relay.RELAY_ROOT)
        self.assertNotIn(own, plain)
        granted = fence._bwrap_argv({**base, "docker_socket": socket_path}, ["cli"])
        bind = [i for i, a in enumerate(granted) if a == "--bind" and granted[i + 1] == own]
        self.assertEqual(len(bind), 1)
        self.assertGreater(bind[0], granted.index("--tmpfs"))
        self.assertEqual(granted[bind[0] + 2], own)

    async def test_a_missing_relay_directory_is_skipped_not_fatal(self):
        docker_relay.start("other")
        missing = docker_relay.relay_socket("gone")
        with self.assertLogs("partyline.fence", "WARNING"):
            argv = fence._bwrap_argv({"cwd": self.tmp.name, "docker_socket": missing}, ["cli"])
        self.assertNotIn(os.path.dirname(missing), argv)
        self.assertIn("--tmpfs", argv)
        await docker_relay.stop("other")
