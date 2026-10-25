# Partyline MCP design

This document describes the MCP implementation and its known limits. Current source claims refer to
the checked-out code; client behaviour is labelled by its evidence: **retained run** (a sanitized log
under `fixture/`), **source** (read from pinned upstream code), or **code** (read from this
repository). Historical gate runs are recorded only at the exact commit where they ran. Evidence
files and reproduction notes are indexed in [`README.md`](README.md).
Route-level dispositions are in [`api-inventory.md`](api-inventory.md); per-client facts are in
[`compat-matrix.md`](compat-matrix.md).

## 1. Shape and process model

- Partyline runs each attached CLI (Claude Code, Codex CLI, OpenCode V2) as a PTY process. For each
  attachment the adapter adds one stdio MCP server to that invocation. The server is
  `python -m partyline.mcp`, run with the Partyline checkout on `PYTHONPATH`, and it receives
  `PARTYLINE_MCP_CONNECTION` naming the attachment's connection file. The CLI starts the server as its
  own child, so the server lives and ends with that CLI invocation.
- The server speaks newline-delimited JSON-RPC 2.0 on stdin and stdout, written by hand; the project
  has no MCP SDK dependency. It answers `initialize` (advertising `tools.listChanged`), `ping`,
  `tools/list`, and `tools/call`. It accepts `notifications/initialized` and ignores other
  notifications. It ends when stdin closes, or on the first input line longer than 1,000,000 bytes.
- One thread runs: the request loop. There are no timers or background threads, so an idle server
  makes no requests. Every module in `partyline/mcp/` and `partyline/mcp_attach.py` is at or
  under 300 lines.
- The server calls the existing HTTP API through `PartylineClient` (`partyline/mcp/client.py`) with
  the attachment's own machine credential. It never uses a human JWT.

## 2. Attach per client

Partyline adds the MCP server for one invocation only. It does not write the global Codex
configuration. The generated Partyline MCP config lives in the per-attachment connection directory,
`<db>.agent-connections/` (mode 0700; `partyline/agent_connection.py`). Codex's effective
`config.toml` is a private copy under that attachment's `CODEX_HOME`.

| Client | How the entry is injected | User configuration | Code |
| --- | --- | --- | --- |
| Claude Code 2.1.302 | `--mcp-config <att>.mcp.json` added to the command, after any user `--mcp-config` values | Non-strict: the user's own MCP servers still load | `mcp_attach.claude_command` |
| Codex CLI 0.163.0 | The user's `~/.codex/config.toml` is copied into each attachment's `CODEX_HOME`; it is never symlinked. A private regular copy is kept on later starts; an old symlink is replaced when the attachment resumes. Partyline adds `-c mcp_servers.partyline.{command,args,env}=<TOML>` only for keys the user did not set in the copied config or inline argv. | A configured `enabled = false` or `url` suppresses the generated stdio entry. User-provided partial `command`, `args`, or `env` values are retained; only missing keys are generated. Inline settings are preserved. A user's own command/URL can therefore replace the Partyline server behavior. | `mcp_attach.codex_overrides`, `adapters/bundled/codex/adapter.py` `mcp_argv`, `adapters/session_seed.py` `seed_private_file` |
| OpenCode V2 2.0.32 | `OPENCODE_CONFIG_CONTENT` with `mcp.partyline` merged in; every other key passes through | If the existing content is unparseable or not a JSON object, nothing is added and no error is raised | `mcp_attach.opencode_config_content`, `adapters/bundled/opencode/v2.py` `mcp_env` |
| OpenCode V1 and any adapter without an override | None. The `McpHooks` defaults return the command and environment unchanged | — | `adapters/mcp_hooks.py` |

The Claude config file is written mode 0600 and holds `mcpServers.partyline` with the server's
command, `-P -m partyline.mcp`, and an `env` carrying the connection file path and `PYTHONPATH`. It
never holds the token. The connection file is a separate private file (section 7).

