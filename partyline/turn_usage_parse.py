"""Read one model response's real token usage out of a structured transcript record.

Verified against real Claude Code JSONL, Codex rollout JSONL and OpenCode v2 session rows.
Every parser yields the same canonical turn: ``input`` is uncached prompt, ``cache_read`` and
``cache_write`` are cached prompt, ``output`` includes reasoning, and ``reasoning`` is only a
breakdown of ``output``. Tool names and sub-operation names are kept; arguments, results and
text are never read into a turn.
"""

from collections import OrderedDict
from datetime import datetime
import json
import time

from .turn_usage_labels import tool_label

OUTPUTS = ("function_call_output", "custom_tool_call_output")
NUMBERS = ("input", "cache_read", "cache_write", "output", "reasoning")


def count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def epoch(stamp) -> float:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def stamp(value) -> float | None:
    """A transcript timestamp as epoch seconds, or None; unlike ``epoch`` it never invents one."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


MAX_MODEL_MS = 3600 * 1000  # a longer gap is a stopped process or a replay, not a model thinking


def model_ms(started, ended) -> int | None:
    """The gap between the input a response answered and its completion, when both are known."""
    if started is None or ended is None:
        return None
    gap = round((ended - started) * 1000)
    return gap if 0 <= gap <= MAX_MODEL_MS else None


def make_turn(response_id, timestamp, *, model=None, input=0, cache_read=0, cache_write=0,
              output=0, reasoning=0, context=None, window=None, calls=(), model_ms=None) -> dict:
    return {"response_id": str(response_id), "timestamp": timestamp, "model_ms": model_ms,
            "model": model if isinstance(model, str) and model != "<synthetic>" else None,
            "input": count(input), "cache_read": count(cache_read), "cache_write": count(cache_write),
            "output": count(output), "reasoning": min(count(reasoning), count(output)),
            "context": context, "window": count(window) or None, "calls": list(dict.fromkeys(calls))}


class ClaudeTurns:
    """Claude Code writes one JSONL line per content block, each repeating the message's usage.

    The usage of a streamed message can grow between its lines, so numbers merge by maximum,
    tool calls accumulate under the message id, and a line that adds nothing is dropped.
    """

    def __init__(self, keep: int = 64):
        self._seen: OrderedDict[str, dict] = OrderedDict()
        self._keep = keep
        self._input_at = None

    def feed(self, record) -> dict | None:
        if isinstance(record, dict) and record.get("type") == "user" and not record.get("isSidechain"):
            self._input_at = stamp(record.get("timestamp"))  # a tool result or a person's message
            return None
        message = record.get("message") if isinstance(record, dict) else None
        if not isinstance(message, dict) or record.get("type") != "assistant":
            return None
        usage, ident = message.get("usage"), message.get("id")
        if not ident or not isinstance(usage, dict) or message.get("model") == "<synthetic>":
            return None
        details = usage.get("output_tokens_details")
        blocks = [block for block in message.get("content") or [] if isinstance(block, dict)]
        calls = [label for block in blocks if block.get("type") == "tool_use"
                 and (label := tool_label(block.get("name"), block.get("input")))]
        turn = make_turn(
            ident, epoch(record.get("timestamp")), model=message.get("model"),
            input=usage.get("input_tokens"), cache_read=usage.get("cache_read_input_tokens"),
            cache_write=usage.get("cache_creation_input_tokens"), output=usage.get("output_tokens"),
            reasoning=details.get("thinking_tokens") if isinstance(details, dict) else 0,
            calls=calls)
        # The input is fixed when the message's first line lands: its own tool results interleave later.
        earlier = self._seen.pop(ident, None)
        started, ended = (earlier["_input"], earlier["_end"]) if earlier else (self._input_at, None)
        written = stamp(record.get("timestamp"))
        turn["_input"], turn["_end"] = started, max(filter(None, (ended, written)), default=None)
        turn["model_ms"] = model_ms(started, turn["_end"])
        if earlier:
            for key in NUMBERS:
                turn[key] = max(turn[key], earlier[key])
            turn["calls"] = list(dict.fromkeys([*earlier["calls"], *turn["calls"]]))
            turn["timestamp"] = earlier["timestamp"]
        turn["context"] = turn["input"] + turn["cache_read"] + turn["cache_write"]
        self._seen[ident] = turn
        while len(self._seen) > self._keep:
            self._seen.popitem(last=False)
        if earlier and all(earlier[key] == turn[key] for key in (*NUMBERS, "calls", "model_ms")):
            return None
        return {key: value for key, value in turn.items() if not key.startswith("_")}


def _arguments(raw) -> dict | None:
    """A native call's JSON-encoded arguments, decoded only so the label can pick an allowlisted op."""
    if not isinstance(raw, str) or len(raw) > 4096:
        return None
    try:
        decoded = json.loads(raw)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


