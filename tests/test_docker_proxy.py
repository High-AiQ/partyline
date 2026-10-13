import asyncio
import json
import os
import tempfile
import unittest
from functools import partial
from types import SimpleNamespace
from urllib.parse import quote
from unittest.mock import AsyncMock, patch

from partyline import docker_admission, docker_gpu, docker_lifetime, docker_proxy, docker_relay
from partyline.db import Db
from tests.fake_docker_daemon import FULL, GB, FakeDaemon

LIMITS = {"Memory": 4 * GB, "MemorySwap": 4 * GB, "NanoCpus": 10**9, "PidsLimit": 100}
LABELS = {"partyline.max-seconds": "600"}
GPU = [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}]


class ProxyBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.realpath(os.path.join(self.tmp.name, "work"))
        os.makedirs(self.work)
        self.db = Db(f"{self.tmp.name}/p.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("root", "root")
        self.db.create_conversation("line", "line")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='line'")
        self.db.add_attachment("lead", "line", "lead", "fake", ["f"], self.work)
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='lead'")
        self.runtime = SimpleNamespace(db=self.db)
        self.daemon = FakeDaemon(os.path.join(self.tmp.name, "daemon.sock"))
        await self.daemon.start()
        self.addAsyncCleanup(self.daemon.stop)
        self.reserved, self.budget = 10 * GB, 40 * GB
        self.notices: list[tuple[str, str]] = []
        self.free_mb = 24000

        async def notice(runtime, conv_id, body, **kw):
            self.notices.append((conv_id, body))

        self.probe = AsyncMock(side_effect=lambda: self.free_mb)
        self.gpu = docker_gpu.Gpu()
        for patcher in (
            patch.dict(os.environ, {"DOCKER_HOST": f"unix://{self.daemon.path}"}),
            patch.object(
                docker_admission,
                "snapshot",
                lambda db: {"memory_reserved_bytes": self.reserved, "memory_budget_bytes": self.budget},
            ),
            patch.object(docker_admission, "gpu", self.gpu),
            patch.object(docker_gpu, "probe", self.probe),
            patch.object(docker_gpu, "post_system_notice", notice),
            patch.object(docker_lifetime, "post_system_notice", notice),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.relay_path = os.path.join(self.tmp.name, "relay.sock")
        self.relay = await asyncio.start_unix_server(
            partial(docker_proxy.serve, self.runtime, "line"), self.relay_path
        )
        self.addAsyncCleanup(self._close_relay)

    async def _close_relay(self):
        self.relay.close()
        await self.relay.wait_closed()

    async def raw(self, data: bytes, wait=5) -> bytes:
        reader, writer = await asyncio.open_unix_connection(self.relay_path)
        writer.write(data)
        await writer.drain()
        try:
            return await asyncio.wait_for(reader.read(), wait)
        finally:
            writer.close()

    async def call(self, method, target, body=None, headers=None):
        payload = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        lines = [
            f"{method} {target} HTTP/1.1",
            "Host: docker",
            *(f"{k}: {v}" for k, v in (headers or {}).items()),
        ]
        if body is not None:
            lines += ["Content-Type: application/json", f"Content-Length: {len(payload)}"]
        data = await self.raw(("\r\n".join(lines) + "\r\n\r\n").encode() + payload)
        head, _, rest = data.partition(b"\r\n\r\n")
        status = int(head.split()[1]) if head else None
        try:
            return status, json.loads(rest)
        except ValueError:
            return status, rest

    def create_body(self, **host):
        return {"Image": "img", "Labels": dict(LABELS), "HostConfig": {**LIMITS, **host}}

    def forwarded(self, method, fragment):
        return self.daemon.seen(method, fragment)


class AllowlistTest(ProxyBase):
    async def test_open_calls_pass_through(self):
        for target in ("/_ping", "/v1.43/version", "/info", "/images/json", "/images/library/alpine:3/json"):
            status, _ = await self.call("GET", target)
            self.assertEqual(status, 200, target)
        status, _ = await self.call("POST", "/images/create?fromImage=alpine&tag=3")
        self.assertEqual(status, 200)

    async def test_pull_needs_an_image_and_nothing_else(self):
        for target in (
            "/images/create",
            "/images/create?fromSrc=http://x&fromImage=a",
            "/images/create?fromImage=a&changes=x",
        ):
            self.assertEqual((await self.call("POST", target))[0], 403, target)
        self.assertEqual(self.forwarded("POST", "/images/create"), [])

    async def test_denied_calls_get_a_403_naming_the_rule_and_never_reach_the_daemon(self):
        for method, target in (
            ("POST", f"/containers/{FULL['mine']}/update"),
            ("GET", "/volumes"),
            ("POST", "/networks/create"),
            ("POST", "/build"),
            ("DELETE", "/images/alpine"),
            ("POST", "/containers/prune"),
            ("GET", "/containers/../version"),
            ("GET", "/containers/%6mine/json"),
        ):
            status, body = await self.call(method, target, body={} if method == "POST" else None)
            self.assertEqual(status, 403, target)
            self.assertIn("rule:", body["message"])
        self.assertEqual(self.daemon.requests, [])

    async def test_update_is_refused_outright_even_on_an_owned_container(self):
        status, body = await self.call("POST", "/containers/mine/update", body={"Memory": 0})
        self.assertEqual(status, 403)
        self.assertIn("default-deny", body["message"])
        self.assertEqual(self.forwarded("POST", "update"), [])

    async def test_the_list_shows_only_this_lines_containers(self):
        status, rows = await self.call("GET", "/containers/json?all=1")
        self.assertEqual({r["Name"] for r in rows}, {"/mine", "/unlimited", "/running", "/gpu", "/gpu2"})
        widened = json.dumps({"label": ["partyline.conversation=elsewhere"]})
        _status, rows = await self.call("GET", "/containers/json?filters=" + quote(widened))
        self.assertEqual(rows, [])


class OwnershipTest(ProxyBase):
    async def test_owned_containers_are_resolved_to_the_full_id_before_the_call(self):
        for ref in ("mine", FULL["mine"][:12], FULL["mine"]):
            status, _ = await self.call("POST", f"/v1.43/containers/{ref}/stop?t=3")
            self.assertEqual(status, 204, ref)
        sent = [r[1] for r in self.forwarded("POST", "/stop")]
        self.assertEqual(sent, [f"/v1.43/containers/{FULL['mine']}/stop?t=3"] * 3)

    async def test_another_lines_container_is_refused_by_name_short_id_and_full_id(self):
        for ref in ("other", FULL["other"][:12], FULL["other"]):
            for method, op in (
                ("POST", "kill"),
                ("POST", "stop"),
                ("GET", "json"),
                ("GET", "logs"),
                ("POST", "exec"),
                ("POST", "attach"),
            ):
                status, body = await self.call(
                    method, f"/containers/{ref}/{op}", body={} if op == "exec" else None
                )
                self.assertEqual(status, 403, (ref, op))
                self.assertIn("ownership", body["message"])
            self.assertEqual((await self.call("DELETE", f"/containers/{ref}"))[0], 403)
        self.assertEqual([r for r in self.daemon.requests if r[0] != "GET"], [])

    async def test_an_unknown_container_is_404_like_docker(self):
        status, body = await self.call("GET", "/containers/nothing/json")
        self.assertEqual(status, 404)
        self.assertIn("No such container", body["message"])

    async def test_owned_operations_are_forwarded(self):
        for method, op in (
            ("GET", "json"),
            ("GET", "logs"),
            ("GET", "stats"),
            ("GET", "top"),
            ("POST", "wait"),
            ("POST", "kill"),
            ("POST", "stop"),
        ):
            self.assertIn((await self.call(method, f"/containers/running/{op}"))[0], (200, 204), op)
        status, _ = await self.call("DELETE", "/containers/running?force=1")
        self.assertEqual(status, 204)
        self.assertEqual(len(self.forwarded("DELETE", FULL["running"])), 1)

    async def test_exec_belongs_to_the_container_it_runs_in(self):
        status, _ = await self.call("POST", "/containers/mine/exec", body={"Cmd": ["ls"]})
        self.assertEqual(status, 201)
        status, body = await self.call(
            "POST", "/containers/mine/exec", body={"Cmd": ["sh"], "Privileged": True}
        )
        self.assertEqual((status, "privileged" in body["message"]), (403, True))
        self.assertEqual(
            (await self.call("POST", "/exec/" + "a" * 12 + "/start", body={"Detach": True}))[0], 200
        )
        status, body = await self.call("POST", "/exec/" + "b" * 12 + "/start", body={"Detach": True})
        self.assertEqual(status, 403)
        self.assertEqual((await self.call("POST", "/exec/" + "d" * 12 + "/start", body={}))[0], 404)
        self.assertEqual((await self.call("GET", "/exec/" + "b" * 12 + "/json"))[0], 403)

    async def test_attach_becomes_a_raw_pump_only_for_an_owned_container(self):
        reader, writer = await asyncio.open_unix_connection(self.relay_path)
        writer.write(
            b"POST /containers/mine/attach?stream=1 HTTP/1.1\r\nHost: d\r\nConnection: Upgrade\r\n"
            b"Upgrade: tcp\r\n\r\nearly"
        )
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        self.assertIn(b"101", head)
        self.assertEqual(
            await asyncio.wait_for(reader.readexactly(5), 5), b"EARLY"
        )  # pipelined bytes ride along
        writer.write(b"hello")
        self.assertEqual(await asyncio.wait_for(reader.readexactly(5), 5), b"HELLO")
        writer.close()
        denied = await self.raw(
            b"POST /containers/other/attach HTTP/1.1\r\nHost: d\r\nConnection: Upgrade\r\n"
            b"Upgrade: tcp\r\n\r\n"
        )
        self.assertIn(b"403", denied.split(b"\r\n")[0])

    async def test_exec_start_upgrades_for_an_owned_exec_only(self):
        reader, writer = await asyncio.open_unix_connection(self.relay_path)
        writer.write(
            b"POST /exec/" + b"a" * 12 + b"/start HTTP/1.1\r\nHost: d\r\nConnection: Upgrade\r\n"
            b"Upgrade: tcp\r\nContent-Length: 2\r\n\r\n{}"
        )
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        self.assertIn(b"101", head)
        writer.close()


class CreateTest(ProxyBase):
    async def test_a_compliant_create_gets_our_labels_whatever_the_client_sent(self):
        body = self.create_body()
        body["Labels"].update(
            {
                "partyline.conversation": "elsewhere",
                "partyline.managed": "0",
                "partyline.attachment": "forged",
                "keep": "me",
            }
        )
        status, reply = await self.call("POST", "/containers/create?name=job", body=body)
        self.assertEqual((status, reply["Id"]), (201, "9" * 64))
        sent = json.loads(self.forwarded("POST", "/containers/create")[0][3])
        self.assertEqual(
            sent["Labels"],
            {
                "partyline.max-seconds": "600",
                "partyline.conversation": "line",
                "partyline.managed": "1",
                "partyline.attachment": "lead",
                "keep": "me",
            },
        )

    async def test_the_clients_own_attachment_label_survives_when_it_is_on_the_line(self):
        body = self.create_body()
        body["Labels"]["partyline.attachment"] = "lead"
        await self.call("POST", "/containers/create", body=body)
        sent = json.loads(self.forwarded("POST", "/containers/create")[0][3])
        self.assertEqual(sent["Labels"]["partyline.attachment"], "lead")

    async def test_a_create_that_declares_only_some_limits_is_refused_with_every_gap_named(self):
        body = {"Image": "img", "HostConfig": {"Memory": 4 * GB}}
        status, reply = await self.call("POST", "/containers/create", body=body)
        self.assertEqual(status, 403)
        for fragment in ("MemorySwap", "CPU limit", "PidsLimit", "partyline.max-seconds", "managed path"):
            self.assertIn(fragment, reply["message"])
        self.assertEqual(self.forwarded("POST", "/containers/create"), [])

    async def test_each_refused_setting_blocks_the_create(self):
        for change in (
            {"Privileged": True},
            {"CapAdd": ["NET_ADMIN"]},
            {"NetworkMode": "host"},
            {"PidMode": "host"},
            {"IpcMode": "host"},
            {"UTSMode": "host"},
            {"Devices": [{"PathOnHost": "/dev/kvm"}]},
            {"Binds": ["/run/docker.sock:/s"]},
            {"Binds": ["/etc:/x"]},
            {"Binds": ["/var/run:/r"]},
            {"VolumesFrom": ["other"]},
        ):
            status, _ = await self.call("POST", "/containers/create", body=self.create_body(**change))
            self.assertEqual(status, 403, change)
        self.assertEqual(self.forwarded("POST", "/containers/create"), [])

    async def test_binds_inside_the_worktree_and_named_volumes_are_fine(self):
        for host in ({"Binds": [f"{self.work}/out:/out"]}, {"Binds": ["cache:/cache"]}):
            self.assertEqual(
                (await self.call("POST", "/containers/create", body=self.create_body(**host)))[0], 201
            )

    async def test_an_approved_write_set_path_is_a_valid_bind_source(self):
        shared = os.path.join(self.tmp.name, "shared")
        os.makedirs(shared)
        from partyline.write_set_routes import add_write_grant

        add_write_grant(self.db, "line", os.path.realpath(shared), "greg")
        body = self.create_body(Binds=[f"{shared}:/s"])
        self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 201)

    async def test_create_admission_counts_cli_reservations_and_running_managed_caps(self):
        self.reserved, self.budget = 20 * GB, 30 * GB  # 8 GB already used by /running
        status, reply = await self.call("POST", "/containers/create", body=self.create_body())
        self.assertEqual(status, 409)
        for fragment in ("20.0 GB", "16.0 GB", "4.0 GB", "30.0 GB"):  # 16: running, other, gpu2
            self.assertIn(fragment, reply["message"])
        self.budget = 40 * GB
        self.assertEqual((await self.call("POST", "/containers/create", body=self.create_body()))[0], 201)

    async def test_bad_json_and_unknown_query_parameters(self):
        self.assertEqual((await self.call("POST", "/containers/create", body=b"{"))[0], 400)
        status, _ = await self.call("POST", "/containers/create?name=a&x=1", body=self.create_body())
        self.assertEqual(status, 403)

    async def test_a_chunked_body_is_decoded_and_judged_like_any_other(self):
        good = json.dumps(self.create_body()).encode()
        bad = json.dumps(
            {"Image": "img", "HostConfig": {"Privileged": True, **LIMITS}, "Labels": LABELS}
        ).encode()
        for payload, expected in ((good, b"201"), (bad, b"403")):
            chunks = (
                b"".join(b"%x\r\n%s\r\n" % (len(part), part) for part in (payload[:20], payload[20:]))
                + b"0\r\n\r\n"
            )
            data = await self.raw(
                b"POST /containers/create HTTP/1.1\r\nHost: d\r\nTransfer-Encoding: chunked\r\n"
                b"Content-Type: application/json\r\n\r\n" + chunks
            )
            self.assertIn(expected, data.split(b"\r\n")[0])
        self.assertEqual(len(self.forwarded("POST", "/containers/create")), 1)
        self.assertEqual(
            json.loads(self.forwarded("POST", "/containers/create")[0][3])["HostConfig"]["Memory"], 4 * GB
        )


class StartTest(ProxyBase):
    async def test_an_existing_unlimited_container_is_refused_with_the_recreate_message(self):
        for op in ("start", "restart"):
            status, body = await self.call("POST", f"/containers/unlimited/{op}")
            self.assertEqual(status, 403)
            self.assertIn("managed path", body["message"])
            self.assertIn("RAM cap", body["message"])
        self.assertEqual(self.forwarded("POST", "/start") + self.forwarded("POST", "/restart"), [])

    async def test_a_container_that_was_not_created_through_the_proxy_is_refused_even_with_limits(self):
        self.daemon.containers["mine"]["Config"]["Labels"].pop("partyline.managed")
        status, body = await self.call("POST", "/containers/mine/start")
        self.assertEqual(status, 403)
        self.assertIn("not created through the managed path", body["message"])

    async def test_a_changed_container_is_rechecked_at_start(self):
        self.daemon.containers["mine"]["HostConfig"]["Privileged"] = True
        self.assertEqual((await self.call("POST", "/containers/mine/start"))[0], 403)
        self.daemon.containers["mine"]["HostConfig"].pop("Privileged")
        self.daemon.containers["mine"]["HostConfig"]["Binds"] = ["/etc:/x"]
        self.assertEqual((await self.call("POST", "/containers/mine/start"))[0], 403)

    async def test_a_compliant_owned_container_starts_by_full_id(self):
        status, _ = await self.call("POST", "/containers/mine/start")
        self.assertEqual(status, 204)
        self.assertEqual(self.forwarded("POST", "/start")[0][1], f"/containers/{FULL['mine']}/start")

    async def test_start_admission_uses_the_budget_and_a_start_takes_no_body(self):
        self.reserved, self.budget = 30 * GB, 40 * GB  # 16 GB of managed caps run; mine needs 4 GB
        status, body = await self.call("POST", "/containers/mine/start")
        self.assertEqual((status, "budget full" in body["message"]), (409, True))
        self.reserved = 10 * GB
        self.assertEqual((await self.call("POST", "/containers/mine/start", body={"Memory": 0}))[0], 403)
        self.assertEqual((await self.call("POST", "/containers/mine/start"))[0], 204)

    async def test_two_concurrent_starts_cannot_spend_the_same_headroom(self):
        self.reserved, self.budget = 10 * GB, 30 * GB  # 16 GB running: exactly one 4 GB container more fits
        self.daemon.containers["unlimited"].update(
            self.daemon.containers["mine"] | {"Id": FULL["unlimited"], "Name": "/unlimited"}
        )
        results = await asyncio.gather(
            self.call("POST", "/containers/mine/start"), self.call("POST", "/containers/unlimited/start")
        )
        self.assertEqual(sorted(status for status, _ in results), [204, 409])


class GpuTest(ProxyBase):
    async def test_a_gpu_container_starts_when_the_slot_is_free_and_vram_fits(self):
        self.daemon.containers["gpu2"]["State"]["Status"] = "exited"
        status, _ = await self.call("POST", "/containers/gpu/start")
        self.assertEqual(status, 204)

    async def test_only_one_heavy_gpu_job_runs_at_a_time(self):
        status, body = await self.call("POST", "/containers/gpu/start")  # gpu2 holds the slot
        self.assertEqual((status, "slot busy" in body["message"]), (409, True))
        self.db.set_setting("docker_gpu_slots", "2")
        self.assertEqual((await self.call("POST", "/containers/gpu/start"))[0], 204)

    async def test_the_slot_frees_when_the_running_container_stops(self):
        await self.call("POST", "/containers/gpu2/stop")
        self.assertEqual((await self.call("POST", "/containers/gpu/start"))[0], 204)

    async def test_declared_vram_must_fit_free_memory(self):
        self.daemon.containers["gpu2"]["State"]["Status"] = "exited"
        self.free_mb = 8000
        status, body = await self.call("POST", "/containers/gpu/start")
        self.assertEqual((status, "8000 MB free" in body["message"]), (409, True))

    async def test_a_failing_health_check_blocks_gpu_starts_and_tells_the_line_and_the_root_once(self):
        self.daemon.containers["gpu2"]["State"]["Status"] = "exited"
        self.probe.side_effect = OSError("nvidia-smi exited 9: NVRM: Xid 79")
        status, body = await self.call("POST", "/containers/gpu/start")
        self.assertEqual((status, "unhealthy" in self.gpu.unhealthy or True), (503, True))
        self.assertIn("health check failed", body["message"])
        self.assertEqual(sorted(conv for conv, _ in self.notices), ["line", "root"])
        status, body = await self.call("POST", "/containers/gpu/start")  # no new probe, no new notice
        self.assertEqual((status, "marked unhealthy" in body["message"]), (503, True))
        self.assertEqual((self.probe.await_count, len(self.notices)), (1, 2))
        self.assertEqual(self.forwarded("POST", "/start"), [])
        self.probe.side_effect = lambda: 24000
        self.gpu.clear()  # only a person's route does this
        self.assertEqual((await self.call("POST", "/containers/gpu/start"))[0], 204)

    async def test_a_cpu_only_start_never_asks_the_gpu(self):
        self.gpu.unhealthy = "broken"
        self.assertEqual((await self.call("POST", "/containers/mine/start"))[0], 204)
        self.probe.assert_not_awaited()


class ConnectionTest(ProxyBase):
    async def test_a_second_request_on_the_same_connection_is_never_forwarded(self):
        data = await self.raw(
            b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\nPOST /containers/other/kill HTTP/1.1\r\nHost: d\r\n\r\n"
        )
        self.assertIn(b"200", data.split(b"\r\n")[0])
        self.assertNotIn(b"HTTP/1.1 403", data)
        self.assertEqual([r[1] for r in self.daemon.requests], ["/_ping"])
        self.assertIn(b"Connection: close", data)

    async def test_malformed_requests_close_the_connection_unanswered_to_the_daemon(self):
        for garbage in (
            b"\x00\x01\x02garbage\r\n\r\n",
            b"GET /_ping HTTP/9.9\r\n\r\n",
            b"GET /_ping HTTP/1.1\r\nHost: d\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n",
            b"POST /containers/create HTTP/1.1\r\nHost: d\r\nContent-Length: 1\r\n"
            b"Content-Length: 2\r\n\r\nxx",
            b"GET /_ping HTTP/1.1\r\n bad header\r\n\r\n",
            b"GET /\xc3\xa9 HTTP/1.1\r\nHost: d\r\n\r\n",
        ):
            self.assertEqual(await self.raw(garbage), b"", garbage)
        self.assertEqual(self.daemon.requests, [])

    async def test_an_oversized_body_is_refused_before_it_is_judged(self):
        big = b"x" * (docker_proxy.MAX_BODY + 10)
        data = await self.raw(
            b"POST /containers/create HTTP/1.1\r\nHost: d\r\nContent-Length: %d\r\n\r\n%s" % (len(big), big)
        )
        self.assertIn(b"413", data.split(b"\r\n")[0])
        self.assertEqual(self.daemon.requests, [])

    async def test_a_dead_daemon_is_a_502_with_the_reason(self):
        await self.daemon.stop()
        self.addCleanup(self.daemon.start)
        os.unlink(self.daemon.path) if os.path.exists(self.daemon.path) else None
        status, body = await self.call("GET", "/_ping")
        self.assertEqual(status, 502)
        self.assertIn("cannot reach Docker", body["message"])

    async def test_an_idle_client_that_closes_is_not_an_error(self):
        reader, writer = await asyncio.open_unix_connection(self.relay_path)
        writer.close()
        await asyncio.sleep(0.05)
        self.assertEqual(self.daemon.requests, [])

    async def test_x_registry_auth_rides_only_on_pulls(self):
        await self.call("POST", "/images/create?fromImage=a", headers={"X-Registry-Auth": "tok"})
        await self.call("GET", "/info", headers={"X-Registry-Auth": "tok"})
        self.assertEqual(self.forwarded("POST", "/images/create")[0][2].get("x-registry-auth"), "tok")
        self.assertNotIn("x-registry-auth", self.forwarded("GET", "/info")[0][2])


class LifetimeTest(ProxyBase):
    def row(self, name, started, max_seconds=60, managed=True, state="running"):
        return {
            "id": FULL[name],
            "name": name,
            "state": state,
            "managed": managed,
            "max_seconds": max_seconds,
            "started_at": started,
            "conversation_id": "line",
        }

    async def test_overdue_managed_containers_are_stopped_not_removed_and_the_line_is_told_once(self):
        now = 1_000_000.0
        rows = [
            self.row("running", now - 120),
            self.row("mine", now - 5),
            self.row("gpu2", now - 999, managed=False),
            self.row("gpu", now - 999, max_seconds=None),
            self.row("unlimited", now - 999, state="exited"),
        ]
        docker_lifetime._told.clear()
        await docker_lifetime.enforce_lifetimes(self.runtime, rows, now)
        await docker_lifetime.enforce_lifetimes(self.runtime, rows, now)
        self.assertEqual(
            [r[1] for r in self.daemon.requests if r[0] == "POST"],
            [f"/containers/{FULL['running']}/stop?t=10"] * 2,
        )
        self.assertEqual(self.forwarded("DELETE", ""), [])
        self.assertEqual(len(self.notices), 1)
        self.assertIn("stopped, not removed", self.notices[0][1])

    async def test_the_inventory_enforces_lifetimes_as_it_samples(self):
        from partyline import docker_api, docker_workloads

        self.daemon.containers["running"]["State"]["StartedAt"] = "2026-10-13T10:00:00Z"
        self.daemon.containers["running"]["Labels"]["partyline.max-seconds"] = "1"
        inventory = docker_workloads.Inventory(lambda: 0.0)
        docker_lifetime._told.clear()
        with patch.object(docker_workloads.docker_relay, "any_grant", lambda db: True):
            await inventory.sample(self.runtime)
        self.assertEqual(len(self.forwarded("POST", f"{FULL['running']}/stop")), 1)
        self.assertTrue(next(c for c in inventory.containers if c["name"] == "running")["managed"])
        self.assertIs(docker_api.request is not None, True)


class ModeTest(ProxyBase):
    async def test_a_docker_grant_is_managed_unless_a_person_chooses_otherwise(self):
        from partyline.write_set_routes import add_write_grant, list_write_grants

        with patch.object(docker_relay, "_runtime", self.runtime):
            self.assertEqual(docker_relay.relay_mode("line"), "managed")  # no grant at all
            add_write_grant(self.db, "line", "/var/run/docker.sock", "greg")
            self.assertEqual(list_write_grants(self.db, "line")[0]["docker_mode"], "managed")
            self.assertEqual(docker_relay.relay_mode("line"), "managed")
            add_write_grant(self.db, "line", "/var/run/docker.sock", "greg", "unrestricted")
            self.assertEqual(docker_relay.relay_mode("line"), "unrestricted")
            add_write_grant(self.db, "line", "/var/run/docker.sock", "greg")  # a re-grant keeps the choice
            self.assertEqual(docker_relay.relay_mode("line"), "unrestricted")
            add_write_grant(self.db, "line", "/var/run/docker.sock", "greg", "managed")
            self.assertEqual(docker_relay.relay_mode("line"), "managed")

    async def test_the_default_relay_is_the_policy_proxy_and_unrestricted_is_raw_forwarding(self):
        os.makedirs(os.path.join(self.tmp.name, "relays"))
        with (
            patch.object(docker_relay, "_runtime", self.runtime),
            patch.object(docker_relay, "RELAY_ROOT", os.path.join(self.tmp.name, "relays")),
        ):
            path = docker_relay.start("line")
            self.addAsyncCleanup(docker_relay.stop, "line")
            await asyncio.sleep(0.05)
            data = await self._via(path, b"POST /containers/mine/update HTTP/1.1\r\nHost: d\r\n\r\n")
            self.assertIn(b"403", data.split(b"\r\n")[0])
            self.assertEqual(self.forwarded("POST", "update"), [])
            with patch.object(docker_relay, "relay_mode", lambda conv: "unrestricted"):
                data = await self._via(path, b"POST /containers/mine/update HTTP/1.1\r\nHost: d\r\n\r\n")
            self.assertIn(b"204", data.split(b"\r\n")[0])  # the fake daemon's answer, untouched
            self.assertEqual(len(self.forwarded("POST", "update")), 1)

    async def _via(self, path, request):
        reader, writer = await asyncio.open_unix_connection(path)
        writer.write(request)
        await writer.drain()
        writer.write_eof()
        try:
            return await asyncio.wait_for(reader.read(), 5)
        finally:
            writer.close()


class GpuProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_probe_reads_free_vram_and_reports_every_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            smi = os.path.join(tmp, "nvidia-smi")

            def script(body):
                with open(smi, "w") as handle:
                    handle.write("#!/bin/sh\n" + body + "\n")
                os.chmod(smi, 0o755)

            with patch.object(docker_gpu, "SMI", smi), patch.object(docker_gpu, "TIMEOUT", 0.3):
                script("echo 11000; echo 24000")
                self.assertEqual(await docker_gpu.probe(), 24000)
                for body, fragment in (
                    ("echo boom >&2; exit 9", "exited 9"),
                    ("echo garbage", "unreadable"),
                    ("sleep 5", "timed out"),
                ):
                    script(body)
                    with self.assertRaises(OSError) as caught:
                        await docker_gpu.probe()
                    self.assertIn(fragment, str(caught.exception))
            with patch.object(docker_gpu, "SMI", "no-such-nvidia-smi"):
                with self.assertRaises(OSError) as caught:
                    await docker_gpu.probe()
                self.assertIn("not installed", str(caught.exception))

    async def test_the_free_vram_reading_is_cached_briefly(self):
        now = [0.0]
        gpu = docker_gpu.Gpu(lambda: now[0])
        with patch.object(docker_gpu, "probe", AsyncMock(return_value=5000)) as probe:
            self.assertEqual(await gpu.free_mb(None, "x"), 5000)
            now[0] = 2.0
            await gpu.free_mb(None, "x")
            now[0] = 6.0
            await gpu.free_mb(None, "x")
        self.assertEqual(probe.await_count, 2)

    def test_the_slot_setting_defaults_to_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Db(f"{tmp}/p.db")
            self.addCleanup(db.close)
            self.assertEqual(docker_gpu.slots(db), 1)
            db.set_setting("docker_gpu_slots", "3")
            self.assertEqual(docker_gpu.slots(db), 3)
            db.set_setting("docker_gpu_slots", "lots")
            self.assertEqual(docker_gpu.slots(db), 1)


if __name__ == "__main__":
    unittest.main()
