"""Small transcript fixtures, one per adapter. SECRET strings must never reach the database."""

from datetime import UTC, datetime
import time

SECRET = "SECRET-CONTENT-DO-NOT-STORE"
NOW = time.time()


def iso(offset=0.0):
    return datetime.fromtimestamp(NOW + offset, UTC).isoformat().replace("+00:00", "Z")


def claude_line(message_id, content, usage, *, kind="assistant", offset=0.0, model="claude-sonnet-5-5"):
    return {"type": kind, "timestamp": iso(offset), "uuid": f"u-{offset}",
            "message": {"id": message_id, "model": model, "content": content, "usage": usage}}


def usage(inp, create, read, out, thinking=0):
    return {"input_tokens": inp, "cache_creation_input_tokens": create, "cache_read_input_tokens": read,
            "output_tokens": out, "output_tokens_details": {"thinking_tokens": thinking}}


THINKING = {"type": "thinking", "thinking": SECRET}
TEXT = {"type": "text", "text": SECRET}
BASH = {"type": "tool_use", "name": "Bash", "input": {"command": SECRET}}
CAPTAIN = {"type": "tool_use", "name": "mcp__partyline__captain",
           "input": {"op": "accept", "args": {"note": SECRET}}}
EXTRAS = {"type": "tool_use", "name": "mcp__partyline__extras",
          "input": {"op": "screen_element_action", "args": {"action": "invoke", "element": SECRET}}}
HOSTILE = {"type": "tool_use", "name": "mcp__partyline__extras",
           "input": {"op": SECRET, "args": {"action": SECRET}}}

# One streamed message: a line per content block, repeating (and growing) the same usage.
CLAUDE_STREAMED = [
    claude_line("msg_1", [THINKING], usage(2, 100, 900, 30, 10), offset=1),
    claude_line("msg_1", [TEXT], usage(2, 100, 900, 80, 25), offset=2),
    claude_line("msg_1", [BASH], usage(2, 100, 900, 80, 25), offset=3),
    claude_line("msg_1", [EXTRAS], usage(2, 100, 900, 80, 25), offset=4),
    claude_line("msg_2", [TEXT], usage(5, 0, 1000, 40), offset=5),
]


def codex(kind, payload, offset=0.0):
    return {"timestamp": iso(offset), "type": kind, "payload": payload}


def codex_usage(inp, cached, out, reasoning=0):
    return {"input_tokens": inp, "cached_input_tokens": cached, "cache_write_input_tokens": 0,
            "output_tokens": out, "reasoning_output_tokens": reasoning, "total_tokens": inp + out}


CODEX_ROLLOUT = [
    codex("event_msg", {"type": "task_started", "model_context_window": 475000}, 1),
    codex("turn_context", {"model": "gpt-6.1-sol", "cwd": SECRET}, 2),
    codex("response_item", {"type": "message", "content": [{"text": SECRET}]}, 3),
    codex("response_item", {"type": "custom_tool_call", "name": "exec", "input": SECRET}, 4),
    codex("token_usage_record", {"response_id": "resp_1", "usage": codex_usage(21000, 8000, 96, 11)}, 5),
    codex("event_msg", {"type": "token_count", "info": {
        "total_token_usage": codex_usage(21000, 8000, 96, 11),
        "last_token_usage": codex_usage(21000, 8000, 96, 11), "model_context_window": 475000}}, 5),
    codex("response_item", {"type": "function_call", "name": "wait", "arguments": SECRET}, 6),
    codex("response_item", {"type": "function_call", "name": "sleep", "namespace": "clock"}, 7),
    codex("token_usage_record", {"response_id": "resp_2", "usage": codex_usage(21400, 21000, 50)}, 8),
]

# Older rollouts: token_count only. The same cumulative total repeats when only rate limits change.
CODEX_OLD = [
    codex("response_item", {"type": "custom_tool_call", "name": "exec", "input": SECRET}, 1),
    codex("event_msg", {"type": "token_count", "info": None}, 2),
    codex("event_msg", {"type": "token_count", "info": {
        "total_token_usage": codex_usage(100, 20, 10), "last_token_usage": codex_usage(100, 20, 10),
        "model_context_window": 1000}}, 3),
    codex("event_msg", {"type": "token_count", "info": {
        "total_token_usage": codex_usage(100, 20, 10), "last_token_usage": codex_usage(100, 20, 10)}}, 4),
    codex("event_msg", {"type": "token_count", "info": {
        "total_token_usage": codex_usage(300, 120, 30), "last_token_usage": codex_usage(200, 100, 20)}}, 5),
]


def opencode_row(reasoning=380, output=201, completed=None, tools=({"name": "bash"},)):
    parts = [{"type": "reasoning", "text": SECRET}, {"type": "text", "text": SECRET}]
    for tool in tools:
        state = {"input": tool.get("input", {"command": SECRET}), "content": [{"text": SECRET}]}
        parts.append({"type": "tool", "name": tool["name"], "state": state})
    cache = {"read": 256640, "write": 7}
    tokens = {"input": 232, "output": output, "reasoning": reasoning, "cache": cache}
    done = completed or int((NOW + 1) * 1000)
    return {"model": {"providerID": "p", "id": "glm-5.3-flash"}, "content": parts, "finish": "stop",
            "tokens": tokens, "time": {"created": int(NOW * 1000), "completed": done}}
