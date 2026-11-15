"""Bound diagnostic/eval replies as serialized UTF-8, including escaping and metadata."""
import json

from .screen_tree import OUT_BYTES
from .screen_tree_answer import size
from .screen_timing_contract import extract


def bounded(result):
    if size(result) <= OUT_BYTES:
        return result
    preview = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()[:3000]
    source, status = result.get("source"), result.get("status")
    source = source if source in ("cdp", "uia") else "cdp"
    status = (status if status in ("completed", "failed", "unconfirmed", "timeout", "no_effect")
              else "completed")
    reply = {"source": source, "status": status,
             "truncated": True, "result_preview": preview.decode("utf-8", errors="ignore")}
    if timing := extract(result):
        reply["timing"] = timing
    while size(reply) > OUT_BYTES:
        reply["result_preview"] = reply["result_preview"][:len(reply["result_preview"]) * 3 // 4]
    return reply
