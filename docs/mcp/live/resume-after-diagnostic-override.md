# DIAGNOSTIC OVERRIDE — Codex resume probe after override placement (2026-10-17)

This is a diagnostic-only result. At the time of the probe, the deployed adapter placed generated Partyline `-c` overrides before `resume`; that service-managed resume had no Partyline tools, as recorded in [`resume-after.md`](resume-after.md). For this single diagnostic resume, the captain changed only this attachment's command so the generated `mcp_servers.partyline.command`, `args`, and `env` overrides followed `resume <id>`. No preset or global configuration was changed. This result confirms the argument-order fix, but does not claim the patched adapter itself was deployed or live-tested.

## Identity and client

- Partyline identity: `luna-2` (role `implementer`)
- Attachment ID: `3ba5a31d-3f41-4a64-a384-396c9cd53ff1`
- Codex session ID: `01a14a1b-2f41-76f1-b65b-f6dc6c545ca1` (same session ID as the previous resumed check)
- Partyline line: `mcp-live-verification` (`cfd0f111-6cf5-4707-bdaf-0a84c1050ca8`)
- Codex CLI version: not exposed by the native calls or sanitized startup log rows

## Live registry and native calls

The live registry search returned these **all** names containing `partyline`:

```text
mcp__partyline__captain
mcp__partyline__get_media
mcp__partyline__goal
mcp__partyline__guide
mcp__partyline__notes
mcp__partyline__post_message
mcp__partyline__react
mcp__partyline__read_messages
mcp__partyline__upload_file
mcp__partyline__whoami
```

`mcp__partyline__whoami({})` succeeded. Bounded raw JSON projection of the result:

```json
{"identity":"luna-2","attachment_id":"3ba5a31d-3f41-4a64-a384-396c9cd53ff1","line":{"id":"cfd0f111-6cf5-4707-bdaf-0a84c1050ca8","name":"mcp-live-verification"},"role":"implementer","capabilities":["read","write"]}
```

`mcp__partyline__guide({})` succeeded. It returned title `Partyline MCP tools` and a `tools` array named:

```text
whoami, guide, read_messages, notes, goal, post_message, upload_file, get_media, react
```

The guide result's tool list and the registry-name search are recorded separately as returned. Both native calls succeeded after the diagnostic resume.

## Sanitized startup-log observation

Read-only SQLite query against this attachment's `CODEX_HOME/logs_2.sqlite`; bounded to the latest 120 selected rows matching `rmcp::*` targets or a log body mentioning `partyline`. The selection returned 97 rows, timestamps `1792244846`–`1792244997`. `feedback_tags` target rows were excluded. Only targets, timestamps, counts, and safe categorical markers were emitted; no raw log bodies or config, environment, feedback-tag, or credential values were copied.

```text
rmcp rows: 7
  rmcp::service: 5
  rmcp::handler::server: 1
  rmcp::transport::streamable_http_server::session::local: 1
rmcp rows mentioning Partyline: 1
Partyline-related title-generation invalid-transport rows in this selection: 0
```

At SQLite timestamp `1792244978`, the `rmcp::service` rows include initialization and tool-related markers; one of those rows mentions Partyline. This is consistent with the native registry and calls succeeding. The deployed-adapter resume result remains the comparison point in `resume-after.md` and failed to expose these tools.
