import asyncio
import os
import signal
import stat
import tempfile
import unittest
from unittest.mock import patch

from partyline import docker_bridge_client, docker_relay, fence
from partyline.docker_bridge_client import bridge

REAL_OPEN = asyncio.open_unix_connection


class DockerBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.host = os.path.join(self.tmp.name, "host.sock")
        for patcher in (
                patch.object(docker_relay, "RELAY_ROOT", os.path.join(self.tmp.name, "d")),
                patch.object(docker_bridge_client, "BRIDGE_ROOT", os.path.join(self.tmp.name, "b")),
                patch.dict(os.environ, {"DOCKER_HOST": f"unix://{self.host}"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        bridge.proc, bridge.attempts, bridge.last_error, bridge.lock = None, [], None, None
        bridge.stderr.clear()

        async def daemon(reader, writer):
            data = await reader.read()
            writer.write(b"daemon:" + data)
            await writer.drain()
            writer.close()

        self.daemon = await asyncio.start_unix_server(daemon, path=self.host)
        self.addAsyncCleanup(self._close_daemon)
        self.addAsyncCleanup(bridge.terminate)
        self.addAsyncCleanup(docker_relay.stop, "line")

        async def refused_directly(path, *args, **kwargs):
            if path == self.host:  # the server lacks the docker group
                raise PermissionError(13, "Permission denied")
            return await REAL_OPEN(path, *args, **kwargs)

        patcher = patch("partyline.docker_bridge_client.asyncio.open_unix_connection", refused_directly)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _close_daemon(self):
        self.daemon.close()
        await self.daemon.wait_closed()

    def fake_sg(self, body: str):
        path = os.path.join(self.tmp.name, "sg")
        with open(path, "w") as handle:
            handle.write(f"#!/bin/sh\n{body}\n")
        os.chmod(path, 0o755)
        patcher = patch.object(docker_bridge_client, "SG", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def ask(self, text=b"GET /_ping") -> bytes:
        reader, writer = await REAL_OPEN(docker_relay.start("line"))
        writer.write(text)
        writer.write_eof()
        reply = await asyncio.wait_for(reader.read(), 10)
        writer.close()
        return reply

    async def test_a_refused_host_socket_is_reached_through_the_bridge(self):
        self.fake_sg('exec sh -c "$3"')  # stands in for `sg docker -c CMD`
        self.assertEqual(await self.ask(), b"daemon:GET /_ping")
        info = bridge.info()
        self.assertTrue(info["running"])
        self.assertIsInstance(info["pid"], int)
        self.assertEqual(stat.S_IMODE(os.stat(bridge.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(bridge.path)).st_mode), 0o700)
        (row,) = await docker_relay.status()
        self.assertTrue(row["bridge"]["running"])
        self.assertEqual(row["probe"], "ok")

    async def test_a_dead_bridge_is_restarted(self):
        self.fake_sg('exec sh -c "$3"')
        await self.ask()
        first = bridge.proc.pid
        os.killpg(first, signal.SIGKILL)
        await bridge.proc.wait()
        self.assertEqual(await self.ask(b"again"), b"daemon:again")
        self.assertNotEqual(bridge.proc.pid, first)
        self.assertEqual(len(bridge.attempts), 2)

    async def test_three_failed_starts_give_up_with_the_reason(self):
        self.fake_sg('echo "sg: user is not in docker" >&2; exit 1')
        for _ in range(3):
            reply = await self.ask()
            self.assertTrue(reply.startswith(b"HTTP/1.1 502"))
        self.assertEqual(len(bridge.attempts), 3)
        reply = await self.ask()
        self.assertIn(b"gave up after 3 failed starts", reply)
        self.assertIn(b"user is not in docker", reply)
        self.assertEqual(len(bridge.attempts), 3)  # no fourth spawn
        self.assertFalse(bridge.info()["running"])

    async def test_paths_with_spaces_and_quotes_survive_the_sg_command_string(self):
        self.fake_sg('exec sh -c "$3"')
        spaced = os.path.join(self.tmp.name, "it's a dir")
        with patch.object(docker_bridge_client, "BRIDGE_ROOT", spaced):
            self.assertEqual(await self.ask(), b"daemon:GET /_ping")
            self.assertTrue(os.path.exists(os.path.join(spaced, "bridge.sock")))

    async def test_the_fence_hides_the_bridge_whenever_a_docker_grant_exists(self):
        self.fake_sg('exec sh -c "$3"')
        base = {"cwd": self.tmp.name}
        self.assertNotIn("--tmpfs", fence._bwrap_argv(base, ["cli"]))
        argv = fence._bwrap_argv({**base, "docker_relays_exist": True}, ["cli"])
        hidden = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
        self.assertIn(docker_bridge_client.BRIDGE_ROOT, hidden)
        self.assertNotIn(docker_bridge_client.BRIDGE_ROOT,
                         [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"])
        own = fence._bwrap_argv({**base, "docker_relays_exist": True,
                                 "docker_socket": docker_relay.start("line")}, ["cli"])
        self.assertNotIn(docker_bridge_client.BRIDGE_ROOT,
                         [own[i + 1] for i, a in enumerate(own) if a == "--bind"])


class BridgeProcessTest(unittest.IsolatedAsyncioTestCase):
    async def test_serves_privately_and_exits_with_its_owner(self):
        from partyline import docker_bridge

        with tempfile.TemporaryDirectory() as tmp:
            host, path = os.path.join(tmp, "host.sock"), os.path.join(tmp, "b", "bridge.sock")

            async def daemon(reader, writer):
                writer.write(b"hi:" + await reader.read())
                await writer.drain()
                writer.close()

            server = await asyncio.start_unix_server(daemon, path=host)
            alive = [True]
            with patch.object(docker_bridge, "POLL_SECONDS", 0.02), \
                    patch.object(docker_bridge, "owner_alive", lambda *_: alive[0]):
                task = asyncio.get_running_loop().create_task(docker_bridge.serve(host, path))
                for _ in range(100):
                    if os.path.exists(path):
                        break
                    await asyncio.sleep(0.02)
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)
                reader, writer = await REAL_OPEN(path)
                writer.write(b"x")
                writer.write_eof()
                self.assertEqual(await asyncio.wait_for(reader.read(), 5), b"hi:x")
                writer.close()
                alive[0] = False
                await asyncio.wait_for(task, 5)
            self.assertFalse(os.path.exists(path))
            server.close()
            await server.wait_closed()

    def test_owner_liveness_and_usage(self):
        from partyline import docker_bridge

        self.assertTrue(docker_bridge.owner_alive(os.getpid(), os.getppid()))
        self.assertTrue(docker_bridge.owner_alive(None, os.getppid()))
        self.assertFalse(docker_bridge.owner_alive(os.getpid(), os.getppid() + 1))
        with patch("os.kill", side_effect=ProcessLookupError):
            self.assertFalse(docker_bridge.owner_alive(999999, os.getppid()))
        self.assertEqual(docker_bridge.main(["only-one"]), 2)
