# Partyline MCP evidence

Index of the evidence behind the MCP server on the `mcp-implementation` line. Start with
[`design.md`](design.md) for what is built and its limitations; the files below show where each
claim comes from.

Placeholders in the commands below:

- `<repo>`: the root of this checkout.
- `<scratch>`: a private per-run directory outside the worktree. Runtime homes, sockets, and logs go
  there, never under `docs/mcp/` (see `docs/lessons.md`, "Runtime homes belong only in per-run
  scratchpads").

## Evidence index

| File | What it is | What it proves |
| --- | --- | --- |
| [`api-inventory.md`](api-inventory.md) | Every HTTP route in the app (Set 1, 136 routes from an AST pass) and the agent-reachable subset (Set 2, 104 routes) with a disposition for each | Each reachable route maps to a named tool, a captain operation, a guide topic, or an exclusion with a reason. The names table lists the 10 core tools and 18 captain operations. Decisions 1 to 14 explain the non-obvious dispositions. |
| [`compat-matrix.md`](compat-matrix.md) | Per-client facts for Claude Code, Codex CLI, OpenCode V1 and V2: refresh behaviour, direct callability, dispatcher fallback, and config injection | Which clients re-list on `list_changed` and which need the dispatcher. Each runtime claim cites its retained log or is marked as a run report. |
| [`design.md`](design.md) | The design as committed at `HEAD` 5efa2cf: process model, per-client attach, tool surface, argument validation, refresh, reauthorization, bounds, credentials and lifecycle, and the limitations | What the committed server does, and what it does not yet do (section 10). Work that is not committed is not described. |
| [`fixture/stdio_server.py`](fixture/stdio_server.py) | The compatibility fixture: a stdio MCP server with `tool_a`, a `dispatch` tool, and a `tool_b` added after its first `tools/list` | Its behaviour is the test subject for every refresh claim. It emits `list_changed` about 2 s after the first listing, and it logs each incoming method and each tool call to `MCP_FIXTURE_LOG`. It does not log its own outgoing notification. |
| [`fixture/claude-service-managed.log`](fixture/claude-service-managed.log) | Retained log from a service-managed Claude Code 2.1.302 run with the fixture attached | Claude re-lists about 2 s after the first `tools/list`, then calls `tool_b` directly about 38 s later. The direct call shows `tool_b` was in the model's catalog. |
| [`fixture/codex-service-managed.log`](fixture/codex-service-managed.log) | Retained log from a service-managed Codex CLI 0.163.0 run with the fixture attached | Codex makes one `tools/list` and never re-lists. The `dispatch({"name": "tool_b"})` call succeeds, so the dispatcher is the working fallback. |
| [`fixture/opencode-v2-service-managed.log`](fixture/opencode-v2-service-managed.log) | Retained log from a service-managed OpenCode V2 2.0.32 run through the `glm-flash` preset | OpenCode V2 re-lists about 2 s after the first `tools/list`, then receives both a `dispatch` call and a direct `tool_b` call. The log shows the calls only; the run report gives the result text ("tool B result") for both. |
| [`fixture/opencode-v2-glm-flash-wrapper.txt`](fixture/opencode-v2-glm-flash-wrapper.txt) | A sanitized copy of the preset wrapper that merged the fixture into `OPENCODE_CONFIG_CONTENT` | The injection form used for that run. It names the server `fixture`; the adapter's own `mcp_env()` uses `partyline`. The wrapper runs the preset unchanged otherwise. |
| `isolate/` | Empty directory (git does not store empty directories, so it is not in the commit) | Nothing. A 516 MB Codex home appeared here during the work and was emptied before the audit. Its creator is unknown, and this directory must stay empty. See `design.md` section 10 and `docs/lessons.md`. |

## Whoami proofs (credentialed, service-managed)

These are kept apart from the fixture capability results above. Each file shows that a real client,
started with the Partyline MCP config that the branch generates for it, reached the branch's MCP server
and got its own attachment identity. They say nothing about refresh or direct calls; those are in the
fixture logs.

| File | Client and launcher | Identity returned |
| --- | --- | --- |
| [`fixture/partyline-whoami-claude.txt`](fixture/partyline-whoami-claude.txt) | Claude Code 2.1.302, via [`fixture/probe_claude.py`](fixture/probe_claude.py) (`PartylineAdapter.mcp_argv`) | `probe-claude` on `mcp-implementation`, role implementer |
| [`fixture/partyline-whoami-codex.txt`](fixture/partyline-whoami-codex.txt) | Codex CLI, via [`fixture/probe_codex.py`](fixture/probe_codex.py) (`codex_command`, which applies `mcp_argv`) | `probe-codex` on `mcp-implementation` |
| [`fixture/partyline-whoami-opencode-v2.txt`](fixture/partyline-whoami-opencode-v2.txt) | OpenCode V2 `glm-flash` preset, via [`fixture/probe_opencode_v2.py`](fixture/probe_opencode_v2.py) (`mcp_env`) | `probe-opencode` on `mcp-implementation`, role implementer, no children |

Each file states that no credential value was recorded. The shared connection lookup is
[`fixture/probe_common.py`](fixture/probe_common.py). It finds the connection file by comparing the
inherited `PARTYLINE_TOKEN` without printing it, and it writes the generated MCP config under the system
temp directory. The launchers need a live Partyline attachment and this host's paths, so they are not
portable (design.md section 10).

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
3. Run the tests, under the memory cap that `AGENTS.md` requires. The tests use their own temporary
   database; do not point them at a real one:

   ```bash
   ./scripts/capped-test uv run --locked python -m unittest \
     tests.test_mcp tests.test_mcp_attach tests.test_mcp_captain \
     tests.test_agent_connection tests.test_terminal_authorization
   ```

   The credential-lifecycle and validation tests named above are a separate run. Run against a clean
   `git archive` of 5efa2cf, this command gave `Ran 151 tests ... OK`, exit 0, under `capped-test` with
   `MemoryMax=2G`. The run on the shared worktree was not used as evidence, because that worktree had an
   uncommitted change to `tests/test_line_process_routes.py` while it ran.

   ```bash
   ./scripts/capped-test uv run --locked python -m unittest \
     tests.test_auth tests.test_mcp tests.test_mcp_attach tests.test_mcp_captain \
     tests.test_line_process_routes tests.test_attachment_lifecycle \
     tests.test_server.ShutdownTest.test_lifespan_starts_automatic_reattachment_without_a_browser \
     tests.test_server.ServerTest.test_resume_screen_keys_and_detach
   ```

   That run's log is in the per-run scratchpad and is not committed. Coverage, ruff, line caps, and the
   frontend gates were not run for this docs refresh.

   Where each claim is covered:

   - `tests/test_mcp.py`: the JSON-RPC protocol and bounds (`test_rpc_rejects_non_object_missing_method_and_pre_revoked_calls`), core argument validation (`test_core_schema_constraints_reject_calls_before_backend`, `test_required_types_and_array_bounds_are_validated`, `test_non_object_arguments_are_not_coerced_to_empty_object`), upload and download limits (`test_upload_*`, `test_download_*`), and revocation without disclosing the token (`test_revoked_credential_produces_short_error_without_disclosing_token`).
   - `tests/test_mcp_captain.py`: captain operations and their gates (`test_dispatcher_denies_non_lead_and_target_line_authorization`), demotion (`test_demoted_cached_named_tool_is_denied_without_side_effect`), revoked dispatch (`test_revoked_credential_while_connected_blocks_dispatch`), child retirement limits (`test_retire_child_is_limited_to_direct_child_and_one_line`), and write-set listing (`test_write_set_requests_*`).
   - `tests/test_mcp_attach.py`: per-client injection for Claude, Codex, and OpenCode (`test_claude_adapter_command_carries_the_config`, `test_codex_overrides_precede_resume_subcommand`, `test_user_inline_config_is_merged_not_replaced`). Codex values are TOML (`test_adds_entry_fields_as_toml_values` parses every override with `tomllib`, and `test_codex_toml_values_escape_awkward_environment_paths` checks an awkward path). `test_resume_regenerates_and_detach_removes` calls `provision_connection` and `remove_connection` directly; it does not run `detach_attachment`.
   - Credential lifecycle (`tests/test_auth.py`, `tests/test_line_process_routes.py`, `tests/test_server.py`, `tests/test_attachment_lifecycle.py`): stopped rows reject their token, rotation on resume and restart recovery, single detach and bulk close revoking a running helper. `design.md` section 7 gives each test name and what it asserts.
   - `tests/test_agent_connection.py`: connection-file publication, resume hints, and cleanup after a failed publish.
   - `tests/test_terminal_authorization.py`: the terminal socket fix in `bf8573a` (`test_revoked_token_stops_input`, `test_moved_target_stops_input_even_for_human`, `test_idle_demotion_revokes_descendant_read`).

   Adapter suites (`tests/test_claude_adapter.py`, `tests/test_codex_adapter.py`,
   `tests/test_opencode_v2_adapter.py`) cover adapter behaviour; the MCP-specific argv and environment
   checks are in `tests/test_mcp_attach.py`.
4. Run the gates from `AGENTS.md`: `uv run --locked ruff check .`, the capped coverage run (≥90%),
   `./check-code-lines`, and `cd frontend && npm run verify && npm run build`.
5. For a claim about a client, find its label in `design.md` or `compat-matrix.md`. A "retained run"
   claim should point at a log in `fixture/`. A "run report" claim has no log here and cannot be
   checked from this directory.
