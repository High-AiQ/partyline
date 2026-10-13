import json
import os
import tempfile
import unittest
from urllib.parse import parse_qs

from partyline.docker_policy import Denied, create_problems, limit_problems, list_filters, parse_target
from partyline.docker_workloads import started_epoch

GB = 1024**3
LABELS = {"partyline.max-seconds": "600"}
LIMITS = {"Memory": 4 * GB, "MemorySwap": 4 * GB, "NanoCpus": 2 * 10**9, "PidsLimit": 256}
SOCK = {os.path.realpath("/run/docker.sock")}


def body(**host):
    return {"Image": "img", "Labels": dict(LABELS), "HostConfig": {**LIMITS, **host}}


class RouteTest(unittest.TestCase):
    def test_the_allowlist_classifies_each_call(self):
        cases = {
            ("GET", "/_ping"): "open",
            ("HEAD", "/_ping"): "open",
            ("GET", "/v1.43/version"): "open",
            ("GET", "/info"): "open",
            ("GET", "/events?since=1"): "open",
            ("GET", "/images/json"): "open",
            ("GET", "/images/nvcr.io/nvidia/x:1.2/json"): "image",
            ("POST", "/images/create?fromImage=alpine&tag=3"): "pull",
            ("GET", "/containers/json?all=1"): "list",
            ("POST", "/containers/create?name=x"): "create",
            ("DELETE", "/containers/abc123"): "container",
            ("GET", "/containers/abc/logs?stdout=1"): "container",
            ("POST", "/containers/abc/exec"): "container",
            ("POST", "/containers/abc/attach"): "container",
            ("POST", "/exec/" + "a" * 12 + "/start"): "exec",
            ("GET", "/exec/" + "a" * 12 + "/json"): "exec",
        }
        for (method, target), kind in cases.items():
            self.assertEqual(parse_target(method, target).kind, kind, (method, target))

    def test_everything_else_is_denied_by_default(self):
        for method, target in (
            ("POST", "/containers/abc/update"),
            ("POST", "/containers/abc/rename"),
            ("POST", "/containers/prune"),
            ("GET", "/volumes"),
            ("POST", "/networks/create"),
            ("POST", "/build"),
            ("DELETE", "/images/alpine"),
            ("GET", "/system/df"),
            ("GET", "/containers/abc/attach/ws"),
            ("POST", "/images/create/x"),
            ("PUT", "/containers/abc/archive"),
            ("GET", "/containers/abc/logs/extra"),
            ("POST", "/exec/zzzz/start"),
            ("GET", "/exec/" + "a" * 12 + "/start"),
        ):
            with self.assertRaises(Denied, msg=(method, target)) as caught:
                parse_target(method, target)
            self.assertEqual(caught.exception.status, 403)
            self.assertIn("rule:", caught.exception.message)

    def test_path_tricks_are_refused(self):
        for target in (
            "/containers/../version",
            "//version",
            "/containers/./json",
            "/containers/%6ason",
            "/containers\\json",
            "/containers/a b/json",
            "/containers/é/json",
            "relative",
            "/containers/abc/../../images/json",
        ):
            with self.assertRaises(Denied, msg=target):
                parse_target("GET", target)

    def test_the_version_prefix_is_kept_apart(self):
        route = parse_target("GET", "/v1.43/containers/abc/json?size=1")
        self.assertEqual(
            (route.prefix, route.ref, route.op, route.query), ("/v1.43", "abc", "json", [("size", "1")])
        )

    def test_the_list_is_narrowed_to_the_line_and_cannot_be_widened(self):
        route = parse_target("GET", "/containers/json?all=1&filters=" + json.dumps({"label": ["x=y"]}))
        query = parse_qs(list_filters(route, "line"))
        self.assertEqual(query["all"], ["1"])
        self.assertEqual(json.loads(query["filters"][0])["label"], ["x=y", "partyline.conversation=line"])
        other = parse_target(
            "GET", "/containers/json?filters=" + json.dumps({"label": ["partyline.conversation=b"]})
        )
        labels = json.loads(parse_qs(list_filters(other, "a"))["filters"][0])["label"]
        self.assertEqual(labels, ["partyline.conversation=b", "partyline.conversation=a"])  # ANDed: empty
        for bad in ("{", "[1]"):
            with self.assertRaises(Denied):
                list_filters(parse_target("GET", "/containers/json?filters=" + bad), "a")