## 3. Tool surface

The server lists tools for the caller's live state only. Names are short and unique per attachment.

**Core tools** (`partyline/mcp/tools_core.py`). A tool appears only when the live actions allow it.

| Tool | Requires | Routes | Notes |
| --- | --- | --- | --- |
| `whoami` | always | own line detail and children; capability state is refreshed by MCP before tool dispatch | identity, role, actions, members, parent, children |
| `guide` | always | `/api/docs` by category and topic for leads; local tool schemas for other roles | on-demand docs for leads; workers get their current permission-filtered core tools without a docs request; with `topic: captain` and no category, returns the caller's captain operations (empty unless a live lead) |
| `read_messages` | `read` | messages, messages around an id | limit clamped to 1 to 50 |
| `post_message` | listed for `write` or `assign` | message post | refuses the caller's own line; `client_key` required; no action check in MCP, the message route decides |
| `react` | listed for `write` | reactions, by message id | POST toggles the reaction; `remove: true` uses DELETE; the route decides line authorization |
| `upload_file` | `upload` on the target line (own line or task root for workers) | files | one regular file of at most 20 MiB; `client_key` required |
| `upload_3d_model` | `upload` on the target line (own line or task root for workers) | files | one self-contained `.glb` or `.gltf` model of at most 64 MiB; case-insensitive extension preflight, optional title, required `client_key`; inline click-to-load 3D card |
| `upload_files` | `upload` on the target line (own line or task root for workers) | files | 1–6 regular files, 20 MiB each and 60 MiB total; one message and retry key |
| `get_media` | `read` | media download | writes a new local file, mode 0600 |
| `notes` | `read`; set needs `assign` for line or tree | notes | attachment notes are own line only; 4,000 characters |
| `goal` | `read`; set needs `assign` | line detail; goal set | 3,000 characters |
| `reports` | listed for `read_reports`, `report`, or `notify`; non-leads use the core tool and live leads use the fixed captain dispatcher; list (`limit`, `before_id`) and get (`report_id`) need `read_reports`; post needs `report` (or `notify` when `notify` is set) | reports | body required, at most 2,000 characters; both schemas and handlers enforce the route limit |

**Argument validation (core tools).** `MCPServer._call` checks a core tool's arguments against the
`inputSchema` the server advertises, using `partyline/mcp/validation.py`, before the handler or any
API call runs. An invalid call returns an error result and never reaches the backend (test
`test_core_schema_constraints_reject_calls_before_backend`). The checker covers `type`, `enum`,
`minLength`/`maxLength`, `minimum`/`maximum`, `minItems`/`maxItems`, `items`, nested `properties` with
`required` and `additionalProperties: false`. Core schemas set `additionalProperties: false`, so an
unknown field is refused rather than ignored. It does not check `pattern`, `format`, `anyOf`, `oneOf`,
or the `null` type, and it silently skips keywords it does not know (section 10). The `arguments`
member must be an object: an omitted member means `{}`, and `null` is refused with JSON-RPC `-32602`
(test `test_non_object_arguments_are_not_coerced_to_empty_object`). Type, length, and range errors on
core tools are tested by `test_required_types_and_array_bounds_are_validated`. Captain operations use a
separate check, `captain_schemas.validate`, described below.
Both `validation.py` and `captain_schemas.validate` are hand-written subsets of JSON Schema.
`validation.py` is not applied to captain operations.

**Captain tier** (`tools_captain.py`, `captain_ops.py`, `captain_schemas.py`).

- `captain(op, args)` is listed to every attachment. It accepts exactly `op` and `args`, and it
  refuses any caller who is not a live lead. The `args` object is checked by `captain_schemas.validate`
  before dispatch: unknown and missing fields, string type and length, boolean, integer range, array
  type, and array item length and count. Enum checks run there too, and `validation.py` is not used.
- Each operation the caller may use is also a named tool with the same name. Named tools appear only
  for a live lead.
