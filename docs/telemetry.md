# Tool usage telemetry

Partyline measures the rendered text returned by every MCP tool call, including
errors and refused operations. This measures estimated context added by tools,
not model turn usage, billed tokens, tool input tokens or a provider tokenizer.
The line management dialog's **Usage** section and
`extras(op="tool_usage", args={})` show the same summary, sorted by total.
Use `include_descendants=true` to include sublines, `since` (Unix seconds) to
narrow the interval, and `group="tool"` to merge operations. The default is
`group="sub_op"`, separating operations, screen actions and then/refresh/query/more
flags. Percentiles use nearest rank over per-call text plus known image estimates;
latency p50 is calculated independently.

Records contain tool and known operation/action names, booleans for then,
refresh, query and more, rendered UTF-8 bytes and characters, estimated text
tokens, error status, elapsed milliseconds and timestamp. The server attributes
them to the authenticated attachment, its line and adapter. Unknown names become
`unknown`; unknown operation labels are discarded. No argument values, result
bodies, error messages, window titles, file names, paths or media IDs are stored.

Text uses `ceil(UTF-8 bytes / 4)` in `estimate_text_tokens`, labelled as an
estimate. Image dimensions are recorded when `get_media` delivers an image or
when a tool returns an inline image with dimensions. A frame/media reference
alone is text; its image is counted when fetched, avoiding double counting.
The generic inline hook accepts `type="image"` or `inline=true`, including nested
media references with width and height. Downloaded dimensions come from the
actual variant's bytes, without decoding its pixels.

The provider estimator table currently supports Claude adapters: fit the image
inside a 1568-pixel longest edge and 1.15 megapixels without upscaling, then
`ceil(resized width * resized height / 750)`. Other adapters report image cost
as **unknown**, never as a claimed zero. Totals add known image estimates to
text; summaries separately count images whose cost is unknown. These
approximations may differ from a particular model's resize rules or billing.

The MCP bridge keeps at most 256 waiting records and one batch of up to 32.
A batch fills, a one-shot two-second deadline after the first queued record,
or shutdown triggers a background flush. Overflow and transport failures drop
records without retries; tool calls never wait for HTTP telemetry. Shutdown
allows a bounded final flush. Metrics are best effort, so totals can undercount.

`POST /api/telemetry/tool-calls` accepts only attachment credentials;
`GET /api/telemetry/tool-calls/summary?conv_id=...&since=...&group=sub_op`
allows a person any line and a process its own line and descendants, including
on plain lines without a captain. Records expire after about 30 days, pruned
on ingestion and by the existing storage retention cleanup. Reads always
exclude expired records. Deleting a line deletes its records.
