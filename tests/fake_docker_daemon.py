"""A fake Docker daemon on a temp unix socket: containers, exec ids, upgrades; every request recorded."""

import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit

GB = 1024**3
FULL = {
    name: ch * 64
    for name, ch in {
        "mine": "1",
        "unlimited": "2",
        "other": "3",
        "running": "4",
        "gpu": "5",
        "gpu2": "6",
    }.items()
}


def container(name, state, conv, memory, managed=True, gpu=False, extra_labels=None):
    labels = {} if conv is None else {"partyline.conversation": conv}
    if managed:
        labels.update({"partyline.managed": "1", "partyline.max-seconds": "600"})
    if gpu:
        labels["partyline.gpu-mem-mb"] = "9000"
    labels.update(extra_labels or {})
    host = {
        "Memory": memory,
        "MemorySwap": memory,
        "NanoCpus": 10**9 if memory else 0,
        "PidsLimit": 100 if memory else 0,
        "DeviceRequests": [{"Driver": "nvidia", "Capabilities": [["gpu"]]}] if gpu else None,
    }
    return {
        "Id": FULL[name],
        "Name": "/" + name,
        "State": {"Status": state, "StartedAt": "2026-10-13T10:00:00Z"},
        "Config": {"Labels": labels},
        "HostConfig": host,
        "Names": ["/" + name],
        "Labels": labels,
        "Image": "img",
    }


class FakeDaemon:
    def __init__(self, path):
        self.path = path
        self.requests: list[tuple[str, str, dict, bytes]] = []
        self.containers = {
            "mine": container("mine", "exited", "line", 4 * GB),
            "unlimited": container("unlimited", "exited", "line", 0, managed=False),
            "other": container("other", "running", "elsewhere", 4 * GB),
            "running": container("running", "running", "line", 8 * GB),
            "gpu": container("gpu", "exited", "line", 4 * GB, gpu=True),
            "gpu2": container("gpu2", "running", "line", 4 * GB, gpu=True),
        }
        self.execs = {"a" * 12: FULL["mine"], "b" * 12: FULL["other"]}
        self.server = None

    async def start(self):
        self.server = await asyncio.start_unix_server(self.handle, self.path)

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    def find(self, ref):
        return next(
            (c for c in self.containers.values() if c["Id"].startswith(ref) or c["Name"] == "/" + ref), None
        )

    def seen(self, method, fragment):
        return [r for r in self.requests if r[0] == method and fragment in r[1]]

    async def handle(self, reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return
        lines = head.decode().split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
        headers = {k.lower(): v for k, v in (line.split(": ", 1) for line in lines[1:] if ": " in line)}
        body = await reader.readexactly(int(headers.get("content-length", 0)))
        self.requests.append((method, target, headers, body))
        status, payload, upgrade = self.route(method, target, body, headers)
        if upgrade:
            writer.write(b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n")
            await writer.drain()
            while data := await reader.read(1024):
                writer.write(data.upper())
                await writer.drain()
        else:
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            writer.write(
                f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nConnection: close\r\n"
                f"Content-Length: {len(raw)}\r\n\r\n".encode()
                + raw
            )
        await writer.drain()
        writer.close()

    def route(self, method, target, body, headers):
        parts = urlsplit(target)
        path = re.sub(r"^/v[0-9.]+", "", parts.path)
        query = parse_qs(parts.query)
        if path == "/_ping":
            return 200, b"OK", False
        if path == "/containers/json":
            wanted = [x.split("=", 1) for x in json.loads(query.get("filters", ["{}"])[0]).get("label", [])]
            rows = [
                c
                for c in self.containers.values()
                if c["State"]["Status"] == "running" or "all" in query
                if all(c["Labels"].get(k) == v for k, v in wanted)
            ]
            return 200, [{**c, "State": c["State"]["Status"]} for c in rows], False
        if path == "/containers/create":
            created = json.loads(body)
            new = {
                "Id": "9" * 64,
                "Name": "/new",
                "State": {"Status": "created"},
                "Config": {"Labels": created.get("Labels", {})},
                "HostConfig": created["HostConfig"],
                "Labels": created.get("Labels"),
            }
            self.containers["new"] = new
            return 201, {"Id": new["Id"]}, False
        if m := re.fullmatch(
            r"/containers/([^/]+)/(json|start|stop|restart|kill|exec|attach|logs|update)", path
        ):
            found = self.find(m.group(1))
            if found is None:
                return 404, {"message": "no such container"}, False
            op = m.group(2)
            if op == "json":
                return 200, found, False
            if op == "exec":
                return 201, {"Id": "c" * 12}, False
            if op == "attach" and headers.get("upgrade") == "tcp":
                return 101, b"", True
            if op in ("start", "restart"):
                found["State"]["Status"] = "running"
            if op in ("stop", "kill"):
                found["State"]["Status"] = "exited"
            return 204, b"", False
        if m := re.fullmatch(r"/containers/([^/]+)", path):
            if method == "DELETE" and self.find(m.group(1)):
                return 204, b"", False
        if m := re.fullmatch(r"/exec/([0-9a-f]+)/(json|start)", path):
            if m.group(2) == "json":
                owner = self.execs.get(m.group(1))
                return (200, {"ContainerID": owner}, False) if owner else (404, {}, False)
            return (101, b"", True) if headers.get("upgrade") == "tcp" else (200, b"", False)
        return 200, {"path": path}, False
