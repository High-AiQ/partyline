"""Bounded, lossy MCP telemetry: no HTTP, argument values or bodies on the call path."""

from collections import deque
from functools import lru_cache
from itertools import islice
import math
import threading
import time

from ..screen_timing_contract import extract
from . import catalog, tools_captain, tools_control, tools_tasks


def estimate_text_tokens(byte_count: int) -> int:
    """Provider-independent estimate, ceil(UTF-8 bytes / 4); not billed usage."""
    return (byte_count + 3) // 4


IMAGE_ESTIMATORS = {"claude": (1568, 1150000, 750), "unknown": None}


def estimate_image(width: int, height: int, adapter: str) -> dict:
    """Claude: fit 1568px longest edge and 1.15MP, never upscale; ceil(area/750)."""
    provider = "claude" if "claude" in adapter.lower() else "unknown"
    rule = IMAGE_ESTIMATORS[provider]
    tokens = None
    if rule:
        edge, pixels, divisor = rule
        scale = min(1, edge / max(width, height), math.sqrt(pixels / (width * height)))
        tokens = math.ceil(width * height * scale * scale / divisor)
    return {"width": width, "height": height, "provider": provider, "estimated_tokens": tokens}


@lru_cache(maxsize=1)
def operation_names():
    """Fixed vocabulary only: never turn an invalid operation into stored content."""
    state = {"actions": ["read", "write", "assign", "report", "notify", "read_reports"],
             "is_lead": True, "role": "lead", "kind": "machine", "dynamic_screen_tools": True,
             "screen_read": True, "screen_windows": True, "screen_control": True}
    return {t["name"] for role in ("lead", "implementer", "reviewer")
            for t in catalog.every_tool({**state, "role": role})} | {
        "extras", "captain", "unknown", *tools_captain.OPERATIONS, *tools_tasks.OPERATIONS,
        *catalog.SCREEN, *catalog.EXTRAS_OPS}


def dimensions(value, *, delivered=False):
    """Find delivered images generically; references alone cost no image tokens yet."""
    if isinstance(value, list):
        for item in value:
            yield from dimensions(item, delivered=delivered)
    elif isinstance(value, dict):
        inline = value.get("type") == "image" or value.get("inline") is True
        width, height = value.get("width"), value.get("height")
        if (delivered or inline) and type(width) is int and type(height) is int \
                and 0 < width <= 100000 and 0 < height <= 100000:
            yield width, height
        else:
            for item in value.values():
                yield from dimensions(item, delivered=delivered or inline)


def record(name, args, text, value, error, started, adapter=""):
    names = operation_names()
    tool = name if isinstance(name, str) and name in names else "unknown"
    op = args.get("op", "") if tool in ("extras", "captain") else ""
    op = op if isinstance(op, str) and op in names else ""
    inner = args.get("args", {}) if tool in ("extras", "captain") else args
    inner = inner if isinstance(inner, dict) else {}
    action = inner.get("action")
    allowed = tools_control.ELEMENT_ACTION_PROPERTIES["action"]["enum"]
    action = action if (op or tool) == "screen_element_action" and action in allowed else ""
    sub_op = op or action
    then = inner.get("then")
    flags = {"then": isinstance(then, dict), "refresh": inner.get("refresh") is True,
             "query": bool(inner.get("query")) or (isinstance(then, dict) and bool(then.get("query"))),
             "more": inner.get("more") is True}
    size = len(text.encode("utf-8"))
    images = [estimate_image(w, h, adapter) for w, h in islice(dimensions(
        value, delivered=(op or tool) == "get_media"), 32)] if not error else []
    return {"tool": tool, "sub_op": sub_op, "action": action, **flags, "result_bytes": size,
            "result_chars": len(text), "estimated_tokens": estimate_text_tokens(size),
            "is_error": error, "latency_ms": max(0, (time.perf_counter() - started) * 1000),
            "timestamp": time.time(), "images": images, "timing": extract(value)}


class Telemetry:
    """One bounded queue, one in-flight batch; failures drop, never retry or block calls."""

    def __init__(self, client, *, capacity=256, batch_size=32, delay=2, timer=threading.Timer):
        self.client, self.capacity, self.batch_size = client, capacity, batch_size
        self.delay, self.timer_factory = delay, timer
        self.queue = deque()
        self.lock = threading.Lock()
        self.timer = None
        self.worker = None
        self.closed = False

    def enqueue(self, item):
        with self.lock:
            if self.closed or len(self.queue) >= self.capacity:
                return
            self.queue.append(item)
            if len(self.queue) >= self.batch_size:
                self._start_locked()
            elif self.timer is None:
                # no-poll (d): one-shot deadline from the first queued metric, not state polling
                self.timer = self.timer_factory(self.delay, self.flush)
                self.timer.daemon = True
                self.timer.start()

    def _start_locked(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.worker is None and self.queue:
            self.worker = threading.Thread(target=self._send, daemon=True)
            self.worker.start()

    def flush(self):
        with self.lock:
            self._start_locked()

    def _send(self):
        while True:  # drain only queued work; no timer or polling
            with self.lock:
                batch = [self.queue.popleft() for _ in range(min(len(self.queue), self.batch_size))]
                if not batch:
                    self.worker = None
                    return
            try:
                self.client.request("POST", "/api/telemetry/tool-calls", {"records": batch}, timeout=1)
            except Exception:
                pass  # telemetry is lossy by design, including authentication and transport failures

    def close(self):
        with self.lock:
            self.closed = True
            self._start_locked()
            worker = self.worker
        if worker:
            worker.join(timeout=1.1)
