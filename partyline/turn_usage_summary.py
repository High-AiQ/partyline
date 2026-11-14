"""Summaries of recorded model usage: per tool or sub-operation, per line, per attachment."""

from collections import defaultdict
import json
import math
import time

from .turn_usage import RETENTION_SECONDS
from .turn_usage_contracts import AttachmentTotals, LineTotals, ToolRow, Totals, TurnSummary

BASIS = ("Actual model usage per response: input + cache read + cache write + output (output includes "
         "reasoning). A response is charged in full to every tool it called.")
NONE = "(no tool)"


def percentile(values, fraction):
    """Nearest rank: the smallest value with at least ``fraction`` of the values at or below it."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _totals(rows) -> dict:
    return {"turns": len(rows), "input_tokens": sum(r["input_tokens"] for r in rows),
            "cache_read_tokens": sum(r["cache_read_tokens"] for r in rows),
            "cache_write_tokens": sum(r["cache_write_tokens"] for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows),
            "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
            "total_tokens": sum(r["total_tokens"] for r in rows),
            "max_context_tokens": max((r["context_tokens"] or 0 for r in rows), default=0)}


def _grouped(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return groups


def tool_rows(rows, group="sub_op") -> list[ToolRow]:
    """A tool's row counts the turns that called it; with ``sub_op`` each operation also has its own."""
    groups = defaultdict(list)
    for row in rows:
        labels = json.loads(row["calls"]) or [NONE]
        keys = {(label.partition(":")[0], label.partition(":")[2] if group == "sub_op" else "")
                for label in labels}
        if group == "sub_op":
            keys |= {(label.partition(":")[0], "") for label in labels}
        for key in keys:
            groups[key].append(row["total_tokens"])
    result = [ToolRow(tool=tool, sub_op=sub, turns=len(tokens), p50_total_tokens=percentile(tokens, .5),
                      p95_total_tokens=percentile(tokens, .95), max_total_tokens=max(tokens),
                      total_tokens=sum(tokens)) for (tool, sub), tokens in groups.items()]
    return sorted(result, key=lambda r: (-r.total_tokens, r.tool, r.sub_op))


def summary(db, conv_id, line_ids, since, group="sub_op", include_descendants=False) -> TurnSummary:
    since = max(since, time.time() - RETENTION_SECONDS)
    marks = ",".join("?" for _ in line_ids)
    rows = db._exec(f"SELECT * FROM turn_usage WHERE conv_id IN ({marks}) AND timestamp >= ?",
                    (*line_ids, since)).fetchall()
    names = {att["id"]: att["name"] for line in line_ids for att in db.list_attachments(line)}
    lines = [LineTotals(conv_id=line, **_totals(found)) for line, found in _grouped(rows, "conv_id").items()]
    attachments = [AttachmentTotals(attachment_id=ident, conv_id=found[0]["conv_id"],
                                    adapter=found[0]["adapter"], name=names.get(ident), **_totals(found))
                   for ident, found in _grouped(rows, "attachment_id").items()]
    return TurnSummary(
        conv_id=conv_id, since=since, include_descendants=include_descendants, basis=BASIS,
        totals=Totals(**_totals(rows)), rows=tool_rows(rows, group),
        lines=sorted(lines, key=lambda t: -t.total_tokens),
        attachments=sorted(attachments, key=lambda t: -t.total_tokens))
