"""Review regressions for the managed docker proxy: each test replays an exploit against the fake daemon."""

import asyncio
import contextlib
import json
import os
import time
import unittest
from urllib.parse import unquote
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from partyline import docker_admission, docker_gpu, docker_lifetime, docker_plan, docker_proxy, docker_relay
from partyline.docker_policy import RULES
from tests.fake_docker_daemon import FULL, GB, container
from tests.test_docker_proxy import GPU, LABELS, LIMITS, ProxyBase

UPGRADE = b"Connection: Upgrade\r\nUpgrade: tcp\r\n"


class CaseTest(ProxyBase):
    """Docker's decoder is case-insensitive about JSON keys; the proxy must be too."""

    async def create(self, payload):
        return await self.call("POST", "/containers/create", body=payload)

    async def test_lower_case_spellings_of_refused_settings_are_refused(self):
        for spelled in ("privileged", "PRIVILEGED", "Privileged"):
            body = {"image": "img", "labels": LABELS, "hostconfig": {**LIMITS, spelled: True}}
            self.assertEqual((await self.create(body))[0], 403, spelled)
        for host in ({"capadd": ["SYS_ADMIN"]}, {"NETWORKMODE": "host"}, {"binds": ["/etc:/x"]}):
            body = {"Image": "img", "Labels": LABELS, "HostConfig": {**LIMITS, **host}}
            self.assertEqual((await self.create(body))[0], 403, host)
        self.assertEqual(self.forwarded("POST", "/containers/create"), [])

    async def test_two_spellings_of_one_key_are_refused_at_every_level(self):
        for raw in (
            b'{"Image":"i","HostConfig":{"Memory":1},"hostconfig":{"Privileged":true}}',
            b'{"Image":"i","HostConfig":{"Memory":1,"memory":2}}',
            b'{"Image":"i","Labels":{"a":"1","A":"2"},"HostConfig":{"Memory":1}}',
            b'{"Image":"i","Image":"j","HostConfig":{"Memory":1}}',
        ):
            status, reply = await self.create(raw)
            self.assertEqual(status, 400, raw)
            self.assertIn("malformed-body", reply["message"])
        self.assertEqual(self.forwarded("POST", "/containers/create"), [])

    async def test_only_canonical_names_reach_the_daemon(self):
        body = {
            "IMAGE": "img",
            "labels": dict(LABELS),
            "hostCONFIG": {k.lower(): v for k, v in LIMITS.items()},
        }
        self.assertEqual((await self.create(body))[0], 201)
        sent = json.loads(self.forwarded("POST", "/containers/create")[0][3])
        self.assertEqual(set(sent), {"Image", "Labels", "HostConfig"})
        self.assertEqual(set(sent["HostConfig"]), set(LIMITS))
        self.assertEqual(sent["HostConfig"]["Memory"], 4 * GB)

    async def test_unknown_fields_are_refused_not_forwarded(self):
        for body in (
            {**self.create_body(), "Surprise": 1},
            self.create_body(SomethingNew=True),
            self.create_body(Sysctls={"net.ipv4.ip_forward": "1"}),
            self.create_body(SecurityOpt=["apparmor=unconfined"]),
            self.create_body(Cgroup="host"),
            self.create_body(Links=["other:o"]),
            self.create_body(OomKillDisable=True),
            self.create_body(Isolation="hyperv"),
            self.create_body(MaskedPaths=["/x"]),
            self.create_body(DeviceCgroupRules=["a *:* rwm"]),
            self.create_body(CgroupParent="/x"),
            self.create_body(UsernsMode="host"),
        ):
            self.assertEqual((await self.create(body))[0], 403, body)
        self.assertEqual(self.forwarded("POST", "/containers/create"), [])

    async def test_exec_bodies_are_rebuilt_too(self):
        status, _ = await self.call("POST", "/containers/mine/exec", body={"privileged": True, "Cmd": ["id"]})
        self.assertEqual(status, 403)
        status, _ = await self.call(
            "POST", "/containers/mine/exec", body={"cmd": ["id"], "user": "root", "x": 1}
        )
        self.assertEqual(status, 403)
        status, _ = await self.call("POST", "/containers/mine/exec", body={"CMD": ["id"], "tty": True})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(self.forwarded("POST", "/exec")[0][3]), {"Cmd": ["id"], "Tty": True})
        self.assertEqual(
            (await self.call("POST", "/containers/mine/exec", body=b'{"Cmd":1,"cmd":2}'))[0], 400
        )

    async def test_a_body_of_the_wrong_shape_is_a_400(self):
        for payload in (
            b"[]",
            b"null",
            b'"x"',
            b'{"Image":"i","HostConfig":[]}',
            b'{"Image":5,"HostConfig":{}}',
            b'{"Image":"i","HostConfig":{"Memory":1},"Labels":{"a":1}}',
            b"\xff\xfe",
        ):
            self.assertEqual((await self.create(payload))[0], 400, payload)


