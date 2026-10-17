# Live Codex Partyline MCP check — luna (2026-10-17)

This is the initial fresh-session check, before the resumed-session diagnosis
and adapter fix. For the decisive same-attachment comparison, see
[`resume-before.md`](resume-before.md), [`resume-after.md`](resume-after.md),
and [`resume-after-diagnostic-override.md`](resume-after-diagnostic-override.md).

This records calls made from luna's actual service-managed Codex CLI attachment,
not an adapter hook or a separately launched probe. No credential values or raw
environment/configuration were copied here.

## Identity and client

- Codex CLI: `codex-cli 0.163.0`
- Model from the live process arguments: `gpt-6-luna`
- Attachment: `8ac6654c-4024-457a-9f6c-9a61981d7645`
- Partyline line: `mcp-live-verification`
- Codex command was a fresh launch (`resume` absent).

## Native Partyline calls

Both tools were called through this process's native Partyline tool registry.
The following are bounded projections of the returned raw JSON text; fields
omitted from the projection are not needed to identify the result.

`mcp__partyline__whoami({})` returned:

```json
{"identity":"luna","attachment_id":"8ac6654c-4024-457a-9f6c-9a61981d7645","line":{"id":"cfd0f111-6cf5-4707-bdaf-0a84c1050ca8","name":"mcp-live-verification"},"role":"implementer"}
```

`mcp__partyline__guide({})` returned title `Partyline MCP tools` and a `tools`
array containing `whoami`, `guide`, `read_messages`, `notes`, `goal`,
`post_message`, `upload_file`, `get_media`, and `react`. The `captain` tool was
not present in this worker's guide output. The call succeeded and identified the
available native tool surface.

## Sanitized startup evidence

The live process was `codex --model gpt-6-luna --config model_reasoning_effort=<redacted> --dangerously-bypass-approvals-and-sandbox` plus three Partyline `-c`
overrides. Their key names were:

```text
mcp_servers.partyline.command
mcp_servers.partyline.args
mcp_servers.partyline.env
```

Parsed without printing values, the effective override shapes were:

```text
command: string, executable basename `python`
args: ["-P", "-m", "partyline.mcp"]
env keys: PARTYLINE_MCP_CONNECTION, PYTHONPATH
```

The private `CODEX_HOME/config.toml` top-level keys were `model`,
`model_reasoning_effort`, `projects`, and `tui`; it had no persisted
`mcp_servers` table. The MCP entry was supplied by the observed command-line
overrides. Adapter construction is at
[`adapter.py`](../../../partyline/adapters/bundled/codex/adapter.py#L90),
which now puts overrides after the resume session ID for resumed commands.
Override generation and
its exact per-key precedence are at
[`mcp_attach.py`](../../../partyline/mcp_attach.py#L119).

## Codex MCP log observation

In this attachment's local Codex log database, Codex CLI 0.163.0 logged one
auxiliary title-generation error at `codex_tui::app::thread_title:157`:

```text
failed to start title-generation thread: failed to load configuration:
invalid transport in `mcp_servers.partyline` (code -32600)
```

The same process's native Partyline `whoami` and `guide` calls succeeded. The
log line is concrete evidence of an auxiliary title-generation thread failing
to load the Partyline entry; by itself it does not establish why another
resumed Codex process might lack the Partyline catalog.

The error names the server table `mcp_servers.partyline`; the sanitized log
does not include the table contents. [Codex's MCP configuration reference](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) says a
stdio server needs `command` (with `args` and `env` optional), while an HTTP
server needs `url`. The error therefore establishes that this thread's config
parser saw no valid transport for that table, but it does not identify which
field was absent or altered: the log contains no field/value detail, so I
cannot say whether `command`, `url`, or another input was missing in the
thread's effective table. A maintainer explanation in the Codex CLI issue
[#13076](https://github.com/openai/codex/issues/13076)
describes this error when a partial MCP override is deserialized before a
later config layer supplies its transport. That is a plausible failure mode,
not a proven explanation for this thread: the live argv below supplied a
`command`, `args`, and `env`, and no raw intermediate config was available.

## Initial fresh-versus-resume source inspection (superseded by live probe)

Source inspection shows that a resumed invocation is assembled as
`codex resume <session-id> ...` first at
[`adapter.py:102-107`](../../../partyline/adapters/bundled/codex/adapter.py#L102),
then passed through `mcp_argv()` at lines 108-110. At the time of this initial
inspection, that function inserted all Partyline
`-c mcp_servers.partyline.{command,args,env}=...` overrides before `resume`;
the deployed-adapter resume experiment in `resume-after.md` later showed this
placement fails. The fix now inserts them after the resume session ID;
`codex_overrides()` is at
[`mcp_attach.py:119-158`](../../../partyline/mcp_attach.py#L119). The exact
placement is covered by
[`test_codex_overrides_follow_resume_session`](../../../tests/test_mcp_attach.py#L273).
Installed `codex resume --help` lists `-c/--config` as a resume option. The
diagnostic override experiment confirms that putting the generated overrides
after `resume <id>` restores the Partyline registry for the same attachment.

For this fresh attachment, the actual `-c` argv contained all three keys and
the private config file had no `mcp_servers` table. Its Codex `logs_2.sqlite`
had seven rows from `rmcp::service`, `rmcp::handler::server`, and
`rmcp::transport` targets; none of those selected MCP rows mentioned
`partyline`. The separate title-generation error above did mention it. The
live calls in the first section prove that this worker's native Partyline
registry exposes and can execute `whoami` and `guide`; they do not independently
prove that Codex spawned the generated local stdio server, which is why the
server startup log is kept separate here.

The same-attachment normal service detach/resume experiment is recorded in
`resume-after.md`: the deployed adapter's pre-resume overrides yielded no
Partyline tools, and the bounded log selection contained no Partyline row. The
attachment-only diagnostic override is recorded in
`resume-after-diagnostic-override.md`: placing the same overrides after
`resume <id>` yielded ten Partyline tool names and successful native calls.
That comparison identifies argument placement as the failure and confirms the
current adapter fix; the diagnostic override itself was not the deployed
adapter.

## Scope limit

The auxiliary title-generation `invalid transport` row above does not expose
which field was absent or malformed, so it is not used to explain the resumed
session failure. The same-attachment service experiment is the direct evidence
for the resume argument-order defect.
