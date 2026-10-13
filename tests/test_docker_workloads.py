import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from urllib.parse import unquote
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from partyline import auth_store, auth_tokens, docker_api, docker_workloads
from partyline.adapters.briefing import child_env
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.docker_workload_routes import register_docker_workload_routes
from partyline.docker_workloads import Inventory, announce_survivors

GB = 1024**3
CAPPED, UNCAPPED, STRAY, GONE, OTHER = ("a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64)


class FakeDaemon:
    """A mocked Docker daemon: containers by id, every call recorded."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.containers = {
            CAPPED: self.make(CAPPED, "voice", "running", "child", 4 * GB),
            UNCAPPED: self.make(UNCAPPED, "comfy", "running", "root", 0),
            STRAY: self.make(STRAY, "shared-stream", "running", None, 0),
            GONE: self.make(GONE, "old", "exited", "child", 0),
            OTHER: self.make(OTHER, "elsewhere", "running", "sibling", 0),
        }

    @staticmethod
    def make(cid, name, state, conv, memory):
        labels = {} if conv is None else {
            "partyline.conversation": conv, "partyline.attachment": "att-" + conv}
        return {"Id": cid, "Names": ["/" + name], "Image": "img", "State": state, "Status": state,
                "Labels": labels, "Name": "/" + name, "Config": {"Labels": labels},
                "HostConfig": {"Memory": memory}}

    async def request(self, method, path, *, timeout=10.0):
        self.calls.append((method, path))
        if path.startswith("/containers/json"):
            wanted = None
            if "filters=" in path:
                wanted = json.loads(unquote(path.split("filters=")[1]))["label"][0].split("=", 1)[1]
            return 200, [c for c in self.containers.values()
                         if (c["State"] == "running" or "all=1" in path)
                         and (wanted is None or c["Labels"].get("partyline.conversation") == wanted)]
        parts = path.split("?")[0].strip("/").split("/")
        container = next((c for c in self.containers.values() if c["Id"].startswith(parts[1])), None)
        if container is None:
            return 404, {"message": "no such container"}
        if method == "POST" and parts[2] == "stop":
            was = container["State"]
            container["State"] = "exited"
            return (204 if was == "running" else 304), None
        if parts[2] == "stats":
            return 200, {"memory_stats": {"usage": 3 * GB, "stats": {"inactive_file": GB}}}
        return 200, container

    def stops(self):
        return [path for method, path in self.calls if method == "POST"]


class WorkloadsBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(f"{self.tmp.name}/p.db")
        self.addCleanup(self.db.close)
        for line in ("root", "child", "sibling"):
            self.db.create_conversation(line, line)
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='child'")
        self.daemon = FakeDaemon()
        self.grant = True
        for patcher in (patch.object(docker_api, "request", self.daemon.request),
                        patch.object(docker_workloads.docker_relay, "any_grant",
                                     lambda db: self.grant)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.notices: list[tuple[str, str]] = []
        docker_workloads._noticed.clear()

        async def notice(runtime, conv_id, body, **kw):
            self.notices.append((conv_id, body))

        patcher = patch.object(docker_workloads, "post_system_notice", notice)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = SimpleNamespace(db=self.db)
        self.inventory = Inventory(lambda: 0.0)


class InventoryTest(WorkloadsBase):
    async def test_containers_are_attributed_by_label_and_strays_are_unattributed(self):
        await self.inventory.sample(self.runtime)
        rows = {r["name"]: r for r in self.inventory.view(self.db, None)["containers"]}
        self.assertEqual((rows["voice"]["line"], rows["voice"]["attribution"]), ("child", "attributed"))
        self.assertEqual(rows["voice"]["attachment_id"], "att-child")
        self.assertEqual((rows["shared-stream"]["line"], rows["shared-stream"]["attribution"]),
                         (None, "unattributed"))
        self.assertIn("old", rows)  # stopped containers still list

    async def test_a_running_container_without_a_ram_cap_is_flagged(self):
        await self.inventory.sample(self.runtime)
        rows = {r["name"]: r for r in self.inventory.view(self.db, None)["containers"]}
        self.assertFalse(rows["voice"]["uncapped"])
        self.assertEqual(rows["voice"]["memory_limit_bytes"], 4 * GB)
        self.assertTrue(rows["comfy"]["uncapped"])
        self.assertTrue(rows["shared-stream"]["uncapped"])
        self.assertFalse(rows["old"]["uncapped"])  # not running: nothing to flag yet
        self.assertEqual(rows["comfy"]["memory_used_bytes"], 2 * GB)  # inactive file cache excluded

    async def test_the_summary_counts_running_uncapped_and_unattributed_apart_from_cli_budgets(self):
        self.assertIsNone(self.inventory.summary())
        await self.inventory.sample(self.runtime)
        summary = self.inventory.summary()
        self.assertEqual((summary["running"], summary["uncapped"], summary["unattributed"]), (4, 3, 1))
        self.assertEqual(summary["memory_used_bytes"], 8 * GB)

    async def test_nothing_is_sampled_without_a_docker_grant(self):
        self.grant = False
        self.assertFalse(await self.inventory.sample(self.runtime))
        self.assertEqual(self.daemon.calls, [])
        self.assertIsNone(self.inventory.summary())
        self.assertFalse(self.inventory.view(self.db, None)["enabled"])

    async def test_sampling_is_slow_unless_forced(self):
        now = [0.0]
        inventory = Inventory(lambda: now[0])
        self.assertTrue(await inventory.sample(self.runtime))
        now[0] = 5.0
        self.assertFalse(await inventory.sample(self.runtime))
        now[0] = 16.0
        self.assertTrue(await inventory.sample(self.runtime))
        self.assertTrue(await inventory.sample(self.runtime, force=True))

    async def test_an_unreachable_daemon_is_reported_not_raised(self):
        async def broken(*args, **kwargs):
            raise OSError("Permission denied")

        with patch.object(docker_api, "request", broken):
            await self.inventory.sample(self.runtime)
        self.assertIn("Permission denied", self.inventory.view(self.db, None)["error"])

    async def test_a_machine_sees_only_its_own_subtree(self):
        await self.inventory.sample(self.runtime)
        names = {r["name"] for r in self.inventory.view(self.db, {"child"})["containers"]}
        self.assertEqual(names, {"voice", "old"})

    def test_processes_with_a_docker_grant_get_the_labels_to_apply(self):
        env = child_env({}, {"id": "att1", "conv_id": "c1", "docker_socket": "/x/docker.sock"})
        self.assertEqual(env["PARTYLINE_DOCKER_LABELS"],
                         "partyline.conversation=c1 partyline.attachment=att1")
        self.assertNotIn("PARTYLINE_DOCKER_LABELS", child_env({}, {"id": "att1", "conv_id": "c1"}))


class SurvivorsTest(WorkloadsBase):
    async def test_a_line_with_no_live_process_is_told_which_containers_still_run(self):
        await announce_survivors(self.runtime, "child")
        (conv, body), = self.notices
        self.assertEqual(conv, "child")
        self.assertIn("voice", body)
        self.assertIn("aaaaaaaaaaaa", body)
        self.assertIn("4.0 GB cap", body)
        self.assertNotIn("comfy", body)  # root's, not this line's
        self.assertNotIn("old", body)  # exited
        self.assertNotIn("@", body)

    async def test_an_uncapped_survivor_says_so(self):
        self.daemon.containers[UNCAPPED]["Labels"] = {"partyline.conversation": "child"}
        await announce_survivors(self.runtime, "child")
        self.assertIn("no RAM cap", self.notices[0][1])

    async def test_a_line_that_still_has_a_live_process_is_not_noticed(self):
        self.db.add_attachment("w", "child", "w", "fake", ["f"], self.tmp.name)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='w'")
        await announce_survivors(self.runtime, "child")
        self.assertEqual(self.notices, [])

    async def test_the_same_survivors_are_not_repeated(self):
        await announce_survivors(self.runtime, "child")
        await announce_survivors(self.runtime, "child")
        self.assertEqual(len(self.notices), 1)

    async def test_without_a_docker_grant_the_daemon_is_not_asked(self):
        self.grant = False
        await announce_survivors(self.runtime, "child")
        self.assertEqual((self.notices, self.daemon.calls), ([], []))

    async def test_nothing_running_posts_nothing_and_a_daemon_failure_is_swallowed(self):
        await announce_survivors(self.runtime, "sibling-none")
        self.assertEqual(self.notices, [])
        with patch.object(docker_api, "request", AsyncMock(side_effect=OSError("down"))):
            await announce_survivors(self.runtime, "root")
        self.assertEqual(self.notices, [])

    async def test_detach_announces_survivors_unless_it_is_part_of_a_resume(self):
        from partyline import line_process_routes
        self.db.add_attachment("w", "child", "w", "fake", ["f"], self.tmp.name)
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='w'")
        runtime = SimpleNamespace(
            db=self.db, live={}, resume_locks={}, memory_usage={"w": 1},
            broadcast=AsyncMock(), broadcast_attachment=AsyncMock())
        await line_process_routes.detach_attachment(runtime, "w", survivors=False)
        self.assertEqual(self.notices, [])
        await line_process_routes.detach_attachment(runtime, "w")
        self.assertEqual(len(self.notices), 1)


class StopTest(WorkloadsBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.person = SimpleNamespace(kind="user", name="greg", conv_id=None)
        self.root = SimpleNamespace(kind="machine", name="captain", conv_id="root")
        self.child = SimpleNamespace(kind="machine", name="worker", conv_id="child")

    async def test_a_person_may_stop_any_container_even_an_unattributed_one(self):
        result = await docker_workloads.stop_owned(self.runtime, self.person, STRAY[:12])
        self.assertTrue(result["ok"])
        self.assertEqual(self.daemon.stops(), [f"/containers/{STRAY}/stop?t=10"])  # the full id

    async def test_a_line_may_stop_its_own_container_and_a_captain_one_under_it(self):
        await docker_workloads.stop_owned(self.runtime, self.child, CAPPED[:12])
        self.daemon.containers[CAPPED]["State"] = "running"
        await docker_workloads.stop_owned(self.runtime, self.root, CAPPED)
        self.assertEqual(len(self.daemon.stops()), 2)
        self.assertIn("stopped, not removed", self.notices[0][1])
        self.assertEqual(self.notices[0][0], "child")

    async def test_ownership_refusals_are_403_and_stop_nothing(self):
        for principal, target in ((self.child, UNCAPPED),   # a parent's container
                                  (self.child, STRAY),      # unlabeled
                                  (self.root, OTHER)):      # a sibling tree's
            with self.assertRaises(docker_workloads.HTTPException) as caught:
                await docker_workloads.stop_owned(self.runtime, principal, target[:12])
            self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(self.daemon.stops(), [])

    async def test_only_an_id_names_a_container(self):
        for ident in ("voice", "voice*", "a", "../json", "z" * 12):
            with self.assertRaises(docker_workloads.HTTPException) as caught:
                await docker_workloads.stop_owned(self.runtime, self.person, ident)
            self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.daemon.calls, [])

    async def test_a_name_that_looks_like_an_id_does_not_match_by_name(self):
        self.daemon.containers[STRAY]["Id"] = "f" * 64
        with self.assertRaises(docker_workloads.HTTPException) as caught:
            await docker_workloads.stop_owned(self.runtime, self.person, "c" * 12)
        self.assertEqual(caught.exception.status_code, 404)

    async def test_an_unknown_id_is_404_and_a_failing_daemon_is_502(self):
        with self.assertRaises(docker_workloads.HTTPException) as caught:
            await docker_workloads.stop_owned(self.runtime, self.person, "9" * 12)
        self.assertEqual(caught.exception.status_code, 404)
        with patch.object(docker_api, "request", AsyncMock(side_effect=OSError("down"))):
            with self.assertRaises(docker_workloads.HTTPException) as caught:
                await docker_workloads.stop_owned(self.runtime, self.person, "a" * 12)
        self.assertEqual(caught.exception.status_code, 502)

    async def test_stopping_never_removes(self):
        await docker_workloads.stop_owned(self.runtime, self.person, GONE)  # already stopped: 304
        self.assertFalse([c for c in self.daemon.calls if c[0] == "DELETE" or "rm" in c[1]])
        self.assertIn(GONE, self.daemon.containers)


class RoutesTest(WorkloadsBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.db.add_attachment("child-w", "child", "worker", "fake", ["f"], self.tmp.name)
        user = auth_store.create_user(
            self.db, "p@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.person = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "child-w")}
        patcher = patch.object(docker_workloads, "inventory", self.inventory)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_docker_workload_routes(app, self.runtime)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    async def test_get_shows_a_person_everything_and_a_worker_only_its_own(self):
        with patch("partyline.docker_workload_routes.inventory", self.inventory):
            everything = (await self.client.get("/api/docker-workloads", headers=self.person)).json()
            own = (await self.client.get("/api/docker-workloads", headers=self.worker)).json()
        self.assertEqual(len(everything["containers"]), 5)
        self.assertEqual({c["name"] for c in own["containers"]}, {"voice", "old"})

    async def test_post_stop_maps_ownership_to_403_and_a_person_succeeds(self):
        with patch("partyline.docker_workload_routes.stop_owned", docker_workloads.stop_owned):
            refused = await self.client.post(f"/api/docker-workloads/{UNCAPPED}/stop", headers=self.worker)
            done = await self.client.post(f"/api/docker-workloads/{UNCAPPED}/stop", headers=self.person)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(done.json()["id"], UNCAPPED)


class DockerApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_it_parses_plain_and_chunked_replies_from_a_unix_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "d.sock")
            replies = [b"HTTP/1.0 200 OK\r\n\r\n[1]",
                       b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                       b"3\r\n[2,\r\n2\r\n3]\r\n0\r\n\r\n",
                       b"HTTP/1.0 204 No Content\r\n\r\n",
                       b"HTTP/1.0 500 x\r\n\r\nnot json", b"garbage"]

            async def serve(reader, writer):
                await reader.readuntil(b"\r\n\r\n")
                writer.write(replies.pop(0))
                await writer.drain()
                writer.close()

            server = await asyncio.start_unix_server(serve, path)
            self.addAsyncCleanup(server.wait_closed)
            self.addCleanup(server.close)
            with patch.object(docker_api, "host_socket", lambda: path):
                self.assertEqual(await docker_api.request("GET", "/x"), (200, [1]))
                self.assertEqual(await docker_api.request("GET", "/x"), (200, [2, 3]))
                self.assertEqual(await docker_api.request("POST", "/x"), (204, None))
                self.assertEqual(await docker_api.request("GET", "/x"), (500, None))
                with self.assertRaises(OSError):
                    await docker_api.request("GET", "/x")


if __name__ == "__main__":
    unittest.main()