class UpgradeTest(ProxyBase):
    async def hijack(self, target, body=b""):
        reader, writer = await asyncio.open_unix_connection(self.relay_path)
        writer.write(
            b"POST "
            + target
            + b" HTTP/1.1\r\nHost: d\r\n"
            + UPGRADE
            + b"Content-Length: %d\r\n\r\n" % len(body)
            + body
        )
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        return head, reader, writer

    async def test_a_refused_attach_does_not_leave_a_raw_line_to_the_daemon(self):
        self.daemon.refuse_attach = self.daemon.keepalive = True
        head, reader, writer = await self.hijack(b"/containers/mine/attach")
        self.assertIn(b"500", head.split(b"\r\n")[0])
        rest = await asyncio.wait_for(reader.read(), 5)  # relayed, then the proxy closes the connection
        self.assertIn(b"attach refused", rest)
        with contextlib.suppress(ConnectionError):  # the proxy has already closed: that is the point
            writer.write(b"GET /containers/json HTTP/1.1\r\nHost: d\r\n\r\n")  # a smuggled second request
            await writer.drain()
        await asyncio.sleep(0.2)
        self.assertEqual(self.forwarded("GET", "/containers/json"), [])
        writer.close()

    async def test_a_refused_exec_start_is_not_a_raw_line_either(self):
        self.daemon.refuse_attach = self.daemon.keepalive = True
        head, reader, writer = await self.hijack(b"/exec/" + b"a" * 12 + b"/start", b"{}")
        self.assertIn(b"500", head.split(b"\r\n")[0])
        await asyncio.wait_for(reader.read(), 5)
        writer.write(b"POST /containers/prune HTTP/1.1\r\nHost: d\r\n\r\n")
        await asyncio.sleep(0.2)
        self.assertEqual(self.forwarded("POST", "/containers/prune"), [])
        writer.close()

    async def test_exec_stdin_reaches_the_process_and_output_comes_back(self):
        head, reader, writer = await self.hijack(b"/exec/" + b"a" * 12 + b"/start", b"{}")
        self.assertIn(b"101", head)
        writer.write(b"echo hi\n")
        self.assertEqual(await asyncio.wait_for(reader.readexactly(8), 5), b"ECHO HI\n")
        writer.close()
        self.assertEqual(json.loads(self.forwarded("POST", "/start")[0][3]), {})

    async def test_the_buildkit_session_upgrades_with_h2c_only(self):
        reader, writer = await asyncio.open_unix_connection(self.relay_path)
        writer.write(
            b"POST /session HTTP/1.1\r\nHost: d\r\nConnection: Upgrade\r\nUpgrade: h2c\r\n"
            b"X-Docker-Expose-Session-Uuid: u1\r\nX-Docker-Expose-Session-Grpc-Method: /a\r\n"
            b"X-Docker-Expose-Session-Grpc-Method: /b\r\nX-Evil: 1\r\n\r\n"
        )
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        self.assertIn(b"101", head)
        writer.write(b"frame")
        self.assertEqual(await asyncio.wait_for(reader.readexactly(5), 5), b"FRAME")
        writer.close()
        sent = self.daemon.requests[-1][2]
        self.assertEqual(sent["x-docker-expose-session-uuid"], "u1")
        self.assertNotIn("x-evil", sent)
        status, _ = await self.call("POST", "/session")  # no upgrade asked: not a plain call
        self.assertEqual(status, 403)


class VolumeAndRuntimeTest(ProxyBase):
    async def test_volume_create_is_the_plain_local_driver_only(self):
        self.assertEqual((await self.call("POST", "/volumes/create", body={"Name": "data"}))[0], 201)
        self.assertEqual((await self.call("GET", "/volumes"))[0], 200)
        self.assertEqual((await self.call("GET", "/system/df"))[0], 200)
        for body in (
            {"Name": "x", "Driver": "local", "DriverOpts": {"type": "none", "o": "bind", "device": "/"}},
            {"Name": "x", "driveropts": {"o": "bind"}},
            {"Name": "x", "Driver": "nfs"},
            {"Name": "../x"},
            {"Name": "x", "name": "y"},
        ):
            self.assertIn((await self.call("POST", "/volumes/create", body=body))[0], (400, 403), body)
        self.assertEqual(len(self.forwarded("POST", "/volumes/create")), 1)

    async def test_a_volume_driver_cannot_be_named_on_a_create(self):
        for host in (
            {"VolumeDriver": "evil"},
            {
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": "v",
                        "Target": "/v",
                        "VolumeOptions": {
                            "DriverConfig": {"Name": "local", "Options": {"o": "bind", "device": "/"}}
                        },
                    }
                ]
            },
        ):
            self.assertEqual(
                (await self.call("POST", "/containers/create", body=self.create_body(**host)))[0], 403, host
            )
        ok = {
            "Mounts": [{"Type": "volume", "Source": "v", "Target": "/v", "VolumeOptions": {"NoCopy": True}}]
        }
        self.assertEqual((await self.call("POST", "/containers/create", body=self.create_body(**ok)))[0], 201)

    async def test_gpu_access_only_through_device_requests(self):
        for host in ({"Runtime": "nvidia"}, {"Runtime": "kata"}):
            self.assertEqual(
                (await self.call("POST", "/containers/create", body=self.create_body(**host)))[0], 403
            )
        body = self.create_body()
        body["Env"] = ["NVIDIA_VISIBLE_DEVICES=all"]
        self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 403)
        body["Env"] = ["CUDA_VISIBLE_DEVICES=0"]
        self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 403)
        body["Env"] = ["FOO=1"]
        body["HostConfig"]["Runtime"] = "runc"
        self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 201)
        gpu = self.create_body(DeviceRequests=GPU)
        gpu["Labels"]["partyline.gpu-mem-mb"] = "9000"
        gpu["Env"] = ["NVIDIA_VISIBLE_DEVICES=all"]
        self.assertEqual((await self.call("POST", "/containers/create", body=gpu))[0], 201)

    async def test_a_restart_policy_would_restart_it_behind_admission(self):
        for name in ("always", "unless-stopped", "on-failure"):
            body = self.create_body(RestartPolicy={"Name": name, "MaximumRetryCount": 0})
            self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 403, name)
        for ok in ({"Name": "no"}, {"Name": ""}, {}):
            body = self.create_body(RestartPolicy=ok)
            self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 201, ok)
        self.daemon.containers["mine"]["HostConfig"]["RestartPolicy"] = {"Name": "always"}
        status, reply = await self.call("POST", f"/containers/{FULL['mine']}/start")
        self.assertEqual(status, 403)
        self.assertIn("RestartPolicy", reply["message"])

    async def test_a_started_container_with_a_runtime_or_volume_driver_is_refused(self):
        for key, value in (("Runtime", "nvidia"), ("VolumeDriver", "evil")):
            self.daemon.containers["mine"]["HostConfig"][key] = value
            self.assertEqual((await self.call("POST", f"/containers/{FULL['mine']}/start"))[0], 403, key)
            del self.daemon.containers["mine"]["HostConfig"][key]
        self.assertEqual(self.forwarded("POST", "/start"), [])

    async def test_a_bind_through_a_symlink_is_refused_even_inside_the_worktree(self):
        os.makedirs(os.path.join(self.work, "real"))
        os.symlink(os.path.join(self.work, "real"), os.path.join(self.work, "inner"))
        os.symlink("/etc", os.path.join(self.work, "out"))
        for source in ("inner", "out", "inner/deeper", "real/../out"):
            body = self.create_body(Binds=[f"{self.work}/{source}:/x"])
            self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 403, source)
        self.assertEqual(
            (
                await self.call(
                    "POST", "/containers/create", body=self.create_body(Binds=[f"{self.work}/real:/x"])
                )
            )[0],
            201,
        )
        # the same rule runs again when an existing container is started
        self.daemon.containers["mine"]["HostConfig"]["Binds"] = [f"{self.work}/out:/x"]
        self.assertEqual((await self.call("POST", f"/containers/{FULL['mine']}/start"))[0], 403)

    async def test_max_seconds_is_capped(self):
        body = self.create_body()
        body["Labels"]["partyline.max-seconds"] = str(48 * 3600)
        status, reply = await self.call("POST", "/containers/create", body=body)
        self.assertEqual(status, 403)
        self.assertIn("cap", reply["message"])
        self.db.set_setting("docker_max_seconds_cap", "200000")
        self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 201)


