# MCP client compatibility matrix

Checked 2026-10-17 against installed CLIs: Claude Code 2.1.302, Codex CLI
0.163.0, OpenCode 1.18.33, and OpenCode V2 2.0.32. Entries distinguish
documented support, pinned source review, and local fixture checks.

## At a glance (2026-10-17)

Runtime columns come from the retained service-managed logs under `fixture/` and
the run reports for those attachments. Source and documentation evidence is in the
sections below. The fixture logs incoming requests only, so the outgoing
`tools/list_changed` send is shown by the fixture code (`_notify_changed`), not by
the log. The logs contain no attachment IDs or CLI version strings; those labels
come from the run reports.

| Client | Version | Refreshes on `list_changed` (runtime) | New tool directly callable (runtime) | Dispatcher fallback worked (runtime) | Per-invocation config injection |
| --- | --- | --- | --- | --- | --- |
| Claude Code | 2.1.302 | Yes: second `tools/list` about 2 s after the first | Yes: model called `tool_b` directly | Not needed in the retained run | `--mcp-config <file>` (adapter `mcp_argv()`); `--strict-mcp-config` is documented but absent from the retained command |
| Codex CLI | 0.163.0 | No: one `tools/list`; `tool_b` never appeared | No | Yes: `dispatch({"name": "tool_b"})` returned `tool B result` | `-c mcp_servers.<id>.*=...` overrides (adapter `mcp_argv()`); private `CODEX_HOME` |
| OpenCode V2 | 2.0.32 via `glm-flash` | Yes: second `tools/list` about 2 s after the first | Yes: Code Mode `tools.fixture.tool_b()` returned `tool B result` (run report) | Yes: `dispatch({"name": "tool_b"})` returned `tool B result` | Wrapper sets `OPENCODE_CONFIG_CONTENT` and execs the preset unchanged; adapter `mcp_env()` merges the same way |
| OpenCode V1 (history) | 1.18.33 | No, in an isolated TUI with no model prompt | Not tested | Not tested | `OPENCODE_CONFIG=<file>`; not the V2 adapter path |

## Per-invocation stdio attach