- The operations are a fixed allowlist: `staffing`, `list_presets`, `attach_worker`, `detach_worker`,
  `create_child`, `appoint_lead`, `retire_child`, `accept`, `review_worktree`, `request_write_set`,
  `decide_write_set`, `request_restart`, `process_overview`, `ack_report`, `set_goal`, `set_gates`,
  `docs_read`, `write_set_requests`, and `reports`. Each has a fixed argument schema with length, enum, and range
  checks. No caller supplies a route or method.
- `list_presets` is read-only. Presets are never mutated through MCP.
- `retire_child` is limited to a direct child that the caller's home line may archive. Purge stays
  excluded.

**Excluded from MCP.** Every route's disposition is in `api-inventory.md`; the reasons that matter most
are in its Decisions section (1 to 14):

- Loopback process lifecycle (rows 4, 111, 120): excluded, since an on-host lead would otherwise
  start and stop processes outside captain scope.
- Child purge (rows 20, 26, 28): excluded. Retirement is limited to `retire_child`.
- Bridges (rows 12 to 15) and decline (rows 102, 132): person-only.
- Presets create, update, and delete (rows 83 to 86): person-only. `list_presets` is read-only.
- Terminal socket, screen, and keys (rows 122, 123, 128): excluded. The terminal stream is raw PTY
  output, not speech, and the socket's own authorization was fixed in `bf8573a`.
- Memory (rows 67 to 72): excluded in this slice; adjustment requests go through the root captain.
- Root heartbeat (rows 37 to 41): the root manager's surface, not captain or worker scope.
- Worker write-set requests (row 136): a worker keeps the direct POST that the fence message names.
- Chat socket (row 124): machines have no push feed in this slice. Agents poll `read_messages`.

## 4. Live capability listing and refresh

- `tools/list` is recomputed from `/api/capabilities` on every call. Each listing records a signature
  (kind, role, conversation, attachment, lead flag, sorted actions).
