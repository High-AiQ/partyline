# Codex resume probe — before (2026-10-17)

This is the pre-resume snapshot from the live service-managed Codex attachment. Calls below used this process's native Partyline tool registry. No separate CLI was launched. Raw outputs are bounded to the identity response and the guide's advertised tool names and schemas; no credentials, environment values, or configuration values are included.

## Identity

- Partyline identity: `luna-2`
- Partyline line: `mcp-live-verification` (`cfd0f111-6cf5-4707-bdaf-0a84c1050ca8`)
- Attachment ID: `3ba5a31d-3f41-4a64-a384-396c9cd53ff1`
- Codex session ID: not exposed by the native snapshot
- Codex CLI version: not exposed by the native calls or attached process context available for this snapshot

The service's manager-observed metadata reported `cli_session` as
`01a14a1b-2f41-76f1-b65b-f6dc6c545ca1` for this attachment on both normal
resumes. Both resumed process argvs began `codex resume 01a14a1b-2f41-76f1-b65b-f6dc6c545ca1 ...`;
the service constructs that argument from the attachment's recorded
`cli_session`. Thus, continuity between this
pre-resume native snapshot and the two resumed checks rests on service metadata,
not on an ID in the native output. No raw pre-detach `cli_session` API response
was retained. The matching ID shown in the native output below is the Partyline
attachment ID, not a Codex session ID.

## Native calls

`mcp__partyline__whoami({})` returned the following bounded projection; the
long `line.topic` field is omitted:

```json
{"identity":"luna-2","attachment_id":"3ba5a31d-3f41-4a64-a384-396c9cd53ff1","line":{"id":"cfd0f111-6cf5-4707-bdaf-0a84c1050ca8","name":"mcp-live-verification"},"role":"implementer","capabilities":["read","write"]}
```

`mcp__partyline__guide({})` returned title `Partyline MCP tools` and these registered names, with these schemas (bounded to the fields needed to identify each callable):

```json
{
  "title": "Partyline MCP tools",
  "tools": [
    {"name":"whoami","inputSchema":{"type":"object","properties":{},"required":[],"additionalProperties":false}},
    {"name":"guide","inputSchema":{"type":"object","properties":{"category":{"type":"string"},"topic":{"type":"string"}},"required":[],"additionalProperties":false}},
    {"name":"read_messages","inputSchema":{"type":"object","properties":{"conv_id":{"type":"string"},"after_id":{"type":"integer"},"before_id":{"type":"integer"},"around_id":{"type":"integer"},"limit":{"type":"integer","minimum":1,"maximum":50}},"required":[],"additionalProperties":false}},
    {"name":"notes","inputSchema":{"type":"object","properties":{"operation":{"type":"string","enum":["get","set"]},"scope":{"type":"string","enum":["line","tree","attachment"]},"conv_id":{"type":"string"},"notes":{"type":"string","maxLength":4000}},"required":["operation","scope"],"additionalProperties":false}},
    {"name":"goal","inputSchema":{"type":"object","properties":{"operation":{"type":"string","enum":["get","set"]},"conv_id":{"type":"string"},"goal":{"type":"string","maxLength":3000}},"required":["operation"],"additionalProperties":false}},
    {"name":"post_message","inputSchema":{"type":"object","properties":{"conv_id":{"type":"string"},"body":{"type":"string","minLength":1},"client_key":{"type":"string","minLength":1,"maxLength":64}},"required":["conv_id","body","client_key"],"additionalProperties":false}},
    {"name":"upload_file","inputSchema":{"type":"object","properties":{"conv_id":{"type":"string"},"path":{"type":"string"},"title":{"type":"string","maxLength":200},"description":{"type":"string","maxLength":2000},"body":{"type":"string","maxLength":3000},"client_key":{"type":"string","minLength":1,"maxLength":64}},"required":["path","client_key"],"additionalProperties":false}},
    {"name":"get_media","inputSchema":{"type":"object","properties":{"file_id":{"type":"string"},"variant":{"type":"string","enum":["original","thumb","slim","readable"]},"destination":{"type":"string"}},"required":["file_id","variant","destination"],"additionalProperties":false}},
    {"name":"react","inputSchema":{"type":"object","properties":{"message_id":{"type":"integer"},"emoji":{"type":"string"},"remove":{"type":"boolean"}},"required":["message_id","emoji"],"additionalProperties":false}}
  ]
}
```

The guide included no `captain` tool for this implementer attachment. Both native calls succeeded before detach/resume.