| Client | Attach without changing global config | Per-server environment | Evidence |
| --- | --- | --- | --- |
| Claude Code | Write a small JSON file and launch `claude --strict-mcp-config --mcp-config <file>`. The strict flag restricts this invocation to that file's servers. | Each stdio entry has `env`; `claude mcp add` also accepts repeated `--env KEY=value`. | [Claude MCP docs](https://code.claude.com/docs/en/mcp) document `--mcp-config`, `--strict-mcp-config`, stdio command and `env`. Local `claude --help` reports these flags. Fixture connected from an isolated `CLAUDE_CONFIG_DIR`. |
| Codex CLI | Pass nested server values with repeatable `-c key=value` overrides. Set `CODEX_HOME` to an invocation-owned directory when isolation from user config/state is required. | `mcp_servers.<id>.env` forwards values to the stdio process; `env_vars` is a separate allowlist for remote execution. | [Codex CLI docs](https://developers.openai.com/codex/cli) and [configuration reference](https://developers.openai.com/codex/config-reference) document `-c`, `command`, `args`, `env`, `cwd`, and `env_vars`. **Runtime:** service-managed Codex 0.163.0 did not refresh the catalog; `dispatch(name=tool_b)` returned `tool B result`. A separate worker-local nested fence failed before MCP startup and is not evidence about the host launch. See amended observations below. |
| OpenCode V1 | Set `OPENCODE_CONFIG=/absolute/path/to/per-invocation.json` and launch OpenCode. | A local server's `environment` values are added to the inherited process environment; `{env:NAME}` substitution reads the launching OpenCode process's environment. | [V1 config docs](https://dev.opencode.ai/docs/config/) describe `OPENCODE_CONFIG`. **Empirical:** installed `opencode` 1.18.33 read the isolated config and connected to the fixture. This is not the V2 adapter Partyline launches. |
| OpenCode V2 | Merge the stdio entry into per-invocation `OPENCODE_CONFIG_CONTENT`; isolate state with private `OPENCODE_CONFIG_DIR`, XDG paths, and `OPENCODE_DB`. Do not assume V1's `OPENCODE_CONFIG` override applies to V2. | Local stdio config supports `environment`; process inherits environment. | [V2 MCP docs](https://dev.opencode.ai/v2/docs/mcp-servers/) and [V2 config docs](https://dev.opencode.ai/v2/docs/config/) document stdio config and config directory. **Runtime checked (isolated, no model call):** the installed V2 wrapper preserved an injected `OPENCODE_CONFIG_CONTENT` MCP entry while adding its configured model; a TUI launch connected to the fixture. A second launch read `opencode.json` from private `OPENCODE_CONFIG_DIR`. `debug paths db` returned the private `OPENCODE_DB` path and the TUI created that database. See the runtime record below. |

For Partyline, generate the small config at attach time, pass only that process's
short-lived connection credential to the server, and keep the config/state
directory private to that invocation. Do not write persistent server entries to
user or project configuration.
## Tool refresh, size, naming, and other MCP features

| Client | `tools/list_changed` during a session | Tool catalog / naming constraints found | Prompts, resources, notifications | Evidence |
| --- | --- | --- | --- | --- |
| Claude Code | **Yes in interactive mode**: the current docs say it refreshes changed tools, prompts, and resources. In `-p` and Agent SDK mode it refreshes tools only. On the v2 runtime, receipt of `list_changed` is via a held-open stream for servers that negotiate the newer protocol revision. | MCP tool names are exposed with `mcp__<server>__<tool>`. Claude omits full names over 128 characters from model requests. The docs describe tool search/deferral but publish no overall tool-count ceiling. | MCP prompts become slash commands; resources are referenceable by `@server:uri` and fetched on demand. The interactive client refreshes all three lists on notification. | [Claude MCP docs](https://code.claude.com/docs/en/mcp), sections “Dynamic tool updates”, “Notification streams on the v2 runtime”, “Tools with names longer than 128 characters”, “Use MCP resources”, and “Use MCP prompts as commands”. **Empirical:** local Claude 2.1.302 initiated the fixture, requested `tools/list`, received a `notifications/tools/list_changed`, then requested `tools/list` again. Service-managed run (retained `fixture/claude-service-managed.log`): second `tools/list` about 2 s after the first, then the model called `tool_b` directly. |
| Codex CLI 0.163.0 | **No catalog refresh.** The RMCP notification handler receives tool/resource/prompt change notifications but only logs them; the connection manager serves its cached catalog. | The configuration reference supports `enabled_tools` and `disabled_tools`, but no overall MCP tool-count cap or normalized naming rule was found. Keep names short and unique. | The handler proves notification receipt only; it does not establish usable prompts/resources UX. | **Source-read:** pinned [`logging_client_handler.rs`](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/rmcp-client/src/logging_client_handler.rs) and [`connection_manager.rs`](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/codex-mcp/src/connection_manager.rs) at commit [`129b8ec7ee6f4511557a4856279f529025c25af4`](https://github.com/openai/codex/commit/129b8ec7ee6f4511557a4856279f529025c25af4). The [0.163.0 release notes](https://github.com/openai/codex/releases/tag/rust-v0.163.0) do not mention MCP catalog refresh. **Runtime:** service-managed fixture log confirms one `tools/list` at startup and no re-list after `list_changed`; `tool_b` never appeared to the model, which used the stable `dispatch` tool. `dispatch(name=tool_b)` returned `tool B result`. |
| OpenCode V1 1.18.33 | **No refresh observed in this fixture.** Its TUI logged `initialize`, `notifications/initialized`, one `tools/list`, then did not re-list after `tools/list_changed`. | Tools use `<server>_<tool>` with other characters normalized to `_`. | V2 features below should not be inferred from this V1 result. | **Empirical:** isolated V1 TUI, no model prompt. |
| OpenCode V2 2.0.32 | **Yes, runtime observed:** after the fixture's `notifications/tools/list_changed`, the live TUI sent a second `tools/list`. Source also implements refresh: MCP manager `onToolsChanged` calls `refreshTools`, which invokes `connection.tools()` and updates the live tool set. Prompts refresh on their callback; resources publish a changed event. | Tools use `<server>_<tool>` with other characters normalized to `_`. V2 defaults to Code Mode, which groups server tools; `codemode: false` exposes individual tools. No overall tool-count ceiling is documented. | V2 docs describe MCP tools, prompts, resources, and instructions; prompts appear as `/server:prompt` commands. Code Mode packages tools; it is not the mechanism for `list_changed` refresh. The V2 CLI help lists no explicit refresh command; docs provide `/mcps` to view, connect, disconnect, or authenticate servers, not a dedicated refresh operation. | **Runtime:** installed wrapper `<home>/.local/share/partyline/opencode-v2-presets/glm-flash --auto` execs `<home>/.opencode/bin/opencode2` (`opencode v2.0.32`). Service-managed run with model calls (retained `fixture/opencode-v2-service-managed.log`): `initialize`, `notifications/initialized`, `tools/list`, a second `tools/list` about 2 s later, then `tools/call dispatch {"name": "tool_b"}` and `tools/call tool_b`. The run report says both calls returned `tool B result`, so direct use of a re-listed tool is proven for V2. Earlier isolated TUI run with no model prompt: the same re-list, inline config and private `OPENCODE_CONFIG_DIR/opencode.json` both connected, and `OPENCODE_DB` was honored. **Source-read:** pinned [`client.ts`](https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/mcp/client.ts) and [`index.ts`](https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/mcp/index.ts) at commit [`843a6c514e606b436a7fe713422ace0a93ad3d61`](https://github.com/anomalyco/opencode/commit/843a6c514e606b436a7fe713422ace0a93ad3d61). **Documented:** [V2 MCP docs](https://dev.opencode.ai/v2/docs/mcp-servers/). |

MCP server/tool naming should stay short, stable, and unique after each host's
normalization. Do not depend on a documented cross-client maximum count: none was
published in the client documentation reviewed. Claude's 128-character limit is
on the fully qualified tool name, not the count of tools.

## Recommended fallback for dynamic Partyline capabilities

Use a small, stable set of named tools for identity/context, reading and sending
messages, and capability discovery. Keep tool definitions stable for the life of
an attached invocation. A call must re-check the caller's live membership,
permissions, and current server-side capability state. When an operation is not
currently permitted, return a short structured error explaining the capability
needed and how to discover available operations; never rely on the client having
refreshed its catalog after promotion, demotion, attach, detach, or a line change.

If Partyline does send `tools/list_changed`, treat it as a helpful refresh hint,
not as the authorization boundary or the only path to newly available operations.
Keep volatile or lengthy endpoint instructions in an on-demand guide tool. This
works with clients that refresh immediately, clients that refresh some lists,
and clients that ignore or delay the notification, while avoiding a giant
captain-only catalog in every worker context.

## Fixture method and limits

The fixture at [`fixture/stdio_server.py`](fixture/stdio_server.py) advertises
`tools.listChanged`, returns `tool_a` and an always-available `dispatch`, then
sends `notifications/tools/list_changed`; a subsequent `tools/list` response
adds `tool_b`. Claude and the V2 TUI both re-listed; OpenCode V1 1.18.33 did not (V1 history, isolated TUI).
The V2 runtime check used the installed `glm-flash` wrapper with isolated
HOME/XDG paths, a private `OPENCODE_CONFIG_DIR`, and a private `OPENCODE_DB`; it
made no model request; the retained service-managed V2 run below made model calls. `OPENCODE_CONFIG_CONTENT` also worked through the
wrapper's merge. `OPENCODE_CONFIG_DIR` and `OPENCODE_DB` were observed working
in the isolated run. OpenCode's `mcp list` management subcommand uses its
managed background service; a separate invocation's inline config was not
visible there, so this observation applies to Partyline's actual
`--standalone` TUI launch path. The earlier isolated Codex check used an empty scratch `CODEX_HOME`, which reported `not logged in`; it did not exercise normal adapter auth seeding. My worker-local nested-fence attempt then failed before MCP initialization, but a service-managed Codex attachment completed the model-level fallback probe. The amended runtime observations below distinguish those results. My OpenCode temporary homes and databases were outside the repository and removed; the service-managed fixture logs are retained under `fixture/`.

## Partyline adapter launch and per-attachment injection

Partyline launches real CLI processes and can construct command arguments and
environment per attachment; no persistent user preset needs to change:

| Adapter | Current launch path | Attach-time MCP injection point |
| --- | --- | --- |
| Claude Code | `partyline/adapters/bundled/claude/adapter.py` builds the existing `att["command"]`; `spawn_env()` sets the seeded per-attachment `CLAUDE_CONFIG_DIR`. | `mcp_argv()` adds the private MCP config with `--mcp-config`, preserving any user config. Server credentials stay in the generated file's stdio `env` or inherited child environment. |
| Codex CLI | `partyline/adapters/bundled/codex/adapter.py` builds `att["command"]`; `spawn_env()` supplies the private `CODEX_HOME` and a private copy of `~/.codex/config.toml`. | `mcp_argv()` inserts per-server `-c 'mcp_servers.partyline....=...'` overrides before a `resume` subcommand. Per key, user values in the copied config or inline argv are preserved and Partyline fills only missing keys. `enabled = false` skips local injection; a user `url` keeps the remote entry and skips local injection. See `design.md` for the precise precedence and tests. |
| OpenCode V2 | `partyline/adapters/bundled/opencode/v2.py` starts `opencode2 --standalone --auto --prompt ...`; `spawn_env()` returns `OPENCODE_DB` plus `mcp_env()`. | `mcp_env()` merges `mcp.partyline` into the process's `OPENCODE_CONFIG_CONTENT` through `opencode_config_content()`. It preserves other JSON settings and does not set `OPENCODE_CONFIG_DIR`; the runtime probe below added private config/XDG paths to isolate this compatibility run. V2 docs do not establish V1 `OPENCODE_CONFIG` support. |

The per-invocation hooks are implemented. The Codex generated config is subject to
the user-config precedence described in `design.md`; probe summaries below do not
establish isolation or non-bypass approval behavior.

## Partyline `whoami` probe summaries (2026-10-17)

The three retained `.txt` files are prose summaries, not raw output or
version-bearing RPC logs. The probe scripts invoked `mcp_attach` and adapter
configuration hooks and called Partyline's `whoami` tool. They did not exercise
service-managed provisioning from a stale or shadowing working directory. The
summaries contain no credential values. The subprocess regression for generated
provisioning/helper entries is listed in `review-disposition.md`.

| Client | Probe identity | Attachment | Result record |
| --- | --- | --- | --- |
| Claude Code | `probe-claude` | `2d62320b-632c-48af-bd68-a4a238aa3134` | [`partyline-whoami-claude.txt`](fixture/partyline-whoami-claude.txt) |
| Codex CLI | `probe-codex` | `45a4267a-34ae-464a-877c-4630417df90a` | [`partyline-whoami-codex.txt`](fixture/partyline-whoami-codex.txt) |
| OpenCode V2 | `probe-opencode` | `f762a12d-8bdf-48c2-b917-dd6386275b7c` | [`partyline-whoami-opencode-v2.txt`](fixture/partyline-whoami-opencode-v2.txt) |

The sanitized launcher sources are `fixture/probe_common.py` and
`fixture/probe_{claude,codex,opencode_v2}.py`. The OpenCode adapter invokes its
executable as `debug paths db` before launch, so its launcher is attached by its
bare shebang executable path and forwards that diagnostic to the `glm-flash`
preset. Codex's wrapper removes the preset's duplicate bypass flag when it is
also present in host adapter arguments; generated fresh and resume arguments
were parsed by Codex `--help` without starting a session.

## Amended runtime observations (2026-10-17)

This section records model-call follow-up separately from source findings.
My OpenCode temporary home, database, and log were under
`<scratch>/mcp-compat-luna2/` and have been removed. The service-
managed Claude, Codex, and OpenCode V2 logs and the V2 wrapper are retained under `fixture/`; `docs/mcp/isolate/`
was empty throughout my probe.
The fixture now advertises `tool_a` and an always-available `dispatch` tool,
then adds `tool_b` after its first `tools/list` and sends
`notifications/tools/list_changed`. It logs tool names and arguments without
credentials.

### Claude Code 2.1.302

A service-managed Haiku 5.5 attachment loaded the fixture through its
per-invocation `--mcp-config` file, with this redacted command shape:

```text
claude --model claude-haiku-5-5 --effort high --dangerously-skip-permissions --mcp-config <scratch>/claude-mcp.json
```

The retained log [`fixture/claude-service-managed.log`](fixture/claude-service-managed.log)
shows `initialize`, `tools/list`, a second `tools/list` about 2 s later, then
`tools/call tool_b` about 38 s after the first listing. The model called `tool_b`
directly and received exactly `tool B result`; the dispatcher was not needed. The
direct call implies `mcp__fixture__tool_b` was in the model's catalog by then. The
log does not record the outgoing `list_changed`; its send is in the fixture's
`_notify_changed`. The retained command shape omits `--strict-mcp-config`; per the
adapter table, `mcp_argv()` adds only `--mcp-config`, so strict isolation is
documented but not exercised by this run.

### Codex CLI 0.163.0

The service-managed Codex attachment used the normal adapter fence and its
seeded login, with per-invocation MCP flags. The redacted command shape was:

```text
codex --model gpt-6-luna --config model_reasoning_effort="high" --dangerously-bypass-approvals-and-sandbox -c mcp_servers.fixture.command="python3" -c mcp_servers.fixture.args=["<worktree>/docs/mcp/fixture/stdio_server.py"] -c mcp_servers.fixture.env={MCP_FIXTURE_LOG="<scratch>/codex-fixture.log"}
```

The log shows one `tools/list`, about 33 s before the `dispatch` call, and no second listing. The model-facing tool names were
`mcp__fixture__dispatch` and `mcp__fixture__tool_a`; `mcp__fixture__tool_b` never
appeared. Calling `dispatch` with `{ "name": "tool_b" }` succeeded and
returned exactly `tool B result`. The sanitized service-managed fixture log is
at [`fixture/codex-service-managed.log`](fixture/codex-service-managed.log).
This confirms the stable dispatcher fallback for Codex when its cached catalog
does not refresh. The source and runtime observations agree.

A separate worker-local attempt called `PartylineAdapter.start()` from inside
an already fenced process. This constructed a second outer fence and is not
evidence about the host service-managed launch. It used an adapter-seeded home
whose `codex login status` reported `Logged in using ChatGPT`, then exited before
fixture initialization with:

```text
bwrap: No permissions to create a new namespace, likely because the kernel does not allow non-privileged user namespaces
```

The exact earlier scratch launch command was not present in the empty
`docs/mcp/isolate/` directory. No runtime home or log was staged or committed
from that local probe.

### OpenCode V2 2.0.32 via `glm-flash`

The retained service-managed run used the installed wrapper
`<home>/.local/share/partyline/opencode-v2-presets/glm-flash` (`--auto`,
resolving to `<home>/.opencode/bin/opencode2`). A copy of the wrapper that
adds the fixture is kept as
[`fixture/opencode-v2-glm-flash-wrapper.txt`](fixture/opencode-v2-glm-flash-wrapper.txt).
It sets `OPENCODE_CONFIG_CONTENT` to a merged config with a stdio server named
`fixture`, then execs the preset unchanged. The adapter's `mcp_env()` uses the name
`partyline` for the same merge; the retained run used `fixture`. The injected entry
(paths sanitized) was:

```json
{"mcp":{"fixture":{"type":"local","command":["python3","<repo>/docs/mcp/fixture/stdio_server.py"],"environment":{"MCP_FIXTURE_LOG":"<scratch>/opencode-fixture.log"}}}}
```

The retained log [`fixture/opencode-v2-service-managed.log`](fixture/opencode-v2-service-managed.log)
shows `initialize`, `notifications/initialized`, `tools/list`, a second `tools/list`
about 2 s later, then `tools/call dispatch {"name": "tool_b"}` about 90 s after the
first listing, followed immediately by `tools/call tool_b`. The run report says both
calls returned exactly `tool B result`: the model's Code Mode call
`tools.fixture.tool_b()` and the `dispatch` call. Code Mode surfaced `tool_b` to the
model as a catalog-update block. The log does not record the Code Mode form itself;
that comes from the run report. So for V2 the re-listed tool is directly callable,
and the dispatcher fallback also works. The earlier isolated run with no model
prompt, which used the `partyline` server name and scratch paths since removed,
showed the same re-list pattern and is superseded for model-facing evidence.
