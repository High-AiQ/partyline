"""Storage, attribution, retention and nearest-rank summaries of tool estimates."""

import json
import time

from .mcp.telemetry import estimate_image, operation_names
from .tool_telemetry_contracts import UsageRow, UsageSummary
from .tool_telemetry_summary import query

RETENTION_SECONDS = 30 * 86400


def prune(db, now=None):
    db._exec("DELETE FROM tool_calls WHERE timestamp < ?",
             ((time.time() if now is None else now) - RETENTION_SECONDS,))


def store(db, attachment, records):
    now = time.time()
    names = operation_names()
    from .mcp.tools_control import ELEMENT_ACTION_PROPERTIES
    sub_ops = names | set(ELEMENT_ACTION_PROPERTIES["action"]["enum"]) | {""}
    rows = []
    for record in records:
        item = record.model_dump()
        # Even invalid calls cannot smuggle arbitrary text through operation labels.
        item["tool"] = item["tool"] if item["tool"] in names else "unknown"
        item["sub_op"] = item["sub_op"] if item["sub_op"] in sub_ops else ""
        item["action"] = (item["action"] if item["action"] in
                          ELEMENT_ACTION_PROPERTIES["action"]["enum"] else "")
        item["images"] = [estimate_image(i.width, i.height, attachment["adapter"])
                          for i in record.images]
        item["timestamp"] = min(now, item["timestamp"])
        if item["timestamp"] < now - RETENTION_SECONDS:
            continue
        rows.append((attachment["conv_id"], attachment["id"], attachment["adapter"],
                     item["timestamp"], json.dumps(item, separators=(",", ":"))))
    with db.lock:
        db.conn.executemany("INSERT INTO tool_calls(conv_id, attachment_id, adapter, timestamp, metrics) "
                            "VALUES(?,?,?,?,?)", rows)
        db.conn.commit()
    prune(db, now)
    return len(rows)


def summary(db, conv_id, line_ids, since, group="sub_op", include_descendants=False):
    since = max(since, time.time() - RETENTION_SECONDS)
    records = db._exec(query(len(line_ids), group), (*line_ids, since)).fetchall()
    rows = [UsageRow.model_validate(dict(row)) for row in records]
    return UsageSummary(conv_id=conv_id, since=since, include_descendants=include_descendants, rows=rows)
