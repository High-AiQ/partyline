"""Throwaway spike (Blender 5.2.2 under Xvfb): `xvfb-run -a blender --factory-startup --python spike.py`.
Loopback HTTP + secret, queue drained by a main-thread timer, settrace deadline, render inside a timer."""

import bpy
import sys
import threading
import queue
import json
import time
import io
import traceback
import os
import tempfile
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SECRET = "s3cret"
CAP = 2000
Q = queue.Queue()
T0 = time.time()


def log(*a):
    print("SPIKE", round(time.time() - T0, 2), *a, flush=True)


class Deadline(Exception):
    pass


def run_with_deadline(code, seconds):
    end = time.monotonic() + seconds

    def tracer(frame, event, arg):
        if time.monotonic() > end:
            raise Deadline(f"deadline {seconds}s exceeded")
        return tracer

    buf = io.StringIO()
    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        with redirect_stdout(buf):
            exec(compile(code, "<agent>", "exec"), {"bpy": bpy})
        out = buf.getvalue()
        return {"ok": True, "stdout": out[:CAP], "truncated": len(out) > CAP}
    except BaseException as e:
        return {
            "ok": False,
            "error": type(e).__name__,
            "message": str(e),
            "tb": traceback.format_exc()[-400:],
        }
    finally:
        sys.settrace(old)


def do(cmd):
    if cmd["op"] == "exec":
        return run_with_deadline(cmd["code"], cmd.get("timeout", 5))
    if cmd["op"] == "render":
        sc = bpy.context.scene
        sc.render.resolution_x = sc.render.resolution_y = cmd["size"]
        sc.render.engine = "BLENDER_WORKBENCH"
        path = os.path.join(tempfile.gettempdir(), "spike.png")
        sc.render.filepath = path
        t = time.time()
        bpy.ops.render.render(write_still=True)
        return {"ok": True, "bytes": os.path.getsize(path), "secs": round(time.time() - t, 2)}


def drain():
    try:
        while True:
            cmd, box = Q.get_nowait()
            box["r"] = do(cmd)
            box["ev"].set()
    except queue.Empty:
        pass
    return 0.05


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + SECRET:
            self.send_response(401)
            self.end_headers()
            return
        cmd = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        box = {"ev": threading.Event()}
        Q.put((cmd, box))
        if not box["ev"].wait(cmd.get("wait", 30)):
            body = {"ok": False, "error": "no-answer"}
        else:
            body = box["r"]
        b = json.dumps(body).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
bpy.app.timers.register(drain, persistent=True)


def call(cmd, secret=SECRET):
    r = Request(f"http://127.0.0.1:{PORT}/", json.dumps(cmd).encode(), {"Authorization": "Bearer " + secret})
    try:
        return json.loads(urlopen(r, timeout=60).read())
    except HTTPError as e:
        return {"http": e.code}


def client():
    time.sleep(1)
    log("no secret ->", call({"op": "exec", "code": "pass"}, "bad"))
    log("exec ->", call({"op": "exec", "code": "print(len(bpy.data.objects))"}))
    log("error ->", call({"op": "exec", "code": "x=1\nraise ValueError('boom')"})["tb"][-80:])
    log(
        "big out ->",
        {k: v for k, v in call({"op": "exec", "code": "print('x'*100000)"}).items() if k != "stdout"},
    )
    t = time.time()
    r = call({"op": "exec", "code": "while True: pass", "timeout": 1})
    log("runaway ->", r["error"], round(time.time() - t, 2), "s")
    t = time.time()
    r = call({"op": "exec", "code": "import time\nwhile True: time.sleep(0.01)", "timeout": 1})
    log("sleepy loop ->", r["error"], round(time.time() - t, 2), "s")
    t = time.time()
    r = call({"op": "exec", "code": "sum(range(10**9))", "timeout": 1})
    log("single C call 1e9 ->", r.get("error") or "completed", round(time.time() - t, 2), "s")
    log("after runaway still alive ->", call({"op": "exec", "code": "print('alive')"}))
    log("render ->", call({"op": "render", "size": 256}))
    log("render again ->", call({"op": "render", "size": 512}))
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.1)


threading.Thread(target=client, daemon=True).start()
