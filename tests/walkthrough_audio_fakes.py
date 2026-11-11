"""Deterministic PCM fixtures and a real HTTP recognizer with no external API."""

from array import array
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import threading
import wave

from partyline.walkthrough_audio import RATE


def wav(spans=(), duration=9, rate=RATE, channels=1):
    samples = array("h", [0]) * int(duration * rate)
    for start, end, value in spans:
        first, last = int(start * rate), int(end * rate)
        samples[first:last] = array("h", [value]) * (last - first)
    output = BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        target.writeframes(samples.tobytes())
    return output.getvalue()


PASSAGES = ((1, 2, 3000), (4, 5, 6000), (7, 8, 9000))


@contextmanager
def recognizer(count, native=False, outro=False):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            message = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
            fields = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True)
                      for p in message.iter_parts()}
            with wave.open(BytesIO(fields["file"]), "rb") as source:
                pcm = array("h", source.readframes(source.getnframes()))
                duration = source.getnframes() / source.getframerate()
            seen.append((self.path, fields, duration))
            word = {3000: "Open the asset panel", 6000: "Select the mesh",
                    9000: "Preview the result"}[max(pcm)]
            if outro and max(pcm) == 6000:
                word = "Thanks for watching. Bye!"
            payload = {"text": word, "languages": [{"code": "en"}]}
            if native:
                payload["segments"] = [{"start": 1.1, "end": 1.9, "text": word}]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 0.2  # failure bound only; successful requests resolve immediately

        def accept():
            for _ in range(count):
                server.handle_request()

        worker = threading.Thread(target=accept, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", seen
        finally:
            worker.join(timeout=0.8)
            if worker.is_alive():
                raise AssertionError("fake recognizer did not receive the expected requests")
