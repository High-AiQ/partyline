# Live Codex Partyline MCP check — luna (2026-10-17)

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
[`adapter.py`](../../../../partyline/adapters/bundled/codex/adapter.py#L90),
which puts overrides before any `resume` subcommand. Override generation and
its exact per-key precedence are at
[`mcp_attach.py`](../../../../partyline/mcp_attach.py#L119).

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

## Fresh versus resume

Source inspection shows that a resumed invocation is assembled as
`codex resume <session-id> ...` first at
[`adapter.py:102-107`](../../../../partyline/adapters/bundled/codex/adapter.py#L102),
then passed through `mcp_argv()` at lines 108-110. That function inserts all
Partyline `-c mcp_servers.partyline.{command,args,env}=...` overrides after
the executable and before `resume`; `codex_overrides()` is at
[`mcp_attach.py:119-158`](../../../../partyline/mcp_attach.py#L119). The exact
placement is also asserted by
[`test_codex_overrides_precede_resume_subcommand`](../../../../tests/test_mcp_attach.py#L273).
Installed `codex resume --help` lists `-c/--config` as a resume option, and
[The official CLI reference](https://learn.chatgpt.com/docs/config-file/config-reference) describes it as a nested config override. So the
adapter's `-c` placement is accepted by the CLI shape and does not explain a
missing `partyline` entry by itself.

For this fresh attachment, the actual `-c` argv contained all three keys and
the private config file had no `mcp_servers` table. Its Codex `logs_2.sqlite`
had seven rows from `rmcp::service`, `rmcp::handler::server`, and
`rmcp::transport` targets; none of those selected MCP rows mentioned
`partyline`. The separate title-generation error above did mention it. The
live calls in the first section prove that this worker's native Partyline
registry exposes and can execute `whoami` and `guide`; they do not independently
prove that Codex spawned the generated local stdio server, which is why the
server startup log is kept separate here.

The delivery captain reported that its resumed sol process had the same three
generated override keys, while its sanitized startup log showed Codex's
`codex_apps` and `codex_worktrees` MCP services but no `partyline` mention.
That supports a gap between config argv and a successful Partyline MCP startup,
but does not establish that resume discarded the overrides. This worker could
not read the other attachments' private process environments or log databases
through its fence, and no `codex resume` was launched against this still-live
attachment's `CODEX_HOME` because doing so concurrently could alter its session
state. No fresh-versus-resume runtime reproduction is claimed.

Current evidence does not show Codex persisting and then preferring a session's
old MCP catalog over startup configuration. Nor does it rule that out. To
attribute the resumed failure, the missing evidence is a correlated read of
each resumed process's effective `mcp_servers.partyline` field shapes and its
own `logs_2.sqlite`/stderr around startup. Do not treat creation of the private
config or the presence of `-c` arguments as proof of a connection.

## Scope limit

The host showed two other Codex resume processes, with the same three override
key names. This attachment's process fence denied reads of their `/proc`
environment (`PermissionError`), so their private `CODEX_HOME` log databases
and config keys could not be correlated to those PIDs here. No exact
startup-failure attribution for the resumed sol/astra sessions is claimed from
this worker's evidence. The service-managed processes should be correlated by
their own sanitized logs before assigning the auxiliary `invalid transport`
message as their cause.
