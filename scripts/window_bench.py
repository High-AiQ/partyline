#!/usr/bin/env python3
"""Run consented window fixtures through Partyline MCP and save timings and verification."""
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit


try:
    from .window_bench_logic import (
        SCENARIOS, ax_observation, find_helper_version,
        confirms_refusal, estimate_tokens, image_tiers_in, percentile, verify_response,
    )
except ImportError:  # direct script execution
    from window_bench_logic import (
        SCENARIOS, ax_observation, find_helper_version,
        confirms_refusal, estimate_tokens, image_tiers_in, percentile, verify_response,
    )

def rpc(process, ident: int, method: str, params: dict) -> dict:
    message = {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    for line in process.stdout:
        response = json.loads(line)
        if response.get("id") == ident:
            if "error" in response:
                raise RuntimeError(response["error"])
            return response["result"]
    raise RuntimeError("Partyline MCP process ended before replying")


def call_tool(process, ident: int, name: str, arguments: dict) -> tuple[dict, int]:
    result = rpc(process, ident, "tools/call", {"name": name, "arguments": arguments})
    response_bytes = len(json.dumps(result, ensure_ascii=False).encode())
    content = result.get("content", [])
    if result.get("isError"):
        message = content[0].get("text", f"{name} failed") if content else f"{name} failed"
        raise ToolCallError(message, response_bytes)
    if not content or "text" not in content[0]:
        raise RuntimeError(f"{name} did not return a text response")
    return json.loads(content[0]["text"]), response_bytes


class ToolCallError(RuntimeError):
    def __init__(self, message: str, response_bytes: int):
        super().__init__(message)
        self.response_bytes = response_bytes


def element_id(answer: dict, query: str) -> str:
    lines = answer.get("lines", "")
    pattern = r'^\s*(\S+)\s+([A-Za-z][A-Za-z0-9_-]*)\s+"([^"]*)"'
    matches = [(ident, name) for ident, _kind, name in re.findall(pattern, lines, re.M)]
    exact = [ident for ident, name in matches if name.casefold() == query.casefold()]
    if len(exact) == 1:
        return exact[0]
    partial = [ident for ident, name in matches if query.casefold() in name.casefold()]
    if len(partial) == 1:
        return partial[0]
    raise RuntimeError(f"expected one accessible element named {query!r}, found {len(partial or exact)}")


def run(args) -> dict:
    started_at = datetime.now(UTC).isoformat()
    env = os.environ.copy()
    if args.connection:
        env["PARTYLINE_MCP_CONNECTION"] = args.connection
    if not env.get("PARTYLINE_MCP_CONNECTION"):
        raise RuntimeError("set PARTYLINE_MCP_CONNECTION or pass --connection")
    process = subprocess.Popen([sys.executable, "-m", "partyline.mcp"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, env=env)
    rows = []
    ident = 1
    try:
        rpc(process, ident, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                             "clientInfo": {"name": "window-bench", "version": "1"}})
        ident += 1
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        try:
            windows, _ = call_tool(process, ident, "screen_windows", {})
            ident += 1
            args.helper_version = find_helper_version(windows) or args.helper_version
        except Exception:
            pass
        for scenario in SCENARIOS:
            url = f"{args.base_url.rstrip('/')}/{scenario.fixture}.html"
            if scenario.fixture == "iframe-cross-origin" and args.cross_origin_url:
                url += "?crossOrigin=" + quote(args.cross_origin_url, safe=":/")
            input(f"Open this fixture in the granted Chrome window, then press Enter: {url}\n")
            row = {"scenario": scenario.name, "fixture": scenario.fixture, "action": scenario.action,
                   "tool": scenario.tool,
                   "transport": args.transport, "helper_version": args.helper_version}
            if scenario.manual:
                prompt = {
                    "file-input": "Select a harmless test file in the fixture input.",
                    "file-chooser": "Click the fixture button, then cancel the native chooser.",
                    "canvas": "Click the blue visual target on the canvas.",
                }[scenario.fixture]
                input(f"Perform this local action, then press Enter: {prompt}\n")
                observed, observe_bytes = call_tool(process, ident, "screen_elements", {
                    "window": args.window, "text": True, "refresh": True})
                ident += 1
                observed = ax_observation(observed)
                target = {"file-input": "target", "file-chooser": "chooser", "canvas": "canvas"}[
                    scenario.fixture]
                verified = verify_response({"observation": observed}, "event", target)
                tiers = image_tiers_in(observed)
                row.update({"status": "manual_verified" if verified["success"] else "failed",
                            "success": verified["success"], "response_bytes": observe_bytes,
                            "image_tiers": tiers, "estimated_tokens": estimate_tokens(observe_bytes, tiers),
                            "evidence": verified["evidence"], "note": "Input was performed by the user."})
                rows.append(row)
                continue
            action_start = None
            action_attempted = False
            action_refused = False
            query_bytes = action_bytes = observe_bytes = 0
            query, action = {}, {}
            try:
                query, query_bytes = {}, 0
                if scenario.tool == "screen_element_action" or scenario.action == "observe":
                    query, query_bytes = call_tool(process, ident, "screen_elements", {
                        "window": args.window, "query": f"={scenario.query}", "refresh": True})
                    ident += 1
                if scenario.action == "observe":
                    observed, observe_bytes = call_tool(process, ident, "screen_elements", {
                        "window": args.window, "text": True, "refresh": True})
                    ident += 1
                    observed = ax_observation(observed)
                    verified = verify_response({"observation": observed}, scenario.expected, scenario.target)
                    tiers = image_tiers_in(query, observed)
                    response_bytes = query_bytes + observe_bytes
                    row.update({"status": "verified" if verified["success"] else "failed",
                                "success": verified["success"],
                                "response_bytes": response_bytes, "image_tiers": tiers,
                                "estimated_tokens": estimate_tokens(response_bytes, tiers),
                                "transport_observed": query.get("source", args.transport),
                                "evidence": verified["evidence"]})
                    rows.append(row)
                    continue
                target_id = (element_id(query, scenario.query)
                             if scenario.tool == "screen_element_action" else None)
                action_args = {"window": args.window, **scenario.tool_args}
                if scenario.tool == "screen_element_action":
                    action_args.update({"element_id": target_id, "action": scenario.action})
                if scenario.value is not None:
                    action_args["value"] = scenario.value
                if scenario.then:
                    action_args["then"] = scenario.then
                action_start = time.perf_counter()
                action_attempted = True
                action, action_bytes = call_tool(process, ident, scenario.tool, action_args)
                action_refused = confirms_refusal(action)
                elapsed = (time.perf_counter() - action_start) * 1000
                row["wall_ms"] = round(elapsed, 3)
                action_start = None
                ident += 1
                observed, observe_bytes = call_tool(process, ident, "screen_elements", {
                    "window": args.window, "text": True, "refresh": True})
                ident += 1
                observed = ax_observation(observed)
                verified = verify_response({"observation": observed}, scenario.expected, scenario.target,
                                           scenario.value if scenario.action == "set_value" else None,
                                           action_refused=action_refused)
                tiers = image_tiers_in(query, action, observed)
                response_bytes = query_bytes + action_bytes + observe_bytes
                row.update({"status": "verified" if verified["success"] else "failed",
                            "success": verified["success"], "wall_ms": round(elapsed, 3),
                            "response_bytes": response_bytes, "image_tiers": tiers,
                            "estimated_tokens": estimate_tokens(response_bytes, tiers),
                            "transport_observed": query.get("source", action.get("source", args.transport)),
                            "evidence": verified["evidence"]})
            except Exception as exc:  # a missing element or refused action is a measured failure
                action_refused = action_attempted and confirms_refusal(str(exc))
                response_bytes = (query_bytes + action_bytes + observe_bytes
                                  + getattr(exc, "response_bytes", 0))
                tiers = image_tiers_in(query, action)
                if response_bytes:
                    row.update({"response_bytes": response_bytes, "image_tiers": tiers,
                                    "estimated_tokens": estimate_tokens(response_bytes, tiers)})
                if action_start is not None:
                    row["wall_ms"] = round((time.perf_counter() - action_start) * 1000, 3)
                if scenario.expected == "refused":
                    try:
                        observed, observed_bytes = call_tool(process, ident, "screen_elements", {
                            "window": args.window, "text": True, "refresh": True})
                        response_bytes += observed_bytes
                        ident += 1
                        observed = ax_observation(observed)
                        verified = verify_response({"observation": observed}, "refused", scenario.target,
                                                   action_refused=action_refused)
                        row.update({"status": "verified_refusal" if verified["success"] else "failed",
                                    "success": verified["success"], "error": str(exc),
                                    "response_bytes": response_bytes,
                                    "estimated_tokens": estimate_tokens(response_bytes),
                                    "evidence": verified["evidence"]})
                    except Exception:
                        row.update({"status": "failed", "success": False, "error": str(exc)})
                else:
                    row.update({"status": "failed", "success": False, "error": str(exc)})
            rows.append(row)
    finally:
        process.stdin.close()
        process.terminate()
        process.wait()
        process.stdout.close()
    measured = [row["wall_ms"] for row in rows if "wall_ms" in row]
    by_action = {}
    for row in rows:
        if "wall_ms" in row:
            by_action.setdefault(row["action"], []).append(row["wall_ms"])
    return {"schema_version": 1, "started_at": started_at,
            "transport": args.transport, "helper_version": args.helper_version,
            "steps": rows,
            "latency_ms": {"p50": percentile(measured, .50), "p95": percentile(measured, .95)},
            "latency_ms_by_action": {action: {"p50": percentile(values, .50), "p95": percentile(values, .95)}
                                     for action, values in by_action.items()},
            "totals": {"verified": sum(row.get("success") is True for row in rows),
                       "failed": sum(row.get("success") is False for row in rows),
                       "manual_verified": sum(row.get("status") == "manual_verified" for row in rows),
                       "manual_required": sum(row.get("status") == "manual_required" for row in rows),
                       "response_bytes": sum(row.get("response_bytes", 0) for row in rows),
                       "estimated_tokens": sum(row.get("estimated_tokens", 0) for row in rows)}}


def write_results(result: dict, output: Path) -> None:
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    steps = result["steps"]
    transport = f"Transport: {result['transport']} · helper: {result['helper_version']}"
    response = (f"Response: {result['totals']['response_bytes']} bytes · "
                f"~{result['totals']['estimated_tokens']} tokens")
    lines = ["# Window bench results", "", transport,
             f"Verified: {result['totals']['verified']} · failed: {result['totals']['failed']} · "
             f"manual verified: {result['totals']['manual_verified']} · pending: "
             f"{result['totals']['manual_required']}",
             f"Action latency p50/p95: {result['latency_ms']['p50']} / {result['latency_ms']['p95']} ms",
             response, "",
             "| Scenario | Result | ms | bytes | tokens |", "| --- | --- | ---: | ---: | ---: |"]
    lines.extend(f"| {row['scenario']} | {row['status']} | {row.get('wall_ms', '—')} | "
                 f"{row.get('response_bytes', '—')} | {row.get('estimated_tokens', '—')} |" for row in steps)
    lines.extend(["", "## Action latency", "", "| Action | p50 ms | p95 ms |", "| --- | ---: | ---: |"])
    lines.extend(f"| {action} | {values['p50']} | {values['p95']} |"
                 for action, values in result["latency_ms_by_action"].items())
    output.with_suffix(".md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-have-a-granted-window", action="store_true",
                        help="required consent acknowledgement")
    parser.add_argument("--base-url", required=True, help="Partyline host URL serving /lab/window-bench")
    parser.add_argument("--window", required=True, help="granted window id or title")
    parser.add_argument("--transport", choices=("extension", "remote-debugging", "uia"), required=True)
    parser.add_argument("--helper-version", required=True)
    parser.add_argument("--cross-origin-url", required=True,
                        help="second origin serving frame.html, for cross-origin fixture")
    parser.add_argument("--connection", help="MCP connection JSON; defaults to PARTYLINE_MCP_CONNECTION")
    parser.add_argument("--output", type=Path, default=Path("window-bench-results.json"))
    args = parser.parse_args()
    if not args.i_have_a_granted_window:
        parser.error("requires --i-have-a-granted-window after the person grants a Chrome window")
    base, cross = urlsplit(args.base_url), urlsplit(args.cross_origin_url)
    if (base.scheme, base.netloc) == (cross.scheme, cross.netloc):
        parser.error("--cross-origin-url must use a distinct origin from --base-url")
    result = run(args)
    write_results(result, args.output)
    print(f"Wrote {args.output} and {args.output.with_suffix('.md')}")
    return 0 if result["totals"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