class CodexTurns:
    """Codex rollouts: tool calls precede the ``token_usage_record`` that closes their response.

    ``token_usage_record`` carries a response id and that response's own usage. Older rollouts
    carry only ``token_count`` events; those count when no record has been seen, once per change
    of ``total_token_usage``. Codex ``input_tokens`` includes its cached tokens and
    ``output_tokens`` includes reasoning.
    """

    def __init__(self):
        self._calls: list[str] = []
        self._model = None
        self._window = None
        self._records = False
        self._total = None
        self._input_at = None  # the last tool output or user message: where the model's turn began

    def feed(self, record) -> dict | None:
        payload = record.get("payload") if isinstance(record, dict) else None
        if not isinstance(payload, dict):
            return None
        kind, when = record.get("type"), record.get("timestamp")
        if kind == "turn_context" and isinstance(payload.get("model"), str):
            self._model = payload["model"]
        elif kind == "response_item" and payload.get("type") in ("function_call", "custom_tool_call"):
            if label := tool_label(payload.get("name"), _arguments(payload.get("arguments"))):
                self._calls.append(label)
        elif kind == "response_item" and payload.get("type") in OUTPUTS:
            self._input_at = stamp(when)
        elif kind == "event_msg" and (payload.get("type") == "user_message" or (
                payload.get("type") == "item_completed"
                and (payload.get("item") or {}).get("type") == "UserMessage")):
            self._input_at = stamp(when)
        elif kind == "event_msg" and payload.get("type") == "task_started":
            self._window = payload.get("model_context_window")
        elif kind == "token_usage_record" and isinstance(payload.get("usage"), dict):
            self._records = True
            return self._turn(payload.get("response_id"), when, payload["usage"], self._window)
        elif kind == "event_msg" and payload.get("type") == "token_count" and not self._records:
            info = payload.get("info")
            last = info.get("last_token_usage") if isinstance(info, dict) else None
            total = (info.get("total_token_usage") or {}).get("total_tokens") if last else None
            if isinstance(last, dict) and total != self._total:
                self._total = total
                return self._turn(f"total-{total}", when, last, info.get("model_context_window"))
        return None

    def _turn(self, response_id, written, usage, window) -> dict | None:
        calls, self._calls = self._calls, []
        started, self._input_at = self._input_at, None
        if not response_id:
            return None
        prompt, cached = count(usage.get("input_tokens")), count(usage.get("cached_input_tokens"))
        return make_turn(
            response_id, epoch(written), model=self._model, input=max(0, prompt - cached), cache_read=cached,
            cache_write=usage.get("cache_write_input_tokens"), output=usage.get("output_tokens"),
            reasoning=usage.get("reasoning_output_tokens"), context=prompt, window=window, calls=calls,
            # token_count-only rollouts carry no response boundary worth trusting.
            model_ms=model_ms(started, stamp(written)) if self._records else None)


def _state(part: dict) -> dict:
    return part["state"] if isinstance(part.get("state"), dict) else {}


class OpenCodeTurns:
    def feed(self, row) -> dict | None:
        return opencode_turn(*row)


def opencode_turn(ident, data) -> dict | None:
    """A completed OpenCode v2 assistant row; its ``reasoning`` is separate from ``output``."""
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    parts = [part for part in data.get("content") or [] if isinstance(part, dict)]
    calls = [label for part in parts if part.get("type") == "tool"
             and (label := tool_label(part.get("name"), _state(part).get("input")))]
    completed = (data.get("time") or {}).get("completed")
    reasoning = count(tokens.get("reasoning"))
    turn = make_turn(
        ident, completed / 1000 if isinstance(completed, (int, float)) else time.time(),
        model=model.get("id"), input=tokens.get("input"), cache_read=cache.get("read"),
        cache_write=cache.get("write"), output=count(tokens.get("output")) + reasoning,
        reasoning=reasoning, calls=calls)
    turn["context"] = turn["input"] + turn["cache_read"] + turn["cache_write"]
    return turn if turn["input"] + turn["cache_read"] + turn["cache_write"] + turn["output"] else None