- Every `tools/call` already fetches capabilities. If the signature differs from the recorded one, the
  server records the new signature and sends `notifications/tools/list_changed` once, then carries on
  with the call. It sends nothing before a listing has recorded a signature. A rejected credential
  (HTTP 401) refuses every later request with a `notifications/message` error ("Partyline attachment credential
  is no longer valid").
- **Correctness never depends on refresh.** `captain` and `guide` are in the first listing for every
  attachment. A worker promoted mid-session on a client that never re-lists can still act through
  `captain(op, args)`, and it gets a structured denial when it is not permitted.
- Named tools are a convenience on clients that re-list. Measured clients behave as recorded in
  section 10: Claude Code and OpenCode V2 re-list (retained runs against the fixture), and Codex
  does not.

## 5. Reauthorization on every call

- Each `tools/call` reads live capabilities first. A name that is not in the current listing is
  refused with "tool is not currently available to this attachment". A demoted worker's cached named
  tool therefore does nothing, and the refusal has no side effects (test
  `test_demoted_cached_named_tool_is_denied_without_side_effect`).
- Any other line is checked with `capabilities(conv_id)` for the required action, in the core
  helpers and in captain operations. The one exception is `post_message` to another line: MCP refreshes
  that target's state and the message route makes the final decision.
- The route is the authority. The capability listing reads the same `allows()` function the routes
  use, so MCP decides what is offered and the server decides what succeeds.
- A captain operation also re-checks that the caller is a live lead, at dispatch and at each target.

## 6. Bounds

| Bound | Value | Code |
| --- | --- | --- |
| JSON-RPC input line | 1,000,000 bytes; a longer line ends the session | `server.MAX_LINE` |
| API response | 2 MiB, checked by `Content-Length` and while streaming | `client.MAX_RESPONSE` |
| Tool result text | 20,000 characters, then cut with a marker | `render.MAX_TEXT` |
| `upload_file` | one regular file of at most 20 MiB, streamed; size and identity re-checked during the stream | `client.MAX_UPLOAD` |
| `upload_3d_model` | one self-contained glTF/GLB model of at most 64 MiB; `.glb`/`.gltf` suffix checked case-insensitively before the same streamed upload as `upload_file` | `tools_media.py`, `client.MAX_MODEL_UPLOAD` |
| `upload_files` | 1–6 regular files, streamed in one request; 20 MiB each, 60 MiB aggregate to bound server preparation memory; paths/stat sizes checked before connection | `uploads.py`, `client.MAX_UPLOAD` |
| `get_media` | at most 20 MiB, streamed; a partial oversize file is removed | `client.MAX_DOWNLOAD` |
| Text fields | notes 4,000; goal 3,000; report body 2,000; upload title 200, description 2,000, caption 3,000; captain free text per schema. The core limits are checked by `validation.py` before the handler; captain limits by `captain_schemas.validate` | `tools_core.py`, `validation.py`, `client.py`, `captain_schemas.py`, and the report route's `ReportIn` |
| `set_gates` | up to 20 commands; timeout 1 to 14,400 s | `captain_schemas.py` |
| `client_key` | 1 to 64 characters, required on `post_message`, `upload_file`, `upload_3d_model`, and `upload_files` | `tools_core.py`, `client.py` |

**Follow-up limit gap.** The MCP upload helpers cap regular files at 20 MiB and dedicated
models at 64 MiB while the server accepts up to 100 MiB. Its 64 KiB chunks still travel in one HTTP request, so they do not bypass reverse-proxy
request-size caps. Limit alignment or resumable uploads are separate work.

**Idempotency.** `post_message`, `upload_file`, `upload_3d_model`, and `upload_files` require a caller key. The server remembers each key
per sender, conversation, and `client_key` for a 600 s window (`idempotent_posts.py`), and a retry
with the same key returns the original result instead of posting again when the remembered key is
present. Insertion and key recording use separate commits, so a process crash between them can leave
a durable post without its retry record. The in-process claim locks also assume one service runtime
per database; they do not coordinate competing server processes. Keys with the `d:` prefix are
stamped by the CLI helper (`agent_client.py`), not by MCP, and have a 120 s window.

**Truncation.** A result cut at the character cap is not valid JSON and has no cursor. The marker
tells the caller to narrow the query or ask for a specific page. Callers should page with `after_id`
or `before_id` rather than rely on a cut result.

## 7. Credentials and lifecycle

Two private files per attachment live in `<db>.agent-connections/`. Both are written through a temp
file and an atomic rename.

- `<att>.json`: the connection file. It holds the API base, the attachment's machine token, the
  line, the attachment ID, and the handle. The directory is mode 0700 and the file is 0600.
- `<att>.mcp.json`: the MCP config. It holds the server command and the path to the connection file,
  never the token. It is mode 0600.

Each process activation has its own machine token, and the `attachments.api_token` column holds only
the current one:

- **Mint** (`auth_store.ensure_api_token`, from `attachment_start.py`): a token is created only when the
  row has none, so the first activation of a new attachment mints it.
- **Rotate** (`auth_store.rotate_api_token`, from `attachment_resume.py`): every resume rotates the
  token before `provision_connection` runs, then regenerates both files. Restart recovery uses the same
  resume path (`server.py` `ReattachCoordinator(runtime, _resume_adapter)`). The previous token stops
  resolving at the rotation, before the new process starts.
- **Resolve** (`auth_store.attachment_by_api_token`): a token resolves to a principal only while its
  row's status is `starting` or `running`. For a row that is `exited`, `detached`, or deleted, the lookup
  returns nothing. `auth_guard.resolve_principal` then tries the token as a JWT, which fails, so the
  request gets HTTP 401. The same rule applies to HTTP and to the WebSocket guard, which uses the same
  `resolve_principal` path.

| Event | Connection file | MCP config | Token |
| --- | --- | --- | --- |
| Create (start) | written | written | minted, if the row had none |
| Resume, including restart recovery | rewritten (new inode) | rewritten (new inode) | rotated before launch; the old token stops resolving |
| Detach through `detach_attachment` (close, archive, memory or write-set approval, lifecycle) | kept on disk, still holds the now-dead token until the next resume or removal | removed (`remove_config` in `line_process_routes.py`) | row status becomes `detached` in the same transaction, so the token stops resolving |
| Removal of a stopped record (`attachment_lifecycle_routes.py`: `remove_stopped_record`, then `_removed_event`) | removed (`remove_connection`) | removed | the row is deleted, so the token stops resolving |
| Fresh replacement (`replace`) | new identity and token; the old token stops resolving | new | new |

Captain authority is checked on top of the bearer lookup. `machine_scope._live_lead` returns no lead
unless the lead row is `starting` or `running` (`machine_scope.py:83`), so a detached lead loses captain
operations even if its token were still presented.

Tests that cover this lifecycle:

- Stopped row rejects its token: `test_machine_token_is_rejected_after_attachment_stops`
  (`tests/test_auth.py`).
- Rotation makes the previous token invalid: `test_rotating_machine_token_revokes_previous_credential`
  (`tests/test_auth.py`), and `test_resume_screen_keys_and_detach` (`tests/test_server.py`), which
  resumes an attachment and checks that the connection file and MCP config are new inodes, that the
  connection file carries the new token, that the old token gets 401, and that the new token gets 200.
- Restart recovery: `test_lifespan_starts_automatic_reattachment_without_a_browser`
  (`tests/test_server.py`, `ShutdownTest`). The automatic reattachment at startup gives the recovered
  attachment a new token. The earlier token and the token of a detached row both get 401, and the
  recovered token gets 200.
- Single detach: `test_single_detach_h1_is_revoked_across_resume_and_h2_uses_rotated_token`; bulk
  close: `test_bulk_close_revokes_each_h1_across_resume_and_h2_uses_rotated_token`
  (`tests/test_line_process_routes.py`). Each builds the same helper H1 before stopping and calls
  through real route authentication successfully. After detach or close, H1's next call with its
  cached token is rejected (structured 401, no message side effect, poller stopped); after resume H1
  stays rejected (the token was rotated) and a new helper H2, loaded from the regenerated connection
  file, succeeds.
- Replacement: `test_fresh_replaces_identity_and_revokes_old_token_without_chat_replay`
  (`tests/test_attachment_lifecycle.py`).
- Config helpers: `test_resume_regenerates_and_detach_removes` (`tests/test_mcp_attach.py`) calls
  `provision_connection` and `remove_connection` directly. It does not call `detach_attachment`, so the
  MCP-config removal on detach is shown by the code path, not by a test that runs detach.

Two things are not shown by these tests. First, after a detach the connection file stays on disk with
a token that no longer resolves, until the next resume or the removal of the record. Second, the
connection file is not a credential boundary against another process running as the same OS user; see
`docs/credentials.md`.

Revocation takes effect at the next request, not at the next poll. A running MCP server whose token
stops resolving gets HTTP 401 on its next API call and marks itself revoked (`_revoked`, `mcp/server.py`).
That state remains set after later failed calls. Later tool calls fail with "attachment credential is no
longer valid", and the poller sends a `notifications/message` error and stops. The revocation tests are
listed in `review-disposition.md`.
The lifecycle paths that make a token stop resolving are listed in the table above.

## 8. Errors

Tool errors return as results with `isError: true`. `ApiError` and `ValueError` messages are returned
as written, so the server's refusal text reaches the caller. `KeyError`, `TypeError`, and `OSError`
return "invalid tool arguments or local file". A deeply nested JSON value that exceeds Python's parser
recursion limit returns a structured JSON-RPC parse error and the helper continues reading input.
Any other exception returns "Partyline MCP operation failed" and logs the traceback through the Python
logger. A request with an ID and an unknown method gets JSON-RPC `-32601`.

## 9. Writes that must not duplicate speech

`post_message` refuses the caller's own line. A line's agent speaks through its transcript, so posting
into its own line over MCP would duplicate that speech. Each post requires a `client_key`; retry keys
are remembered before delivery starts. This handles a delivery failure after the key was recorded, but
does not close the separate-commit crash window described in section 6.

## 10. Limitations

- **Codex never re-lists.** The retained run (`fixture/codex-service-managed.log`) shows one
  `tools/list` at startup and no second listing after the fixture's `list_changed`. The dispatcher
  fallback worked: `dispatch({"name": "tool_b"})` returned `tool B result`. A named tool added
  mid-session is not callable directly on Codex unless Codex re-lists, which it never did in the
  retained run. Captains on Codex use `captain(op, args)` for anything that was not listed at startup.
- **Claude Code and OpenCode V2 re-list, shown against the fixture only.** The retained logs show a
  second `tools/list` about 2 s after the first on Claude Code 2.1.302 (`claude-service-managed.log`)
  and on OpenCode V2 2.0.32 (`opencode-v2-service-managed.log`). The model then called `tool_b`
  directly on Claude, and on OpenCode V2 it called both the dispatcher and `tool_b`. That evidence
  comes from the fixture's own notification. No retained run has observed a `list_changed` sent by
  Partyline's poller.
- **The fixture does not log its outgoing notification.** Its log records incoming methods and tool
  calls. The send itself is shown by the fixture code (`_notify_changed`, two seconds after the first
  listing), and the re-list in the log is the observable effect.
- **Refresh on calls, not push or polling.** Machines have no chat push feed in this slice (inventory
  decision 9), and an idle poll costs a request per process every few seconds. The server checks the
  signature on each call and sends `list_changed` then. A client that does not call sees a change only
  on its next call. A cached named tool is refused
  on that call, so reauthorization holds even without a re-list.
- **A dead token stays on disk after detach.** The connection file keeps the token that the detach
  made unusable (section 7) until the next resume rewrites it or the record is removed. The token is
  refused at the bearer lookup, so the file is inert, but it is still a copy of a credential. I did
  not find a test that reads the connection file after a detach.
- **Validator subset.** `partyline/mcp/validation.py` skips keywords it does not know, silently. A
  future schema that uses `pattern`, `format`, `anyOf`, `oneOf`, or `type: "null"` would be advertised
  but not enforced, and nothing would report that. Any such addition needs a test that proves the
  check happens, or the validator needs to grow first.
- **Codex override types.** `codex_overrides` renders only strings, booleans, numbers, lists, and
  dictionaries as TOML. Any other value raises `ValueError` at attach time. The current entry fields are
  a command string, a list of argument strings, and an environment dictionary of strings, so the error
  path is not reached in practice. `test_adds_entry_fields_as_toml_values` parses each override with
  `tomllib`, and `test_codex_toml_values_escape_awkward_environment_paths` checks an environment path with
  quotes and a backslash.
- **Write-set visibility.** `decide_write_set` is listed to a live lead because `tools_captain.py`
  `_ACTION` maps it to `read`, so a lead who can read the line sees the decision tool. The route
  enforces the ancestor-captain rule (`write_set_decisions.py`, `_machine_decision_error`). MCP only
  filters what is offered.
- **Withdrawal is not reachable through MCP for workers.** Captain operations require a live lead, so a
  worker withdraws its own write-set request on the route (inventory row 134), not through MCP.
- **Truncated results** are not valid JSON and have no cursor (section 6).
- **OpenCode V2 merge is skipped without an error** when an existing `OPENCODE_CONFIG_CONTENT` is
  unparseable or not an object. The server is then absent from that invocation, and nothing reports it.
- **Media links in tool results.** Same-service `/api/media/` URLs are rendered as host-relative
  paths, including links embedded in prose. Other absolute URLs are left as supplied by the source.
- **Versions.** Behaviour is recorded for Claude Code 2.1.302, Codex CLI 0.163.0, and OpenCode V2
  2.0.32 only. OpenCode V1 has no per-invocation MCP hook in this code.
- **Probe runs need local setup.** The whoami hook probes (`fixture/probe_*.py`) need a live Partyline
  attachment and checkout; the OpenCode V2 launcher also needs a locally configured preset, and the
  launchers name their CLI models. Set `PARTYLINE_PROBE_SCRATCH` to a fresh per-run scratch directory
  to keep generated MCP config there. Otherwise the config is written beside the attachment connection
  file. Their retained `.txt` files are prose summaries, not raw RPC output or version-bearing logs.
  These probes are evidence from one host and exercise adapter hooks, not service provisioning; the
  generated-entry subprocess regression is separate test evidence.
- **Codex attachment-home lifecycle and platform differences.** The shipping review observed
  `~/.partyline/sessions/codex/<attachment-id>` directories with mode 0775 and no cleanup; about 217
  existed at review time. It found `auth.json` symlinked on Linux and copied on Windows. These are
  existing adapter-home behaviors; the config copy fix does not change them. No real credential was
  copied for MCP evidence.
- **Runtime home provenance (unresolved).** A 516 MB Codex home appeared under `docs/mcp/isolate`
  during this work and was emptied before the audit. Its creator and whether it contained auth material
  are unknown. The `isolate/` directory must stay empty. See `docs/lessons.md`, "Runtime homes belong
  only in per-run scratchpads".

## Orchestrator task tools

`partyline/mcp/tools_tasks.py` adds four named tools, filtered by the live actions
from `/api/capabilities`. Every HTTP handler independently authorizes the caller.

| Tool | Caller | HTTP operation |
| --- | --- | --- |
| `create_task(name, goal, implementer, review?)` | Orchestrator root captain | POST `/api/conversations/{root}/tasks` |
| `tasks()` | Orchestrator root captain | GET `/api/conversations/{root}/tasks` |
| `blocked(reason)` | Exact assigned implementer attachment | POST `/api/conversations/{task}/blocked` |
| `waiting(reason, seconds?)` | Exact assigned implementer attachment | POST `/api/conversations/{task}/waiting` |
| `request_review(sha?, what, where)` | Exact assigned implementer attachment | POST `/api/conversations/{task}/request-review` |
| `review_verdict(verdict, findings)` | Exact assigned reviewer, or root captain for captain policy | POST `/api/conversations/{task}/review-verdict` |

The root captain supplies `conv_id` to `review_verdict`; assigned reviewers use
their home task line. Policies are `none`, `captain` (default), or an exact reviewer
preset name. Worker tools grant no staffing rights. Reviewer assignment is stored
and reused across unlimited rounds; reviewer approval is acceptance. Task state
is structured database state, never parsed from transcript prose. Reports notify
the root once on approved, done without review, or captain review requested;
return routing and idle-goal guards do not spend additional root turns during review.
See [the task lifecycle](../hierarchy.md#orchestrator-captains-and-task-lines).

`blocked(reason)` reports a dependency or other blocker to the root and sets the
blocked rail status. A new review attempt resumes implementation. A task without
a peer gets one structured-tool reminder on an unstructured return; returning
again after consuming it sends a deduplicated stalled report to the root.

`waiting(reason, seconds)` (60–3600, default 900) is the implementer's own
statement that a long command is running. The server records it on the task row
and posts one gentle `waiting, not stalled` note on the line; while the wait is
live neither the reminder nor the stalled report fires, and an implementer whose
harness turn is still open — a tool call in flight — is never stalled either.
When the wait runs out, the task owes a hand-off again and gets the same one
reminder, never a skipped straight to a stall report.