class TreeAndBuildTest(ProxyBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.db.create_conversation("sib", "sib")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='sib'")
        self.daemon.containers["sibling"] = container("sibling", "exited", "sib", 4 * GB)
        self.daemon.containers["sibling"]["Labels"]["partyline.tree"] = "root"

    async def test_any_line_in_the_creators_tree_can_operate_on_a_container(self):
        ref = FULL["sibling"]
        for method, target in (
            ("GET", f"/containers/{ref}/json"),
            ("POST", f"/containers/{ref}/stop"),
            ("GET", f"/containers/{ref}/logs?stdout=1"),
            ("DELETE", f"/containers/{ref}"),
            ("POST", f"/containers/{ref}/start"),
        ):
            self.assertIn((await self.call(method, target))[0], (200, 204), target)
        status, rows = await self.call("GET", "/containers/json?all=1")
        self.assertIn("/sibling", {r["Name"] for r in rows})
        self.assertNotIn("/other", {r["Name"] for r in rows})
        self.assertEqual((await self.call("POST", f"/containers/{FULL['other']}/stop"))[0], 403)

    async def test_created_containers_carry_the_trees_root(self):
        await self.call("POST", "/containers/create", body=self.create_body())
        sent = json.loads(self.forwarded("POST", "/containers/create")[0][3])
        self.assertEqual(
            (sent["Labels"]["partyline.tree"], sent["Labels"]["partyline.conversation"]), ("root", "line")
        )

    async def test_events_are_forced_to_the_tree(self):
        await self.call("GET", "/events?filters=" + json.dumps({"label": ["x=y"]}).replace(" ", ""))
        target = self.forwarded("GET", "/events")[0][1]
        self.assertIn("partyline.tree%3Droot", target)
        self.assertIn("x%3Dy", target)

    async def test_a_build_streams_a_large_body_with_either_framing(self):
        tar = os.urandom(3 << 20)
        head = b"POST /build?t=img%3A1&rm=1 HTTP/1.1\r\nHost: d\r\nContent-Type: application/x-tar\r\n"
        data = await self.raw(head + b"Content-Length: %d\r\n\r\n" % len(tar) + tar, wait=20)
        self.assertIn(b"200", data.split(b"\r\n")[0])
        self.assertEqual(self.forwarded("POST", "/build")[0][3], tar)
        pieces = (
            b"".join(b"%x\r\n%s\r\n" % (len(p), p) for p in (tar[: 1 << 20], tar[1 << 20 :])) + b"0\r\n\r\n"
        )
        data = await self.raw(head + b"Transfer-Encoding: chunked\r\n\r\n" + pieces, wait=20)
        self.assertIn(b"200", data.split(b"\r\n")[0])
        self.assertEqual(self.forwarded("POST", "/build")[1][3], tar)

    async def test_builds_refuse_host_networking_remote_contexts_and_unknown_parameters(self):
        for query in (
            "networkmode=host",
            "networkmode=container:x",
            "remote=http://x/ctx.tar",
            "cgroupparent=/x",
            "extra=1",
        ):
            status, reply = await self.call("POST", "/build?" + query, body=b"")
            self.assertEqual(status, 403, query)
            self.assertIn("refused:", reply["message"])
        self.assertEqual(self.forwarded("POST", "/build"), [])
        self.assertEqual((await self.call("POST", "/build?networkmode=bridge&t=x", body=b""))[0], 200)

    async def test_container_queries_are_allowlisted(self):
        ref = FULL["mine"]
        for target in (
            f"/containers/{ref}/stop?foo=1",
            f"/containers/{ref}/top?ps_args=aux;id",
            f"/containers/{ref}/json?x=1",
        ):
            self.assertEqual((await self.call("POST" if "stop" in target else "GET", target))[0], 403, target)
        self.assertEqual((await self.call("GET", f"/containers/{ref}/top?ps_args=aux"))[0], 200)


class LimitsTest(ProxyBase):
    async def test_too_many_open_connections_on_one_line_are_refused(self):
        with patch.object(docker_proxy, "MAX_CONNECTIONS", 2):
            held = [await asyncio.open_unix_connection(self.relay_path) for _ in range(2)]
            await asyncio.sleep(0.1)
            data = await self.raw(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
            self.assertIn(b"429", data.split(b"\r\n")[0])
            for _reader, writer in held:
                writer.close()
            await asyncio.sleep(0.2)
            self.assertIn(
                b"200", (await self.raw(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")).split(b"\r\n")[0]
            )
        self.assertEqual(docker_proxy._open.get("line", 0), 0)

    async def test_a_slow_request_is_cut_off_by_the_overall_deadline(self):
        with patch.object(docker_proxy, "REQUEST_DEADLINE", 0.3):
            reader, writer = await asyncio.open_unix_connection(self.relay_path)
            with self.assertRaises((BrokenPipeError, ConnectionResetError)):
                for _ in range(40):  # a byte at a time is never idle, but never finishes either
                    writer.write(b"G")
                    await writer.drain()
                    await asyncio.sleep(0.1)
            writer.close()

    async def test_an_unexpected_error_is_a_500_and_the_connection_closes(self):
        with patch.object(docker_proxy, "decide", AsyncMock(side_effect=RuntimeError("boom"))):
            data = await self.raw(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
        self.assertIn(b"500", data.split(b"\r\n")[0])
        self.assertNotIn(b"boom", data)

    async def test_the_admission_lock_is_not_held_while_a_request_is_forwarded(self):
        self.reserved, self.budget = 0, 17 * GB  # 16 GB running: room for exactly one more 1 GB container
        for name in ("mine", "gpu"):
            self.daemon.containers[name]["HostConfig"].update(Memory=GB, MemorySwap=GB)
        gate, entered = asyncio.Event(), asyncio.Event()
        real = docker_proxy.forward

        async def slow(*args):
            entered.set()
            await gate.wait()
            await real(*args)

        with patch.object(docker_proxy, "forward", slow):
            first = asyncio.ensure_future(self.call("POST", f"/containers/{FULL['mine']}/start"))
            await asyncio.wait_for(entered.wait(), 5)
            # in flight: the lock is free, and its slot already counts against the budget
            async with asyncio.timeout(5):
                async with docker_admission.admission_lock():
                    pass
            status, reply = await self.call("POST", f"/containers/{FULL['unlimited']}/start")
            self.assertEqual(status, 403)  # a different refusal, reached without waiting on the first
            self.daemon.containers["unlimited"].update(
                Config={"Labels": {**self.daemon.containers["mine"]["Labels"]}},
                HostConfig=dict(self.daemon.containers["mine"]["HostConfig"]),
            )
            status, reply = await self.call("POST", f"/containers/{FULL['unlimited']}/start")
            self.assertEqual(status, 409)
            self.assertIn("budget", reply["message"])
            gate.set()
            self.assertEqual((await first)[0], 204)
        self.assertEqual(docker_admission._pending, {})

    async def test_changing_a_grants_access_mode_closes_the_lines_open_connections(self):
        from partyline.write_set_routes import add_write_grant

        writer = MagicMock()
        relay = docker_relay.Relay("p", MagicMock(), clients={writer})
        with patch.dict(docker_relay._relays, {"line": relay}):
            add_write_grant(self.db, "line", "/run/docker.sock", "greg")
            writer.close.assert_not_called()
            add_write_grant(self.db, "line", "/run/docker.sock", "greg", "managed")  # unchanged
            writer.close.assert_not_called()
            add_write_grant(self.db, "line", "/run/docker.sock", "greg", "unrestricted")
            writer.close.assert_called_once()


class LifetimeCapTest(ProxyBase):
    async def test_the_cap_applies_and_counts_from_the_last_start(self):
        now = time.time()
        row = {
            "id": FULL["running"],
            "name": "running",
            "state": "running",
            "managed": True,
            "max_seconds": 10**7,
            "started_at": now - 25 * 3600,
            "conversation_id": "line",
        }
        docker_lifetime._told.clear()
        await docker_lifetime.enforce_lifetimes(self.runtime, [row], now)
        self.assertEqual(len(self.forwarded("POST", "/stop")), 1)
        self.assertIn("86400", self.notices[0][1])
        docker_lifetime._told.clear()
        self.daemon.requests.clear()
        await docker_lifetime.enforce_lifetimes(self.runtime, [{**row, "started_at": now - 3600}], now)
        self.assertEqual(self.forwarded("POST", "/stop"), [])  # restarted an hour ago: a fresh lifetime


class EnvironmentTest(ProxyBase):
    async def test_only_the_requests_own_env_is_judged_never_the_images(self):
        # an image that bakes in NVIDIA_VISIBLE_DEVICES: its merged Config.Env shows up on inspect
        self.daemon.containers["mine"]["Config"]["Env"] = ["NVIDIA_VISIBLE_DEVICES=all", "PATH=/bin"]
        self.assertEqual((await self.call("POST", "/containers/create", body=self.create_body()))[0], 201)
        self.assertEqual((await self.call("POST", f"/containers/{FULL['mine']}/start"))[0], 204)

    async def test_a_default_runtime_other_than_runc_refuses_every_non_gpu_create(self):
        self.daemon.info = {"DefaultRuntime": "nvidia"}
        with patch.object(docker_plan, "_runtime_seen", (float("-inf"), "runc")):
            status, reply = await self.call("POST", "/containers/create", body=self.create_body())
            self.assertEqual(status, 403)
            self.assertTrue(reply["message"].startswith("refused: default-runtime: "))
            gpu = self.create_body(DeviceRequests=GPU)
            gpu["Labels"]["partyline.gpu-mem-mb"] = "9000"
            self.assertEqual((await self.call("POST", "/containers/create", body=gpu))[0], 201)
        self.daemon.info = {"DefaultRuntime": "runc"}
        with patch.object(docker_plan, "_runtime_seen", (float("-inf"), "runc")):
            self.assertEqual((await self.call("POST", "/containers/create", body=self.create_body()))[0], 201)


class RuleNamesTest(ProxyBase):
    """Every refusal reads ``refused: <rule>: <detail>``; each stable rule name shows up in a real refusal."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.seen: dict[str, int] = {}

    def note(self, status, reply, expected, want=403):
        self.assertEqual(status, want, (expected, reply))
        message = reply["message"] if isinstance(reply, dict) else reply.decode()
        self.assertTrue(message.startswith(f"refused: {expected}: "), message)
        if isinstance(reply, dict) and "rules" in reply:
            self.assertEqual(reply["rules"][0], expected)
        self.seen[expected] = status

    async def refused(self, rule, method, target, body=None, want=403):
        status, reply = await self.call(method, target, body=body)
        self.note(status, reply, rule, want)

    def create(self, **host):
        return self.create_body(**host)

    async def test_every_rule_name_appears_in_a_refusal_and_in_the_docs(self):
        mine, c = FULL["mine"], "/containers/create"
        await self.refused("endpoint-not-allowed", "POST", "/networks/create", {})
        await self.refused("update-refused", "POST", f"/containers/{mine}/update", {})
        await self.refused("malformed-path", "GET", "/containers/../version")
        await self.refused("query-not-allowed", "POST", f"/containers/{mine}/stop?foo=1")
        await self.refused("malformed-body", "POST", c, b"[]", 400)
        with patch.object(docker_proxy, "MAX_BODY", 50):
            await self.refused("body-too-large", "POST", c, self.create(), 413)
        await self.refused("not-owned", "POST", f"/containers/{FULL['other']}/stop")
        await self.refused("not-managed", "POST", f"/containers/{FULL['unlimited']}/start")
        await self.refused("limits-required", "POST", c, {"Image": "i", "HostConfig": {"Memory": 1}})
        long = self.create()
        long["Labels"]["partyline.max-seconds"] = str(10**7)
        await self.refused("lifetime-cap", "POST", c, long)
        await self.refused("restart-policy", "POST", c, self.create(RestartPolicy={"Name": "always"}))
        await self.refused("privileged", "POST", c, self.create(Privileged=True))
        await self.refused("host-namespace", "POST", c, self.create(PidMode="host"))
        await self.refused("runtime", "POST", c, self.create(Runtime="nvidia"))
        env = self.create()
        env["Env"] = ["NVIDIA_VISIBLE_DEVICES=all"]
        await self.refused("gpu-env", "POST", c, env)
        await self.refused("volume-driver", "POST", "/volumes/create", {"Name": "v", "Driver": "nfs"})
        await self.refused("bind-source", "POST", c, self.create(Binds=["/etc:/x"]))
        await self.refused("forbidden-setting", "POST", c, self.create(CapAdd=["NET_ADMIN"]))
        await self.refused("field-not-allowed", "POST", c, {**self.create(), "Surprise": 1})
        await self.refused("security-opt", "POST", c, self.create(SecurityOpt=["seccomp=unconfined"]))
        await self.refused("device-request", "POST", c, self.create(DeviceRequests=[{"Driver": "x"}]))
        await self.refused("mount-type", "POST", c, self.create(Mounts=[{"Type": "npipe"}]))
        await self.refused("build-network", "POST", "/build?networkmode=host", b"")
        await self.refused("build-remote", "POST", "/build?remote=http://x", b"")
        await self.refused("upgrade-required", "POST", "/session")
        self.daemon.info = {"DefaultRuntime": "nvidia"}
        with patch.object(docker_plan, "_runtime_seen", (float("-inf"), "runc")):
            await self.refused("default-runtime", "POST", c, self.create())
        self.daemon.info = {"DefaultRuntime": "runc"}
        with patch.object(docker_proxy, "MAX_CONNECTIONS", 0):
            data = await self.raw(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
            self.note(
                int(data.split()[1]), json.loads(data.partition(b"\r\n\r\n")[2]), "connection-limit", 429
            )
        await self.refused("network-driver", "POST", c, self.create(NetworkMode="lan"))
        await self.refused("log-driver", "POST", c, self.create(LogConfig={"Type": "syslog"}))
        await self.refused("port-exposure", "POST", c, self.create(PublishAllPorts=True))
        self.reserved, self.budget = 39 * GB, 40 * GB
        await self.refused("budget-exceeded", "POST", f"/containers/{mine}/start", None, 409)
        self.reserved = 10 * GB
        await self.refused("gpu-busy", "POST", f"/containers/{FULL['gpu']}/start", None, 409)
        self.daemon.containers["gpu2"]["State"]["Status"] = "exited"
        self.free_mb = 100
        self.gpu.clear()
        await self.refused("gpu-memory", "POST", f"/containers/{FULL['gpu']}/start", None, 409)
        self.probe.side_effect = OSError("no nvidia-smi")
        self.gpu.clear()
        with patch.object(docker_gpu, "post_system_notice", AsyncMock()):
            await self.refused("gpu-unhealthy", "POST", f"/containers/{FULL['gpu']}/start", None, 409)
        self.assertEqual(set(RULES) - set(self.seen), set(), "rule names with no refusal in this test")
        self.assertEqual(set(self.seen) - set(RULES), set(), "rule names missing from RULES")
        docs = open(os.path.join(os.path.dirname(__file__), "..", "docs", "write-fence.md")).read()
        self.assertEqual([rule for rule in RULES if f"`{rule}`" not in docs], [], "undocumented rules")

    async def test_a_create_with_several_problems_names_them_all_and_leads_with_the_first_rule(self):
        status, reply = await self.call(
            "POST", "/containers/create", body={"Image": "i", "HostConfig": {"Privileged": True}}
        )
        self.assertEqual(status, 403)
        self.assertTrue(reply["message"].startswith("refused: privileged: "))
        self.assertIn("limits-required", reply["rules"])
        self.assertIn("[limits-required]", reply["message"])


class NestedCaseTest(ProxyBase):
    """Docker reads the keys of nested objects in any case too: every level is rebuilt, then checked."""

    async def create(self, **host):
        return await self.call("POST", "/containers/create", body=self.create_body(**host))

    async def test_a_lowercase_mount_source_cannot_dodge_the_bind_check(self):
        for mount in (
            {"Type": "bind", "source": "/", "Target": "/h"},
            {"type": "bind", "SOURCE": "/etc"},
            {"Type": "bind", "Source": "/", "target": "/h"},
        ):
            status, reply = await self.create(Mounts=[mount])
            self.assertEqual((status, reply["rules"][0]), (403, "bind-source"), mount)
        ok = {"type": "bind", "source": f"{self.work}", "target": "/w"}
        self.assertEqual((await self.create(Mounts=[ok]))[0], 201)
        sent = json.loads(self.forwarded("POST", "/containers/create")[0][3])
        self.assertEqual(
            sent["HostConfig"]["Mounts"], [{"Type": "bind", "Source": self.work, "Target": "/w"}]
        )

    async def test_lowercase_volume_options_cannot_dodge_the_driver_check(self):
        opts = {"Type": "volume", "Source": "v", "Target": "/v"}
        for nested in (
            {"volumeoptions": {"driverconfig": {"name": "local", "options": {"o": "bind", "device": "/"}}}},
            {"VolumeOptions": {"DRIVERCONFIG": {"Name": "local", "OPTIONS": {"device": "/"}}}},
            {"VolumeOptions": {"DriverConfig": {"name": "evil"}}},
        ):
            status, reply = await self.create(Mounts=[{**opts, **nested}])
            self.assertEqual((status, reply["rules"][0]), (403, "volume-driver"), nested)

    async def test_a_lowercase_restart_policy_name_is_still_a_restart_policy(self):
        for policy in ({"name": "always"}, {"NAME": "unless-stopped"}, {"Name": "on-failure"}):
            status, reply = await self.create(restartpolicy=policy)
            self.assertEqual((status, reply["rules"][0]), (403, "restart-policy"), policy)

    async def test_lowercase_device_request_keys_are_the_same_keys(self):
        gpu = self.create_body(devicerequests=[{"driver": "nvidia", "count": -1, "capabilities": [["gpu"]]}])
        gpu["Labels"]["partyline.gpu-mem-mb"] = "9000"
        self.assertEqual((await self.call("POST", "/containers/create", body=gpu))[0], 201)
        sent = json.loads(self.forwarded("POST", "/containers/create")[0][3])
        self.assertEqual(sent["HostConfig"]["DeviceRequests"][0]["Driver"], "nvidia")
        status, reply = await self.create(devicerequests=[{"driver": "evil", "capabilities": [["x"]]}])
        self.assertEqual((status, reply["rules"][0]), (403, "device-request"))
        status, reply = await self.create(DeviceRequests=[{"Driver": "nvidia", "Smuggled": 1}])
        self.assertEqual((status, reply["rules"][0]), (403, "field-not-allowed"))

    async def test_nested_unknown_fields_are_refused_at_every_level(self):
        for host in (
            {"Mounts": [{"Type": "volume", "Source": "v", "Target": "/v", "Extra": 1}]},
            {"Mounts": [{"Type": "bind", "Source": self.work, "Target": "/w", "BindOptions": {"X": 1}}]},
            {"LogConfig": {"Type": "json-file", "Extra": 1}},
            {"RestartPolicy": {"Name": "no", "Extra": 1}},
            {"Ulimits": [{"Name": "nofile", "Soft": 1, "Hard": 1, "Extra": 1}]},
            {"PortBindings": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "80", "Extra": 1}]}},
        ):
            status, reply = await self.create(**host)
            self.assertEqual((status, reply["rules"][0]), (403, "field-not-allowed"), host)
        body = self.create_body()
        body["NetworkingConfig"] = {"EndpointsConfig": {"bridge": {"Surprise": 1}}}
        self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 403)
        body["NetworkingConfig"] = {"endpointsconfig": {"host": {}}}
        status, reply = await self.call("POST", "/containers/create", body=body)
        self.assertEqual((status, reply["rules"][0]), (403, "host-namespace"))
        body["NetworkingConfig"] = {"EndpointsConfig": {"bridge": {"aliases": ["x"]}}}
        self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 201)

    async def test_annotations_log_drivers_and_published_ports(self):
        cases = {
            "forbidden-setting": [
                {"Annotations": {"io.kubernetes.cri.sandbox": "x"}},
                {"annotations": {"run.oci.handler": "x"}},
            ],
            "log-driver": [
                {"LogConfig": {"Type": "syslog", "Config": {"syslog-address": "tcp://x:1"}}},
                {"logconfig": {"type": "fluentd"}},
            ],
            "port-exposure": [
                {"PublishAllPorts": True},
                {"PortBindings": {"80/tcp": [{"HostPort": "80"}]}},
                {"PortBindings": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "80"}]}},
                {"portbindings": {"80/tcp": [{"hostip": "", "hostport": "80"}]}},
            ],
        }
        for rule, hosts in cases.items():
            for host in hosts:
                status, reply = await self.create(**host)
                self.assertEqual((status, reply["rules"][0]), (403, rule), host)
        for host in (
            {"LogConfig": {"Type": "local", "Config": {"max-size": "10m"}}},
            {"LogConfig": {}},
            {"PortBindings": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}},
            {"PortBindings": {"80/tcp": [{"HostIp": "::1", "HostPort": "8080"}], "81/tcp": None}},
        ):
            self.assertEqual((await self.create(**host))[0], 201, host)

    async def test_a_started_container_is_held_to_the_same_rules(self):
        self.daemon.containers["mine"]["HostConfig"]["PortBindings"] = {
            "80/tcp": [{"HostIp": "", "HostPort": "80"}]
        }
        status, reply = await self.call("POST", f"/containers/{FULL['mine']}/start")
        self.assertEqual((status, reply["rules"][0]), (403, "port-exposure"))
        self.daemon.containers["mine"]["HostConfig"]["PortBindings"] = {}
        self.daemon.containers["mine"]["HostConfig"]["LogConfig"] = {"Type": "gelf", "Config": {}}
        self.assertEqual(
            (await self.call("POST", f"/containers/{FULL['mine']}/start"))[1]["rules"][0], "log-driver"
        )

    async def test_exec_and_volume_bodies_are_case_proof_too(self):
        status, reply = await self.call(
            "POST", "/containers/mine/exec", body={"Cmd": ["id"], "PRIVILEGED": True}
        )
        self.assertEqual((status, reply["rules"][0]), (403, "privileged"))
        self.assertEqual(
            (await self.call("POST", "/volumes/create", body={"name": "d", "driver": "local"}))[0], 201
        )
        sent = json.loads(self.forwarded("POST", "/volumes/create")[0][3])
        self.assertEqual(sent, {"Name": "d", "Driver": "local"})
        status, reply = await self.call(
            "POST", "/volumes/create", body={"name": "d", "driveropts": {"o": "bind"}}
        )
        self.assertEqual((status, reply["rules"][0]), (403, "volume-driver"))

    async def test_every_key_of_a_full_body_is_case_proof(self):
        """Lowercase and upper-case each struct key in turn: refused, or identical once canonicalised."""
        from partyline.docker_body import canonical_create
        from partyline.docker_schema import CREATE

        sample = {
            "Image": "img",
            "Hostname": "h",
            "Env": ["A=1"],
            "Labels": {"partyline.max-seconds": "60", "partyline.gpu-mem-mb": "1000"},
            "Healthcheck": {"Test": ["CMD", "true"], "Interval": 1, "Retries": 2},
            "NetworkingConfig": {
                "EndpointsConfig": {"bridge": {"IPAMConfig": {"IPv4Address": "10.0.0.2"}, "Aliases": ["a"]}}
            },
            "HostConfig": {
                **LIMITS,
                "Binds": [f"{self.work}:/w"],
                "Runtime": "runc",
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m"}},
                "PortBindings": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "80"}]},
                "DeviceRequests": [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}],
                "Ulimits": [{"Name": "nofile", "Soft": 1, "Hard": 2}],
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": self.work,
                        "Target": "/b",
                        "BindOptions": {"Propagation": "rprivate"},
                    },
                    {
                        "Type": "volume",
                        "Source": "v",
                        "Target": "/v",
                        "VolumeOptions": {"NoCopy": True, "DriverConfig": {"Name": "local"}},
                    },
                    {"Type": "tmpfs", "Target": "/t", "TmpfsOptions": {"SizeBytes": 1}},
                ],
            },
        }
        sockets, roots = {"/run/docker.sock"}, [self.work]
        base, problems = canonical_create(sample, sockets, roots, 86400)
        self.assertEqual(problems, [])
        paths = []

        def walk(value, spec, path):
            if isinstance(spec, tuple):
                for key, item in value.items():
                    walk(item, spec[1], path + [(key, 1)])
            elif isinstance(spec, list):
                for index, item in enumerate(value):
                    walk(item, spec[0], path + [(index, 0)])
            elif isinstance(spec, dict) and isinstance(value, dict):
                for key, item in value.items():
                    paths.append(path + [(key, 0)])
                    walk(item, spec[key], path + [(key, 0)])

        walk(sample, CREATE, [])
        self.assertGreater(len(paths), 40)

        def variant(path, change):
            def rec(value, rest):
                (key, _), tail = rest[0], rest[1:]
                if isinstance(value, list):
                    return [rec(v, tail) if i == key else v for i, v in enumerate(value)]
                renamed = {}
                for name, item in value.items():
                    new = change(name) if name == key and not tail else name
                    renamed[new] = rec(item, tail) if name == key and tail else item
                return renamed

            return rec(sample, path)

        for path in paths:
            for change in (str.lower, str.upper):
                fresh, found = canonical_create(variant(path, change), sockets, roots, 86400)
                self.assertTrue(found or fresh == base, (path, change))
                self.assertEqual(found, [], (path, change))


class DocumentedAnswersTest(ProxyBase):
    """Calls the docs say are not available, and ones they say are scoped, behave as written."""

    async def test_image_networks_and_volume_management_calls_are_not_allowed(self):
        for method, target in (
            ("POST", "/images/img/tag?repo=x"),
            ("POST", "/images/img/push"),
            ("DELETE", "/images/img"),
            ("POST", "/networks/create"),
            ("POST", "/networks/bridge/connect"),
            ("DELETE", "/networks/bridge"),
            ("DELETE", "/volumes/data"),
            ("POST", "/volumes/prune"),
            ("POST", "/images/prune"),
            ("POST", "/commit?container=x"),
        ):
            status, reply = await self.call(method, target, body=b"{}" if method == "POST" else None)
            self.assertEqual((status, reply["rules"][0]), (403, "endpoint-not-allowed"), target)
        self.assertEqual(self.daemon.requests, [])

    async def test_rm_takes_only_v_and_force_and_only_in_the_tree(self):
        ref = FULL["mine"]
        self.assertEqual((await self.call("DELETE", f"/containers/{ref}?v=1&force=1"))[0], 204)
        self.assertEqual(
            (await self.call("DELETE", f"/containers/{ref}?link=1"))[1]["rules"][0], "query-not-allowed"
        )
        self.assertEqual(
            (await self.call("DELETE", f"/containers/{FULL['other']}?v=1"))[1]["rules"][0], "not-owned"
        )
        self.assertEqual(self.forwarded("DELETE", "/containers")[0][1], f"/containers/{ref}?v=1&force=1")

    async def test_exec_create_fields_are_an_allowlist(self):
        ok = {
            "Cmd": ["id"],
            "User": "1000",
            "Env": ["A=1"],
            "WorkingDir": "/w",
            "Tty": True,
            "AttachStdin": True,
        }
        self.assertEqual((await self.call("POST", "/containers/mine/exec", body=ok))[0], 201)
        self.assertEqual(json.loads(self.forwarded("POST", "/exec")[0][3]), ok)
        self.assertEqual(
            (await self.call("POST", "/containers/mine/exec", body={"Cmd": ["id"], "Mounts": []}))[0], 403
        )


class NetworkAndDeviceTest(ProxyBase):
    async def create(self, networking=None, **host):
        body = self.create_body(**host)
        if networking:
            body["NetworkingConfig"] = networking
        return await self.call("POST", "/containers/create", body=body)

    def looked_up(self):
        return [r[1] for r in self.daemon.requests if "/networks/" in r[1]]

    async def test_networks_named_by_name_or_id_must_resolve_to_a_bridge_driver(self):
        for host in (
            {"NetworkMode": "lan"},
            {"NetworkMode": "m" * 64},
            {"NetworkMode": "vlan"},
            {"NetworkMode": "nowhere"},
            {"NetworkMode": "../x"},
            {"networkmode": "host"},
        ):
            status, reply = await self.create(**host)
            self.assertEqual(status, 403, host)
            self.assertIn(reply["rules"][0], ("network-driver", "host-namespace"), host)
        status, reply = await self.create({"EndpointsConfig": {"lan": {}}})
        self.assertEqual((status, reply["rules"][0]), (403, "network-driver"))
        status, reply = await self.create({"EndpointsConfig": {"bridge": {"NetworkID": "m" * 64}}})
        self.assertEqual((status, reply["rules"][0]), (403, "network-driver"))
        status, reply = await self.create({"endpointsconfig": {"bridge": {"networkid": "m" * 64}}})
        self.assertEqual((status, reply["rules"][0]), (403, "network-driver"))
        self.assertEqual(self.forwarded("POST", "/containers/create"), [])

    async def test_bridge_networks_by_name_or_id_pass_and_none_and_default_need_no_lookup(self):
        self.assertEqual((await self.create(NetworkMode="appnet"))[0], 201)
        self.assertEqual((await self.create(NetworkMode="b" * 64))[0], 201)
        self.assertEqual(
            (await self.create({"EndpointsConfig": {"appnet": {"NetworkID": "b" * 64}}}))[0], 201
        )
        self.daemon.requests.clear()
        for mode in ("none", "default", ""):
            self.assertEqual((await self.create(NetworkMode=mode))[0], 201, mode)
        self.assertEqual(self.looked_up(), [])

    async def test_start_resolves_the_networks_the_container_is_on(self):
        mine = self.daemon.containers["mine"]
        mine["NetworkSettings"] = {"Networks": {"bridge": {"NetworkID": "b" * 64}}}
        self.assertEqual((await self.call("POST", f"/containers/{FULL['mine']}/start"))[0], 204)
        for where, value in (("lan", {}), ("bridge", {"NetworkID": "m" * 64})):
            mine["NetworkSettings"] = {"Networks": {where: value}}
            status, reply = await self.call("POST", f"/containers/{FULL['mine']}/start")
            self.assertEqual((status, reply["rules"][0]), (403, "network-driver"), where)
        mine["NetworkSettings"] = {}
        mine["HostConfig"]["NetworkMode"] = "lan"
        self.assertEqual(
            (await self.call("POST", f"/containers/{FULL['mine']}/start"))[1]["rules"][0], "network-driver"
        )

    async def test_the_build_network_is_resolved_too(self):
        for mode in ("lan", "m" * 64, "vlan", "nowhere"):
            status, reply = await self.call("POST", f"/build?networkmode={mode}", body=b"")
            self.assertEqual((status, reply["rules"][0]), (403, "network-driver"), mode)
        for mode in ("appnet", "none", "default", ""):
            self.assertEqual((await self.call("POST", f"/build?networkmode={mode}", body=b""))[0], 200, mode)

    async def test_only_plain_nvidia_gpu_requests_are_device_requests(self):
        bad = (
            {"Driver": "cdi", "Capabilities": [["gpu"]], "DeviceIDs": ["vendor.com/x=all"]},
            {"Driver": "", "Capabilities": [["gpu"]], "DeviceIDs": ["vendor.com/x=all"]},
            {"Driver": "nvidia", "Capabilities": [["gpu"]], "DeviceIDs": ["/dev/sda"]},
            {"Driver": "nvidia", "Capabilities": [["gpu"]], "Options": {"mount": "/"}},
            {"Driver": "nvidia", "Capabilities": [["utility"]]},
            {"Driver": "other", "Capabilities": [["gpu"]]},
        )
        for request in bad:
            body = self.create_body(DeviceRequests=[request])
            body["Labels"]["partyline.gpu-mem-mb"] = "9000"
            status, reply = await self.call("POST", "/containers/create", body=body)
            self.assertEqual((status, reply["rules"][0]), (403, "device-request"), request)
        for ids in ([], ["0", "1"], ["GPU-3f2c1a9e-1111-2222-3333-444455556666"]):
            ok = {
                "Driver": "nvidia",
                "Count": -1 if not ids else 0,
                "Capabilities": [["gpu"]],
                "DeviceIDs": ids,
            }
            body = self.create_body(DeviceRequests=[ok])
            body["Labels"]["partyline.gpu-mem-mb"] = "9000"
            self.assertEqual((await self.call("POST", "/containers/create", body=body))[0], 201, ids)


class InspectFallthroughTest(ProxyBase):
    """`docker inspect <name>` tries containers, then images, networks and volumes: lookups pass."""

    async def test_a_missing_container_then_network_then_volume_reads_as_on_a_raw_socket(self):
        status, reply = await self.call("GET", "/containers/nothing-here/json")
        self.assertEqual((status, reply["message"]), (404, "No such container: nothing-here"))
        status, reply = await self.call("GET", "/networks/nothing-here")
        self.assertEqual((status, reply), (404, {"message": "network nothing-here not found"}))
        status, reply = await self.call("GET", "/volumes/nothing-here")
        self.assertEqual((status, reply), (404, {"message": "get nothing-here: no such volume"}))
        self.assertEqual(self.call_rules(reply), [])

    @staticmethod
    def call_rules(reply):
        return reply.get("rules", []) if isinstance(reply, dict) else []

    async def test_a_volume_lookup_is_forwarded_by_name_and_takes_no_query(self):
        self.assertEqual(await self.call("GET", "/volumes/data"), (200, {"Name": "data", "Driver": "local"}))
        self.assertEqual(self.forwarded("GET", "/volumes/data")[0][1], "/volumes/data")
        status, reply = await self.call("GET", "/volumes/data?filters=x")
        self.assertEqual((status, reply["rules"][0]), (403, "query-not-allowed"))
        for target, rule in (
            ("/volumes/da%20ta", "malformed-path"),
            ("/volumes/../x", "malformed-path"),
            ("/volumes/-x", "endpoint-not-allowed"),
        ):
            self.assertEqual((await self.call("GET", target))[1]["rules"][0], rule, target)

    async def test_a_network_shows_only_this_trees_containers(self):
        status, net = await self.call("GET", "/networks/appnet")
        self.assertEqual(status, 200)
        self.assertEqual(
            list(net["Containers"]), [FULL["mine"]]
        )  # another tree's, and a vanished one, hidden
        self.assertEqual((net["Name"], net["Driver"]), ("appnet", "bridge"))
        self.assertNotIn("Services", net)
        self.assertNotIn("Peers", net)
        self.assertNotIn("elsewhere", json.dumps(net))
        self.assertNotIn(FULL["other"], json.dumps(net))

    async def test_one_tree_filtered_list_decides_with_no_per_container_inspects(self):
        self.daemon.attached["appnet"] = ["mine", "other", "gone", "running", "sibling"]
        await self.call("GET", "/networks/appnet")
        lists = [r for r in self.daemon.requests if "/containers/json" in r[1]]
        inspects = [
            r
            for r in self.daemon.requests
            if r[1].startswith("/containers/") and "/json" in r[1] and "/containers/json" not in r[1]
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(inspects, [])
        target = unquote(lists[0][1])
        self.assertIn("all=1", target)
        self.assertIn('"partyline.tree=root"', target)

    async def test_a_swarm_endpoint_key_and_an_unlisted_id_are_not_shown(self):
        self.daemon.attached["appnet"] = ["mine", "lb-appnet"]
        _status, net = await self.call("GET", "/networks/appnet")
        self.assertEqual(list(net["Containers"]), [FULL["mine"]])

    async def test_a_failed_list_shows_no_containers_instead_of_all_of_them(self):
        self.daemon.list_status = 500
        status, net = await self.call("GET", "/networks/appnet")
        self.assertEqual((status, net["Containers"]), (200, {}))
        self.assertEqual((net["Name"], net["Driver"]), ("appnet", "bridge"))

    async def test_a_status_the_standard_library_does_not_know_is_still_relayed(self):
        self.assertEqual(await self.call("GET", "/networks/odd"), (299, {"message": "an unusual status"}))
        from partyline.docker_proxy import phrase, reply

        self.assertEqual((phrase(404), phrase(299)), ("Not Found", "Status"))
        sink = SimpleNamespace(data=b"", write=lambda data: setattr(sink, "data", sink.data + data))
        reply(sink, 299, "odd")
        self.assertTrue(sink.data.startswith(b"HTTP/1.1 299 Status\r\n"))

    async def test_a_network_with_nothing_of_ours_shows_an_empty_list(self):
        self.daemon.attached["appnet"] = ["other"]
        status, net = await self.call("GET", "/networks/appnet")
        self.assertEqual((status, net["Containers"]), (200, {}))
        self.daemon.attached["appnet"] = []
        self.assertEqual((await self.call("GET", "/networks/appnet"))[1]["Containers"], {})

    async def test_the_tree_decides_not_the_line(self):
        self.daemon.attached["appnet"] = ["sibling", "mine"]
        status, net = await self.call("GET", "/networks/appnet")
        self.assertEqual(status, 200)
        self.assertIn(FULL["mine"], net["Containers"])

    async def test_only_verbose_and_scope_reach_the_daemon(self):
        await self.call("GET", "/networks/appnet?verbose=true&scope=local")
        self.assertEqual(
            self.forwarded("GET", "/networks/appnet")[0][1], "/networks/appnet?verbose=true&scope=local"
        )
        status, reply = await self.call("GET", "/networks/appnet?filters=x")
        self.assertEqual((status, reply["rules"][0]), (403, "query-not-allowed"))

    async def test_listing_creating_changing_and_removing_networks_stays_refused(self):
        for method, target in (
            ("GET", "/networks"),
            ("POST", "/networks/create"),
            ("POST", "/networks/appnet/connect"),
            ("POST", "/networks/appnet/disconnect"),
            ("DELETE", "/networks/appnet"),
            ("POST", "/networks/prune"),
            ("POST", "/networks/appnet"),
            ("DELETE", "/volumes/data"),
            ("PUT", "/volumes/data"),
            ("POST", "/volumes/data"),
        ):
            status, reply = await self.call(method, target, body=b"{}" if method != "GET" else None)
            self.assertEqual((status, reply["rules"][0]), (403, "endpoint-not-allowed"), (method, target))
        self.assertEqual(self.daemon.requests, [])


if __name__ == "__main__":
    unittest.main()
