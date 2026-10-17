# Codex resume probe — after (2026-10-17)

This is the post-resume snapshot from the same service-managed attachment after normal service detach/resume. The resumed Codex session ID and attachment ID are recorded separately. Calls were not made through a manual CLI launch.

## Identity and registry

- Partyline attachment ID: `3ba5a31d-3f41-4a64-a384-396c9cd53ff1`
- Resumed Codex session ID: `01a14a1b-2f41-76f1-b65b-f6dc6c545ca1`
- Partyline identity/line: unavailable after resume because this registry exposed no Partyline tools
- Codex CLI version: not exposed by the available registry or sanitized startup log rows

The current tool registry was searched for every name containing `partyline`; the result was an empty list. Direct attempts to invoke `mcp__partyline__whoami({})` and `mcp__partyline__guide({})` also found both tools unavailable, so neither native call could run. This is the observed post-resume result, not an inference from configuration-file creation.

## Sanitized Codex startup-log result

Read-only SQLite query against this process's `CODEX_HOME/logs_2.sqlite`, bounded to 120 rows after the resumed startup window. The selection began at the resumed startup window (SQLite timestamp `1792244760`) and included `rmcp::*` targets and rows whose log body mentions `partyline`; `feedback_tags` target rows were excluded. Only timestamps, levels, targets, counts, and safe categorical summaries were emitted. No config, environment, feedback-tag, credential, or raw log-body values were emitted or copied into the report.

```text
selected rows returned: 84 (limit 120)
rmcp rows: 6
  rmcp::service: 4
  rmcp::handler::server: 1
  rmcp::transport::streamable_http_server::session::local: 1
rmcp rows mentioning Partyline: 0
Partyline-specific startup error rows in this post-resume selection: 0
```

The RMCP rows were initialization/service activity, but they did not identify a Partyline server. The log selection therefore has no Partyline-specific startup diagnostic to explain the missing registry tools. The registry result itself is direct evidence that this resumed Codex session did not expose Partyline tools. The log check does not establish whether a child server was attempted outside the selected rows or why the registry omitted it.
