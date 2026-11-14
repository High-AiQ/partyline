# Telemetry

## Tool usage telemetry

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
## Model usage per response

Alongside the estimated size of each tool result, Partyline records what the model actually
used for every response, because each turn re-sends the whole context and cache reads, cache
writes and output all count. The numbers come only from the structured transcripts partyline
already tails, never from the screen, and only for **Claude Code**, **Codex** and **OpenCode v2**.
Every other adapter records nothing and is untouched.

### What one record holds

Attachment, line and adapter; the model id when the transcript names one; uncached input, cache
read, cache write, output and reasoning tokens; the context size; the response's own timestamp; and
the **names** of the tools it called, with the operation for `extras` and `captain` and the
element action for `screen_element_action` (`extras:invoke`), the same labelling the tool-result
telemetry uses so the two tables join on (tool, operation); an operation outside the fixed
vocabulary is dropped. Tools that are not Partyline's keep a safe name (`Bash`, `exec`). No prompt, reply,
argument value, result, path or file name is stored; tool names with unsafe characters become
`unknown`. A response is one row, keyed by the transcript's response id, so a repeated line
updates it instead of adding another.

All three adapters are normalised to one meaning:

| column | meaning |
| --- | --- |
| input | prompt tokens that were not cached (Codex: its `input_tokens` minus `cached_input_tokens`) |
| cache read / cache write | cached prompt tokens read, and written to the cache |
| output | everything the model generated, reasoning included (OpenCode: its `output` plus `reasoning`) |
| reasoning | a breakdown of output, never added again |
| total | input + cache read + cache write + output |
| context | the prompt size of that response: input + cache read + cache write (Codex: `input_tokens`) |

### Model time

Each response also records how long the model took: the gap from the previous tool result or user
message to the response's completion, in milliseconds. The summary reports its nearest-rank p50 and
p95 (`p50_model_ms`, `p95_model_ms`, over `model_time_turns` responses) on every row and total, so
a slow run reads as model thinking or, by comparison with the tool-call telemetry, tool time. Only
a transcript that can say records it, and the others record nothing rather than a guess:

- **Claude Code**: from the latest non-sidechain `user` record before the message's first line to
  the message's last line, since its lines are written as each block completes.
- **Codex**: from the latest tool output or user message to the `token_usage_record`. A rollout with
  only `token_count` events records none.
- **OpenCode v2**: none. A row spans its tool executions, so its created-to-completed time is not
  model time.

A gap longer than an hour is dropped (a stopped process or a replay, not a model thinking).

### What each adapter measures

| adapter | source | notes |
| --- | --- | --- |
| Claude Code | JSONL `message.usage` (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `output_tokens_details.thinking_tokens`) | One line is written per content block and each repeats the message's usage; they are merged by message id (largest counts, all tool calls). Synthetic harness replies and compaction records do not. |
| Codex | rollout `token_usage_record` (its response id and per-response `usage`), else `token_count` `last_token_usage` | Tool calls since the previous record belong to the next one. Native calls have their JSON arguments decoded only to pick an allowlisted operation. A resumed process is relayed from its thread-history store, which holds no token counts, so its own rollout is read alongside for usage only. A `token_count` only counts when no record was seen, once per change of its cumulative total. Cache writes are recorded as reported, which has always been zero in observed rollouts. |
| OpenCode v2 | the completed assistant row's `tokens` (`input`, `output`, `reasoning`, `cache.read`, `cache.write`) | Each completed row is one response; an unfinished row waits. Partyline tool names are assumed to carry the `partyline_` prefix; without it the tool is still named, but extras and captain operations are not. |

Not measured:

- **Sub-agents and child sessions.** Claude Code writes sub-agent responses to separate files
  that are not tailed, and OpenCode child sessions are not read, so their spend is not counted.
- **Codex tool operations.** Codex runs tools through one `exec` code tool, so the tool is named
  `exec` and its operations are not visible; named calls (`wait`, `sleep`) are.
- **Anything before the process started.** A resumed CLI can show earlier history; only responses
  newer than this process's spawn count (a resume or restart-plan reattachment allows no clock slack,
  a fresh spawn five seconds), so a session is never charged twice. Resumed processes record like fresh ones.
- **Cost in money, and other adapters.**

### Reading it

`GET /api/telemetry/turns/summary?conv_id=...&since=...&group=sub_op&include_descendants=false`.
A person may read any line; a process its own line and descendants, with or without a captain.
`extras(op="turn_usage", args={})` calls the same route. The management dialog's **Model usage**
section shows it under the estimated results, with the same `tool · operation` label.

It returns:

- `rows`: per tool, and per operation of a tool, the **turns** that called it with the median and
  p95 (nearest rank) of their total tokens, plus the maximum and the sum. A turn that called
  three tools is counted whole in each of them, so rows say what a tool's turns cost, not what
  the tool itself cost, and rows must not be added together. Turns with no tool appear as
  `(no tool)`.
- `lines` and `attachments`: totals over the window, summed over responses, so they never
  double-count a multi-tool turn.
- `totals` and `basis` (the definition above).

### Retention

Records expire after about 30 days. They are pruned whenever a new response is stored and by the
storage retention cleanup, reads always exclude expired rows, and deleting a line deletes them.

Screen calls also store their compact, content-free `timing` object in tool-call metrics. See
[the UIA latency audit](screen-action-latency.md) for phase definitions and the ranked cost hypotheses.
