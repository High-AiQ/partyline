import asyncio
import os
import stat
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

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
        # The start probe connects and sends nothing.
        self.assertEqual([seen for seen in self.seen if seen], [b"GET /_ping"])

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

    async def test_without_a_docker_grant_the_argv_has_no_docker_ops(self):
        argv = fence._bwrap_argv({"cwd": self.tmp.name}, ["cli"])
        self.assertNotIn("--tmpfs", argv)
        self.assertFalse(os.path.exists(docker_relay.RELAY_ROOT))

    async def test_another_line_is_hidden_from_the_relay_and_only_the_granted_one_binds_it(self):
        own = docker_relay.relay_dir("line")
        socket_path = docker_relay.start("line")  # line A holds the grant
        other = fence._bwrap_argv({"cwd": self.tmp.name, "docker_relays_exist": True}, ["cli"])
        self.assertEqual(other[other.index("--tmpfs") + 1], docker_relay.RELAY_ROOT)
        self.assertNotIn(own, other)
        granted = fence._bwrap_argv({"cwd": self.tmp.name, "docker_relays_exist": True,
                                     "docker_socket": socket_path}, ["cli"])
        bind = [i for i, a in enumerate(granted) if a == "--bind" and granted[i + 1] == own]
        self.assertEqual(len(bind), 1)
        self.assertGreater(bind[0], granted.index("--tmpfs"))
        self.assertEqual(granted[bind[0] + 2], own)

    async def test_a_line_that_starts_before_any_relay_exists_is_still_hidden(self):
        # The trigger is a grant row; the root is created for the argv.
        argv = fence._bwrap_argv({"cwd": self.tmp.name, "docker_relays_exist": True}, ["cli"])
        self.assertIn("--tmpfs", argv)
        self.assertTrue(os.path.isdir(docker_relay.RELAY_ROOT))

    async def test_a_missing_relay_directory_is_skipped_not_fatal(self):
        missing = docker_relay.relay_socket("gone")
        with self.assertLogs("partyline.fence", "WARNING"):
            argv = fence._bwrap_argv({"cwd": self.tmp.name, "docker_relays_exist": True,
                                      "docker_socket": missing}, ["cli"])
        self.assertNotIn(os.path.dirname(missing), argv)
        self.assertIn("--tmpfs", argv)

    async def test_grant_rows_decide_whether_relays_exist(self):
        from partyline.db import Db
        from partyline.write_set_routes import add_write_grant, load_write_grants
        db = Db(os.path.join(self.tmp.name, "t.db"))
        self.addCleanup(db.close)
        db.create_conversation("a", "A")
        db.create_conversation("b", "B")
        att = {"conv_id": "b"}
        load_write_grants(db, att)
        self.assertFalse(att["docker_relays_exist"])
        add_write_grant(db, "a", "/var/run/docker.sock", "person")
        att = {"conv_id": "b"}
        load_write_grants(db, att)
        self.assertTrue(att["docker_relays_exist"])
        self.assertNotIn("docker_socket", att)  # B holds no grant: no relay of its own
        db._exec("UPDATE conversations SET archived_at=1 WHERE id='a'")
        self.assertFalse(docker_relay.any_grant(db))

    async def test_an_unreachable_host_socket_answers_502_with_the_reason_and_a_notice(self):
        await self._close_daemon()
        # Closing the daemon removed its socket: connect fails with ENOENT.
        path = docker_relay.start("line")
        reader, writer = await asyncio.open_unix_connection(path)
        writer.write(b"GET /_ping HTTP/1.1\r\n\r\n")
        reply = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        self.assertTrue(reply.startswith(b"HTTP/1.1 502 Bad Gateway"))
        self.assertIn(b"Content-Type: text/plain", reply)
        self.assertIn(f"cannot connect to {self.host}".encode(), reply)
        self.assertIn(b"needs the docker group", reply)
        (row,) = await docker_relay.status()
        self.assertIn("cannot connect", row["last_error"])
        self.assertIn("cannot connect", row["probe"])

    async def test_a_failed_probe_at_start_posts_a_notice_on_the_line(self):
        await self._close_daemon()
        with patch("partyline.system_notice.post_system_notice", new_callable=AsyncMock) as post, \
                patch.object(docker_relay, "_runtime", object()):
            docker_relay.start("line")
            for _ in range(100):
                if post.await_count:
                    break
                await asyncio.sleep(0.02)
        post.assert_awaited_once()
        self.assertEqual(post.await_args.args[1], "line")
        self.assertIn("cannot connect to", post.await_args.args[2])

    async def test_a_second_start_reuses_the_one_listener(self):
        path = docker_relay.start("line")
        first, inode = docker_relay._relays["line"], os.stat(path).st_ino
        await asyncio.sleep(0.05)  # the server task has finished creating the server
        self.assertEqual(docker_relay.start("line"), path)
        self.assertIs(docker_relay._relays["line"], first)
        self.assertEqual(os.stat(path).st_ino, inode)
        self.assertEqual(len(docker_relay._relays), 1)

    async def test_a_dead_listener_is_replaced_and_stop_closes_open_connections(self):
        path = docker_relay.start("line")
        reader, writer = await asyncio.open_unix_connection(path)
        for _ in range(100):
            if docker_relay._relays["line"].clients:
                break
            await asyncio.sleep(0.02)
        self.assertEqual((await docker_relay.status())[0]["connections"], 1)
        await asyncio.wait_for(docker_relay.stop("line"), 10)  # must not hang on the client
        self.assertEqual(await asyncio.wait_for(reader.read(), 5), b"")
        writer.close()
        self.assertEqual(docker_relay._relays, {})
