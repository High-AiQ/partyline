"""Record the ``containers/create`` body the installed ``docker`` CLI sends, as test fixtures.

Run it after upgrading Docker and before a release (docs/write-fence.md): it starts a fake
daemon on a Unix socket, runs the CLI through a spread of flag sets, and writes each body
with the CLI version to ``tests/fixtures/docker_create/<case>.json``. The proxy test then
runs every fixture through the create checks.

    python scripts/capture_docker_create.py
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "docker_create"
LIMITS = ["--memory", "16g", "--memory-swap", "16g", "--cpus", "8", "--pids-limit", "512", "--restart", "no"]
LABELS = ["--label", "partyline.max-seconds=3600", "--label", "partyline.gpu-mem-mb=8000"]
CASES = {
    "full-managed": [
        *LIMITS, "--gpus", "device=0", "-p", "127.0.0.1:8189:8189", "-v", "vol:/models", *LABELS],
    "limits-only": [*LIMITS, "--label", "partyline.max-seconds=60"],
    "bridge-network": [
        *LIMITS, "--network", "appnet", "--label", "partyline.max-seconds=60"],
    "env-workdir-entrypoint-user-name": [
        *LIMITS, "-e", "A=1", "-e", "B=two", "-w", "/work", "--entrypoint", "/bin/true",
        "--user", "1000:1000",
        "--name", "capture-test", "--label", "partyline.max-seconds=60"],
}
VERSION = {"ApiVersion": "1.56", "Version": "0", "MinAPIVersion": "1.24", "Os": "linux"}


def serve(listener: socket.socket, bodies: list[bytes]) -> None:
    while True:
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(65536)
        head, _, body = data.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        length = next((int(h.split(":")[1]) for h in lines[1:] if h.lower().startswith("content-length:")), 0)
        while len(body) < length:
            body += conn.recv(65536)
        if "/containers/create" in lines[0]:
            bodies.append(body)
            status, reply = "500 Internal Server Error", b'{"message":"captured"}'
        elif "/_ping" in lines[0]:
            status, reply = "200 OK", b"OK"
        else:
            status, reply = "200 OK", json.dumps(VERSION).encode()
        conn.sendall(f"HTTP/1.1 {status}\r\nApi-Version: 1.56\r\nContent-Type: application/json\r\n"
                     f"Content-Length: {len(reply)}\r\n\r\n".encode() + reply)
        conn.close()


def main() -> int:
    if not shutil.which("docker"):
        print("docker CLI not found", file=sys.stderr)
        return 1
    version = subprocess.run(
        ["docker", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    OUT.mkdir(parents=True, exist_ok=True)
    short = tempfile.mkdtemp(prefix="dcap.", dir="/var/tmp")  # a socket path is capped near 107 bytes
    path = os.path.join(short, "d.sock")
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(path)
    listener.listen(5)
    bodies: list[bytes] = []
    threading.Thread(target=serve, args=(listener, bodies), daemon=True).start()
    env = {**os.environ, "DOCKER_HOST": f"unix://{path}", "DOCKER_CONFIG": short}
    try:
        for case, flags in CASES.items():
            bodies.clear()
            subprocess.run(["docker", "create", *flags, "busybox"], env=env, capture_output=True, timeout=60)
            if len(bodies) != 1:
                print(f"{case}: expected one create body, saw {len(bodies)}", file=sys.stderr)
                return 1
            record = {"cli": version, "case": case, "args": flags, "body": json.loads(bodies[0])}
            (OUT / f"{case}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            print(f"{case}: captured with {version}")
    finally:
        listener.close()
        shutil.rmtree(short, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
