# Partyline MCP evidence

Captain tools include `retirement_preview` and an extended `retire_child`. Preview returns
bounded evidence and a token bound to the caller; forced retirement requires explicit
`force_discard` and that `preview_token`. Only a tree's root captain can override descendant
dirty/unmerged guards. `include_children`, `stop_processes` and `clear_goal` are explicit;
preview's `required_flags` names every one the plan needs, so a refusal never arrives one
flag per call and changes nothing. The result records recovery refs and an audit ID. See the
[retirement contract](../hierarchy.md#root-decisions-about-obsolete-descendants).

Service-managed native tool calls and the Codex resume comparison for the
2026-10-17 live verification are indexed in [`live/README.md`](live/README.md).

Index of the evidence behind the MCP server on the `mcp-implementation` line. Start with
[`design.md`](design.md) for what is built and its limitations; the files below show where each
claim comes from.

Placeholders in the commands below:

- `<repo>`: the root of this checkout.
- `<scratch>`: a private per-run directory outside the worktree. Runtime homes, sockets, and logs go
  there, never under `docs/mcp/` (see `docs/lessons.md`, "Runtime homes belong only in per-run
  scratchpads").

## Upload tools

`upload_files` accepts `paths` (1–6 readable regular local files, in display order),
a required per-message `client_key` (1–64 characters), optional `conv_id` (own line
by default), and optional `title` (200), `description` (2000), and `body` (3000).
Metadata applies to the single message and its attachments. Own-line captions
are refused, as with `upload_file`: your terminal reply is the chat message,
so the error says to omit `body` or pass another `conv_id`; authorization is
unchanged.

The client validates paths and stat sizes before connecting, then streams one
multipart request using repeated `file` fields. Each file is limited to 20 MiB;
the total is limited to 60 MiB because the route prepares the originals together.
It detects size changes while streaming and preserves all original bytes.
Retries with the same caller, destination, and key replay the original message
and complete ordered file list. Images are detected by content and receive
thumb/slim/readable/original variants; gallery thumbnails open the full-size
viewer with download. Other files are generic downloadable attachments.
`upload_file` remains compatible for single-file uploads.

## Evidence index

| File | What it is | What it proves |
| --- | --- | --- |
| [`api-inventory.md`](api-inventory.md) | Every HTTP route in the app (Set 1, 136 routes from an AST pass) and the agent-reachable subset (Set 2, 104 routes) with a disposition for each | Each reachable route maps to a named tool, a captain operation, a guide topic, or an exclusion with a reason. Source references use handler names so line shifts do not stale the inventory. The names table lists the core tools and captain operations. |
| [`compat-matrix.md`](compat-matrix.md) | Per-client facts for Claude Code, Codex CLI, OpenCode V1 and V2: refresh behaviour, direct callability, dispatcher fallback, and config injection | Which clients re-list on `list_changed` and which need the dispatcher. Each runtime claim cites its retained log or is marked as a run report. |
| [`design.md`](design.md) | Current design and source behaviour, plus client observations tied to their retained evidence | What the server does and its documented limits. Runtime claims remain pinned to the recorded client versions and logs. |
| [`review-disposition.md`](review-disposition.md) | Finding-by-finding disposition of the shipping review | The exact fix/test or bounded limitation for each review finding. |
| [`fixture/stdio_server.py`](fixture/stdio_server.py) | The compatibility fixture: a stdio MCP server with `tool_a`, a `dispatch` tool, and a `tool_b` added after its first `tools/list` | Its behaviour is the test subject for every refresh claim. It emits `list_changed` about 2 s after the first listing, and it logs each incoming method and each tool call to `MCP_FIXTURE_LOG`. It does not log its own outgoing notification. |
| [`fixture/claude-service-managed.log`](fixture/claude-service-managed.log) | Retained log from a service-managed Claude Code 2.1.302 run with the fixture attached | Claude re-lists about 2 s after the first `tools/list`, then calls `tool_b` directly about 38 s later. The direct call shows `tool_b` was in the model's catalog. |
| [`fixture/codex-service-managed.log`](fixture/codex-service-managed.log) | Retained log from a service-managed Codex CLI 0.163.0 run with the fixture attached | Codex makes one `tools/list` and never re-lists. The `dispatch({"name": "tool_b"})` call succeeds, so the dispatcher is the working fallback. |
| [`fixture/opencode-v2-service-managed.log`](fixture/opencode-v2-service-managed.log) | Retained log from a service-managed OpenCode V2 2.0.32 run through the `glm-flash` preset | OpenCode V2 re-lists about 2 s after the first `tools/list`, then receives both a `dispatch` call and a direct `tool_b` call. The log shows the calls only; the run report gives the result text ("tool B result") for both. |
| [`fixture/opencode-v2-glm-flash-wrapper.txt`](fixture/opencode-v2-glm-flash-wrapper.txt) | A sanitized copy of the preset wrapper that merged the fixture into `OPENCODE_CONFIG_CONTENT` | The injection form used for that run. It names the server `fixture`; the adapter's own `mcp_env()` uses `partyline`. The wrapper runs the preset unchanged otherwise. |
| `isolate/` | Empty directory (git does not store empty directories, so it is not in the commit) | Nothing. A 516 MB Codex home appeared here during the work and was emptied before the audit. Its creator is unknown, and this directory must stay empty. See `design.md` section 10 and `docs/lessons.md`. |

The fixture refresh logs contain protocol methods and tool-call records only; they do
not carry attachment IDs or CLI version strings. Those labels come from the associated
run reports, not from the retained log bytes.

## Whoami probe summaries (hook-level)

These are kept apart from the fixture capability results above. The retained `.txt` files are
human-written prose summaries of probe outcomes, not raw client output or version-bearing RPC
transcripts. The probes called `whoami` through adapter configuration hooks; they did not exercise
service provisioning. They say nothing about refresh or direct calls; those observations are from the
fixture logs.

| File | Client and launcher | Summary reports |
| --- | --- | --- |
| [`fixture/partyline-whoami-claude.txt`](fixture/partyline-whoami-claude.txt) | Claude Code 2.1.302, via [`fixture/probe_claude.py`](fixture/probe_claude.py) (`PartylineAdapter.mcp_argv`) | `probe-claude` on `mcp-implementation`, role implementer |
| [`fixture/partyline-whoami-codex.txt`](fixture/partyline-whoami-codex.txt) | Codex CLI, via [`fixture/probe_codex.py`](fixture/probe_codex.py) (`codex_command`, which applies `mcp_argv`) | `probe-codex` on `mcp-implementation` |
| [`fixture/partyline-whoami-opencode-v2.txt`](fixture/partyline-whoami-opencode-v2.txt) | OpenCode V2 `glm-flash` preset, via [`fixture/probe_opencode_v2.py`](fixture/probe_opencode_v2.py) (`mcp_env`) | `probe-opencode` on `mcp-implementation`, role implementer, no children |

Each summary states that no credential value was recorded. The shared connection lookup is
[`fixture/probe_common.py`](fixture/probe_common.py). It finds the connection file by comparing the
inherited `PARTYLINE_TOKEN` without printing it. With `PARTYLINE_PROBE_SCRATCH` set, the generated
MCP config goes under `<scratch>/partyline-mcp-probe.agent-connections/`; without it, the config is
written beside the attachment connection file. The launchers need a live Partyline attachment, a
checkout, and (for OpenCode V2) a locally configured preset, so they are host-run hook-level probes
rather than provisioning tests or portable fixtures (design.md section 10). The generated-entry
subprocess regression is tracked in `review-disposition.md`. Reproduction paths use placeholders such
as `<repo>` and `<scratch>`; do not replace them with a user's home path.

## Reproduce the fixture runs

### 1. Protocol check, no CLI and no credentials

This drives the fixture directly over stdin. It needs only Python.

```bash
mkdir -p <scratch>/fixture-check
(printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
 sleep 3
 printf '%s\n' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"dispatch","arguments":{"name":"tool_b"}}}'
 sleep 1) | MCP_FIXTURE_LOG=<scratch>/fixture-check/fixture.log python3 <repo>/docs/mcp/fixture/stdio_server.py
```

Expected: stdout contains a `notifications/tools/list_changed` line after the first listing, the second
`tools/list` includes `tool_b`, and the call returns `tool B result`. The log in
`<scratch>/fixture-check/fixture.log` lists `initialize`, two `tools/list` lines, and
`call dispatch {"name": "tool_b"}`.

### 2. Claude Code 2.1.302

Run it with your normal authenticated Claude Code home, in place; do not copy that home. Keep the MCP
config and the fixture log in `<scratch>`. These manual commands approximate the retained
service-managed run; they are not replays of it.

```bash
mkdir -p <scratch>/claude-run && cd <scratch>/claude-run
cat > "<scratch>/claude-mcp.json" <<'JSON'
{"mcpServers":{"fixture":{"command":"python3","args":["<repo>/docs/mcp/fixture/stdio_server.py"],"env":{"MCP_FIXTURE_LOG":"<scratch>/claude-fixture.log"}}}}
JSON
claude --model claude-haiku-5-5 --mcp-config <scratch>/claude-mcp.json
```

Wait about 5 s after startup, then ask the model to call `tool_b`. Check `<scratch>/claude-fixture.log`
for a second `tools/list` about 2 s after the first, and a `call tool_b` line.

### 3. Codex CLI 0.163.0

Run it with your normal authenticated Codex home, in place; do not copy that home. This command
approximates the retained service-managed run.

```bash
codex --model <model> \
  -c 'mcp_servers.fixture.command="python3"' \
  -c 'mcp_servers.fixture.args=["<repo>/docs/mcp/fixture/stdio_server.py"]' \
  -c 'mcp_servers.fixture.env={MCP_FIXTURE_LOG="<scratch>/codex-fixture.log"}'
```

Ask the model to call `dispatch` with `{"name": "tool_b"}` after startup. Expect exactly one `tools/list`
in the log and a `call dispatch` line. A direct `tool_b` call is not available on Codex.

### 4. OpenCode V2 2.0.32

The retained run used the `glm-flash` preset wrapper. The command below has not been run as a retained
run. It uses the same `OPENCODE_CONFIG_CONTENT` shape as the wrapper, with the server named `fixture`,
and it still needs your own authenticated OpenCode.

```bash
OPENCODE_DB=<scratch>/opencode-v2.db \
OPENCODE_CONFIG_CONTENT='{"mcp":{"fixture":{"type":"local","command":["python3","<repo>/docs/mcp/fixture/stdio_server.py"],"environment":{"MCP_FIXTURE_LOG":"<scratch>/opencode-fixture.log"}}}}' \
opencode2 --standalone --auto --prompt "<prompt that asks for tool_b after startup>"
```

Expect a second `tools/list` about 2 s after the first, then `call dispatch` and `call tool_b` lines.

Before committing any new log: redact paths, drop any token-shaped strings, and keep only the
JSON-RPC method names and tool-call lines the fixture writes. Do not commit a runtime home or a
config that holds a credential.

## How to review

1. Read [`design.md`](design.md) section 10 first. Each limitation there names the evidence or the gap.
2. Check the code against the claims. Every design section names its module.
3. Run the relevant tests under the memory cap that `AGENTS.md` requires. The tests use their own
   temporary database; do not point them at a real one:

   ```bash
   ./scripts/capped-test uv run --locked python -m unittest \
     tests.test_mcp tests.test_mcp_attach tests.test_mcp_captain \
     tests.test_agent_connection tests.test_terminal_authorization
   ```

   The regression test names for the shipping review findings are listed in
   [`review-disposition.md`](review-disposition.md). Historical runs from earlier MCP commits are not
   evidence for a replacement tip.
4. Run all gates from `AGENTS.md` on the final unchanged SHA: Ruff, one `./scripts/capped-test` run
   with coverage ≥90%, `./check-code-lines`, then the frontend verify and build sequentially. Record
   the exact SHA and gate results in the handoff; do not point tests at a real database.
5. For a client behavior claim, use `compat-matrix.md` and distinguish retained fixture logs from the
   associated run report. The logs record protocol methods and calls, not attachment IDs or CLI versions.