class LimitsTest(unittest.TestCase):
    def test_a_complete_declaration_passes(self):
        self.assertEqual(create_problems(body(), SOCK, []), [])

    def test_every_missing_limit_is_named(self):
        cases = {
            "Memory": {"Memory": 0},
            "swap": {"MemorySwap": 8 * GB},
            "no swap field": {"MemorySwap": 0},
            "cpu": {"NanoCpus": 0},
            "pids": {"PidsLimit": 0},
            "unlimited pids": {"PidsLimit": -1},
            "bool memory": {"Memory": True},
        }
        for name, change in cases.items():
            self.assertTrue(limit_problems({**LIMITS, **change}, LABELS), name)
        self.assertEqual(limit_problems({**LIMITS, "NanoCpus": 0, "CpuQuota": 50000}, LABELS), [])
        for labels in ({}, {"partyline.max-seconds": "0"}, {"partyline.max-seconds": "soon"}):
            self.assertTrue(limit_problems(LIMITS, labels), labels)

    def test_gpu_requests_need_a_vram_label(self):
        gpu = [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}]
        self.assertTrue(limit_problems({**LIMITS, "DeviceRequests": gpu}, LABELS))
        self.assertEqual(
            limit_problems({**LIMITS, "DeviceRequests": gpu}, {**LABELS, "partyline.gpu-mem-mb": "9000"}), []
        )

    def test_refused_settings(self):
        for change in (
            {"Privileged": True},
            {"CapAdd": ["SYS_ADMIN"]},
            {"NetworkMode": "host"},
            {"NetworkMode": "container:abc"},
            {"PidMode": "host"},
            {"IpcMode": "host"},
            {"UTSMode": "host"},
            {"Devices": [{"PathOnHost": "/dev/sda"}]},
            {"DeviceRequests": [{"Driver": "other", "Capabilities": [["tpu"]]}]},
            {"VolumesFrom": ["other"]},
            {"SecurityOpt": ["seccomp=unconfined"]},
            {"CgroupParent": "/x"},
            {"UsernsMode": "host"},
            {"Mounts": [{"Type": "npipe", "Source": "x"}]},
        ):
            self.assertTrue(create_problems(body(**change), SOCK, []), change)
        for fine in (
            {"NetworkMode": "bridge"},
            {"Binds": ["named:/data"]},
            {"CapDrop": ["ALL"]},
            {"Mounts": [{"Type": "volume", "Source": "v", "Target": "/v"}]},
        ):
            self.assertEqual(create_problems(body(**fine), SOCK, []), [], fine)

    def test_bind_sources_stay_inside_the_lines_paths_and_never_expose_the_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.realpath(tmp)
            os.makedirs(os.path.join(work, "sub"))
            roots = [work]
            self.assertEqual(create_problems(body(Binds=[f"{work}/sub:/x:ro"]), SOCK, roots), [])
            self.assertEqual(
                create_problems(body(Mounts=[{"Type": "bind", "Source": work, "Target": "/w"}]), SOCK, roots),
                [],
            )
            for binds in (
                [f"{work}/../etc:/x"],
                ["/etc:/x"],
                ["/:/host"],
                ["/run/docker.sock:/s"],
                ["/var/run/docker.sock:/s"],
                ["/run:/r"],
                [f"{work}-evil:/x"],
            ):
                self.assertTrue(create_problems(body(Binds=binds), SOCK, roots), binds)
            link = os.path.join(work, "sock")
            os.symlink("/run/docker.sock", link)
            self.assertTrue(create_problems(body(Binds=[f"{link}:/s"]), SOCK, roots))
            self.assertTrue(
                create_problems(
                    body(Mounts=[{"Type": "bind", "Source": "/etc", "Target": "/e"}]), SOCK, roots
                )
            )

    def test_malformed_bodies(self):
        for bad in (
            None,
            [],
            {"Image": "i"},
            {"HostConfig": {}},
            {"Image": "i", "HostConfig": {}, "Labels": []},
        ):
            self.assertTrue(create_problems(bad, SOCK, []))


class StartedEpochTest(unittest.TestCase):
    def test_docker_timestamps_parse(self):
        self.assertEqual(started_epoch("2026-10-13T10:41:12.123456789Z"), 1791888072.123456)
        self.assertEqual(started_epoch("2026-10-13T10:41:12Z"), 1791888072.0)
        self.assertIsNone(started_epoch("0001-01-01T00:00:00Z"))
        self.assertIsNone(started_epoch(None))


if __name__ == "__main__":
    unittest.main()
