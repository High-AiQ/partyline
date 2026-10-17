# Agent-facing HTTP API inventory

Scope: every HTTP and WebSocket route registered under `partyline/`, found by an AST pass over route decorators, `add_api_route` calls, and websocket registrations. Route numbers come from that pass and are fixed.

This document has two labelled sets:

- **Set 1: all routes found by the AST pass (136).** Method, path, file:line, caller class, and whether an agent principal can call the route.
- **Set 2: agent-reachable subset (104).** Every route Set 1 marks reachable, with its MCP disposition and reason.

**Agent-reachable** means a machine token or an attachment token passes the route's guard. Routes exempt from the bearer guard count as reachable because the guard admits any caller (rows 7-9, 108, 109). Human-only routes, the operator-token route (77), and the restart report-token route (98) are not agent-reachable.

Sources of truth for the implemented surface: `partyline/mcp/tools_core.py` (`tool_list`, `call`), `partyline/mcp/captain_schemas.py` (`OPERATIONS`), `partyline/mcp/captain_ops.py` (`execute`), and `partyline/mcp/tools_captain.py` (`permitted`).

## Caller key

**H** = human (JWT user, `Principal.kind == "user"`); **M** = any machine token on its own line (`allows(...)` decides); **L** = machine that is the line's lead/captain (`is_lead`) acting on its home line or a descendant; **LB** = loopback request (`require_loopback`). `allows()` rules come from `partyline/machine_scope.py:88`; anything not listed there is refused for machines. **Attachment token** = the per-attachment `runtime_owner` token in the path. **Operator token** = one-use token for local operator approval. **Report token** = restart machinery capability.

## Disposition vocabulary

- **tool**: a core tool in `partyline/mcp/tools_core.py`, named in backticks.
- **op**: a fixed captain operation in `partyline/mcp/captain_schemas.py`. A line captain reaches it as `captain(op, args)`, and as a named tool of the same name when the live check permits it.
- **guide**: read on demand through the core `guide` tool.
- **excluded**: never exposed to MCP. The reason states the rule.

## Set 1: all 136 routes (AST pass)

| # | Method | Path | file:line | Caller | Agent-reachable | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/conversations/{conv_id}/accepts` | partyline/accept_history.py:39 | M with `read` | yes | see Set 2 |
| 2 | POST | `/api/conversations/{conv_id}/accept` | partyline/accept_sha.py:240 | L with `accept` | yes | see Set 2 |
| 3 | GET | `/api/conversations/{conv_id}/approvals` | partyline/approval_bubble.py:133 | H only | no | approval queue is decided by people; machines never see it |
| 4 | POST | `/api/attachments/{att_id}/fresh` | partyline/attachment_lifecycle_routes.py:70 | LB with `attach` (human or lead) | yes | see Set 2 |
| 5 | POST | `/api/attachments/{att_id}/replace` | partyline/attachment_lifecycle_routes.py:88 | H, or M with `assign` | yes | see Set 2 |
| 6 | DELETE | `/api/attachments/{att_id}/record` | partyline/attachment_lifecycle_routes.py:157 | M with `close` | yes | see Set 2 |
| 7 | POST | `/api/auth/register` | partyline/auth_routes.py:120 | anyone (exempt) | yes | see Set 2 |
| 8 | POST | `/api/auth/login` | partyline/auth_routes.py:131 | anyone (exempt) | yes | see Set 2 |
| 9 | POST | `/api/auth/refresh` | partyline/auth_routes.py:141 | anyone (exempt) | yes | see Set 2 |
| 10 | GET | `/api/auth/me` | partyline/auth_routes.py:154 | H only | no | human account; a machine token gets 401; identity comes from `/api/capabilities` (row 42) |
| 11 | PATCH | `/api/auth/me` | partyline/auth_routes.py:158 | H only | no | human account management |
| 12 | POST | `/api/bridges` | partyline/bridge_routes.py:39 | H only | no | bridges are opened only by people |
| 13 | GET | `/api/bridges` | partyline/bridge_routes.py:45 | M with `read` | yes | see Set 2 |
| 14 | DELETE | `/api/bridges/{bridge_id}` | partyline/bridge_routes.py:53 | H only | no | bridges are closed only by people |
| 15 | GET | `/api/bridges/{bridge_id}/messages` | partyline/bridge_routes.py:60 | H only | no | bridge traffic crosses lines; person-only audit |
| 16 | GET | `/api/docs` | partyline/captain_docs.py:141 | H, or lead | yes | see Set 2 |
| 17 | GET | `/api/docs/{category}` | partyline/captain_docs.py:146 | H, or lead | yes | see Set 2 |
| 18 | GET | `/api/docs/{category}/{topic}` | partyline/captain_docs.py:154 | H, or lead | yes | see Set 2 |
| 19 | POST | `/api/attachments/{att_id}/compact` | partyline/compact_routes.py:31 | M with `attach` | yes | see Set 2 |
| 20 | DELETE | `/api/conversations/{conv_id}` | partyline/conversation_archive.py:46 | H, or M lead with `archive` on a descendant | yes | see Set 2 |
| 21 | GET | `/api/conversations` | partyline/conversation_routes.py:59 | H; M for visible lines | yes | see Set 2 |
| 22 | POST | `/api/conversations` | partyline/conversation_routes.py:68 | H only | no | only a person opens a top-level line |
| 23 | GET | `/api/conversations/{conv_id}` | partyline/conversation_routes.py:78 | M with `read` | yes | see Set 2 |
| 24 | PUT | `/api/conversations/{conv_id}/topic` | partyline/conversation_routes.py:86 | M with `write` | yes | see Set 2 |
| 25 | PUT | `/api/conversations/{conv_id}/name` | partyline/conversation_routes.py:106 | M with `write` | yes | see Set 2 |
| 26 | DELETE | `/api/conversations/archived` | partyline/conversation_routes.py:130 | H only | no | purge of all archived lines; person-only and destructive |
| 27 | POST | `/api/conversations/{conv_id}/restore` | partyline/conversation_routes.py:141 | M with `archive` | yes | see Set 2 |
| 28 | DELETE | `/api/conversations/{conv_id}/purge` | partyline/conversation_routes.py:156 | M with `archive` | yes | see Set 2 |
| 29 | POST | `/api/conversations/{conv_id}/attachments` | partyline/conversation_routes.py:172 | M with `attach` | yes | see Set 2 |
| 30 | GET | `/api/docker-relay` | partyline/docker_relay_routes.py:12 | H, or lead (own rows) | yes | see Set 2 |
| 31 | GET | `/api/docker-workloads` | partyline/docker_workload_routes.py:22 | H; M for visible rows | yes | see Set 2 |
| 32 | POST | `/api/docker-workloads/{container_id}/stop` | partyline/docker_workload_routes.py:29 | owning principal | yes | see Set 2 |
| 33 | GET | `/api/docker-gpu` | partyline/docker_workload_routes.py:33 | any principal | yes | see Set 2 |
| 34 | POST | `/api/docker-gpu/clear` | partyline/docker_workload_routes.py:38 | H only | no | GPU admission clear is person-only |
| 35 | PUT | `/api/docker-gpu` | partyline/docker_workload_routes.py:44 | H only | no | GPU slot count is person-only |
| 36 | PUT | `/api/conversations/{conv_id}/goal` | partyline/goal.py:63 | M with `assign`, or H | yes | see Set 2 |
| 37 | GET | `/api/heartbeat` | partyline/heartbeat_routes.py:70 | H, or root-lead attachment | yes | see Set 2 |
| 38 | POST | `/api/heartbeat` | partyline/heartbeat_routes.py:75 | root-lead machine (H refused) | yes | see Set 2 |
| 39 | GET | `/api/heartbeat/status` | partyline/heartbeat_routes.py:96 | root-lead attachment | yes | see Set 2 |
| 40 | GET | `/api/heartbeat/snapshots/{digest}` | partyline/heartbeat_routes.py:117 | root-lead attachment | yes | see Set 2 |
| 41 | DELETE | `/api/heartbeat` | partyline/heartbeat_routes.py:131 | root-lead attachment | yes | see Set 2 |
| 42 | GET | `/api/capabilities` | partyline/hierarchy_routes.py:66 | any principal | yes | see Set 2 |
| 43 | GET | `/api/conversations/{conv_id}/briefing` | partyline/hierarchy_routes.py:70 | M with `read`, and lead | yes | see Set 2 |
| 44 | GET | `/api/conversations/{conv_id}/lead` | partyline/hierarchy_routes.py:83 | M with `read`, or H | yes | see Set 2 |
| 45 | POST | `/api/conversations/{conv_id}/lead` | partyline/hierarchy_routes.py:89 | H, or M with `appoint_lead` | yes | see Set 2 |
| 46 | PUT | `/api/conversations/{conv_id}/parent` | partyline/hierarchy_routes.py:133 | H only | no | parent links are person-only |
| 47 | POST | `/api/conversations/{conv_id}/children` | partyline/hierarchy_routes.py:147 | L with `create_child` | yes | see Set 2 |
| 48 | GET | `/api/conversations/{conv_id}/children` | partyline/hierarchy_routes.py:207 | M with `read` | yes | see Set 2 |
| 49 | GET | `/api/conversations/{conv_id}/reports` | partyline/hierarchy_routes.py:212 | L with `read_reports` | yes | see Set 2 |
| 50 | POST | `/api/conversations/{conv_id}/reports` | partyline/hierarchy_routes.py:221 | L with `report` (or `notify`) | yes | see Set 2 |
| 51 | POST | `/api/conversations/{conv_id}/reports/{report_id}/ack` | partyline/hierarchy_routes.py:274 | L with `read_reports` | yes | see Set 2 |
| 52 | POST | `/api/hooks/{att_id}/{token}` | partyline/hook_routes.py:116 | attachment token in path | yes | see Set 2 |
| 53 | GET | `/api/hooks/{att_id}/{token}/rebrief` | partyline/hook_routes.py:120 | attachment token in path | yes | see Set 2 |
| 54 | GET | `/api/conversations/{conv_id}/base` | partyline/line_base.py:168 | M with `read` | yes | see Set 2 |
| 55 | GET | `/api/conversations/{conv_id}/tip` | partyline/line_base.py:180 | M with `read` | yes | see Set 2 |
| 56 | POST | `/api/conversations/{conv_id}/refresh-base` | partyline/line_base.py:203 | M with `write` | yes | see Set 2 |
| 57 | PUT | `/api/conversations/{conv_id}/gates` | partyline/line_gates.py:152 | H, or M with `assign` | yes | see Set 2 |
| 58 | GET | `/api/conversations/{conv_id}/gates` | partyline/line_gates.py:167 | M with `read` | yes | see Set 2 |
| 59 | GET | `/api/conversations/{conv_id}/notes` | partyline/line_notes.py:108 | M with `read` | yes | see Set 2 |
| 60 | PUT | `/api/conversations/{conv_id}/notes` | partyline/line_notes.py:120 | M, by scope | yes | see Set 2 |
| 61 | POST | `/api/conversations/{conv_id}/attachments/close` | partyline/line_process_routes.py:237 | M with `close` | yes | see Set 2 |
| 62 | GET | `/api/media/{file_id}/{variant}` | partyline/media_routes.py:166 | H; M with `read`; handed-to process | yes | see Set 2 |
| 63 | POST | `/api/conversations/{conv_id}/files` | partyline/media_routes.py:130 | M with `write` | yes | see Set 2 |
| 64 | POST | `/api/conversations/{conv_id}/images` | partyline/media_routes.py:137 | M with `write` | yes | see Set 2 |
| 65 | GET | `/api/conversations/{conv_id}/files` | partyline/media_routes.py:150 | M with `read` | yes | see Set 2 |
| 66 | GET | `/api/conversations/{conv_id}/images` | partyline/media_routes.py:157 | M with `read` | yes | see Set 2 |
| 67 | GET | `/api/conversations/{conv_id}/memory-request` | partyline/memory_requests.py:43 | M with `read` | yes | see Set 2 |
| 68 | POST | `/api/attachments/{att_id}/memory-requests` | partyline/memory_requests.py:48 | M with `attach` | yes | see Set 2 |
| 69 | POST | `/api/memory-requests/{request_id}/approve` | partyline/memory_requests.py:112 | M with `assign`, not the requester; or H | yes | see Set 2 |
| 70 | DELETE | `/api/memory-requests/{request_id}` | partyline/memory_requests.py:153 | M with `assign`, not the requester; or H | yes | see Set 2 |
| 71 | GET | `/api/attachments/{att_id}/memory` | partyline/memory_routes.py:32 | M with `read` | yes | see Set 2 |
| 72 | PUT | `/api/attachments/{att_id}/memory` | partyline/memory_routes.py:37 | M with `attach` (self-grant refused); H | yes | see Set 2 |
| 73 | POST | `/api/conversations/{conv_id}/messages/{message_id}/forward` | partyline/message_forward.py:40 | M with `read` (source), `write` (target) | yes | see Set 2 |
| 74 | GET | `/api/conversations/{conv_id}/messages` | partyline/message_routes.py:48 | M with `read` | yes | see Set 2 |
| 75 | GET | `/api/conversations/{conv_id}/messages/around` | partyline/message_routes.py:71 | M with `read` | yes | see Set 2 |
| 76 | POST | `/api/conversations/{conv_id}/messages` | partyline/message_routes.py:102 | M with `write` (own) or `assign` (other) | yes | see Set 2 |
| 77 | POST | `/api/restart-request/operator-approve` | partyline/operator_restart.py:60 | operator token (loopback) | no | local operator approval with a one-use operator token |
| 78 | GET | `/api/conversations/{conv_id}/pins` | partyline/pin_routes.py:37 | M with `read` | yes | see Set 2 |
| 79 | POST | `/api/conversations/{conv_id}/pins` | partyline/pin_routes.py:42 | H only | no | pins are person-only |
| 80 | PUT | `/api/conversations/{conv_id}/pins/{message_id}` | partyline/pin_routes.py:57 | H only | no | pin aliases are person-only |
| 81 | DELETE | `/api/conversations/{conv_id}/pins/{message_id}` | partyline/pin_routes.py:72 | H only | no | pin removal is person-only |
| 82 | POST | `/api/conversations/{conv_id}/prereview` | partyline/prereview.py:285 | M with `read` | yes | see Set 2 |
| 83 | GET | `/api/presets` | partyline/preset_routes.py:19 | any authenticated caller | yes | see Set 2 |
| 84 | POST | `/api/presets` | partyline/preset_routes.py:23 | H only | no | instance configuration; person-only |
| 85 | PUT | `/api/presets/{preset_id}` | partyline/preset_routes.py:27 | H only | no | instance configuration; person-only |
| 86 | DELETE | `/api/presets/{preset_id}` | partyline/preset_routes.py:33 | H only | no | instance configuration; person-only |
| 87 | GET | `/api/conversations/{conv_id}/process-overview` | partyline/process_overview.py:102 | M with `read` | yes | see Set 2 |
| 88 | POST | `/api/attachments/{att_id}/signal` | partyline/process_signal.py:81 | owning process or line captain | yes | see Set 2 |
| 89 | POST | `/api/messages/{message_id}/reactions` | partyline/reaction_routes.py:105 | H, or machine on the message's line | yes | see Set 2 |
| 90 | DELETE | `/api/messages/{message_id}/reactions/{emoji}` | partyline/reaction_routes.py:109 | H, or machine on the message's line | yes | see Set 2 |
| 91 | POST | `/api/leases` | partyline/resource_leases.py:218 | process (`attachment_id` required) | yes | see Set 2 |
| 92 | GET | `/api/leases` | partyline/resource_leases.py:237 | any authenticated caller | yes | see Set 2 |
| 93 | DELETE | `/api/leases/{name}` | partyline/resource_leases.py:242 | holding process | yes | see Set 2 |
| 94 | GET | `/api/resources` | partyline/resource_routes.py:17 | any authenticated caller | yes | see Set 2 |
| 95 | GET | `/api/settings/resources` | partyline/resource_routes.py:23 | H only | no | resource settings are person-only |
| 96 | PUT | `/api/settings/resources` | partyline/resource_routes.py:36 | H only | no | resource settings are person-only |
| 97 | POST | `/api/settings/resources/reset` | partyline/resource_routes.py:65 | H only | no | resource settings are person-only |
| 98 | POST | `/api/restart-plan/failure` | partyline/restart_report.py:32 | report token (loopback) | no | restart machinery capability, not an agent credential |
| 99 | GET | `/api/restart-request` | partyline/restart_requests.py:122 | any authenticated caller | yes | see Set 2 |
| 100 | POST | `/api/conversations/{conv_id}/restart-request` | partyline/restart_requests.py:127 | M with `assign`, or H | yes | see Set 2 |
| 101 | POST | `/api/restart-request/{request_id}/approve` | partyline/restart_requests.py:172 | H only | no | restart approval is a person's decision |
| 102 | DELETE | `/api/restart-request/{request_id}` | partyline/restart_requests.py:206 | H only | no | restart decline is person-only |
| 103 | POST | `/api/conversations/{conv_id}/review-worktrees` | partyline/review_worktrees.py:247 | M with `write` | yes | see Set 2 |
| 104 | GET | `/api/conversations/{conv_id}/review-worktrees` | partyline/review_worktrees.py:269 | M with `read` | yes | see Set 2 |
| 105 | POST | `/api/conversations/{conv_id}/scratch-worktrees` | partyline/scratch_worktrees.py:255 | M with `write` | yes | see Set 2 |
| 106 | GET | `/api/conversations/{conv_id}/scratch-worktrees` | partyline/scratch_worktrees.py:278 | M with `read` | yes | see Set 2 |
| 107 | DELETE | `/api/conversations/{conv_id}/scratch-worktrees/{sha}` | partyline/scratch_worktrees.py:283 | M with `write` | yes | see Set 2 |
| 108 | GET | `/` | partyline/server.py:244 | anyone (exempt) | yes | see Set 2 |
| 109 | GET | `/api/version` | partyline/server.py:264 | anyone (exempt) | yes | see Set 2 |
| 110 | GET | `/api/running` | partyline/server.py:316 | any authenticated caller (visible lines for M) | yes | see Set 2 |
| 111 | POST | `/api/restart-plan` | partyline/server.py:328 | loopback with `allows_restart_plan` | yes | see Set 2 |
| 112 | POST | `/api/shutdown` | partyline/server.py:344 | H only (loopback) | no | instance shutdown is a human operator act |
| 113 | GET | `/api/features` | partyline/server.py:378 | any authenticated caller | yes | see Set 2 |
| 114 | GET | `/api/fence/status` | partyline/server.py:384 | any authenticated caller | yes | see Set 2 |
| 115 | GET | `/api/adapters` | partyline/server.py:390 | any authenticated caller | yes | see Set 2 |
| 116 | POST | `/api/adapters/import` | partyline/server.py:395 | H only | no | adapter import is human-only instance configuration |
| 117 | POST | `/api/adapters/reload` | partyline/server.py:404 | H only | no | adapter reload is human-only instance configuration |
| 118 | DELETE | `/api/adapters/{adapter_name}` | partyline/server.py:413 | H only | no | adapter removal is human-only instance configuration |
| 119 | POST | `/api/attachments/{att_id}/resume` | partyline/server.py:459 | M with `attach`, or H | yes | see Set 2 |
| 120 | PATCH | `/api/attachments/{att_id}` | partyline/server.py:490 | M with `attach`, loopback, stopped attachment | yes | see Set 2 |
| 121 | DELETE | `/api/attachments/{att_id}` | partyline/server.py:515 | M with `close`, or H | yes | see Set 2 |
| 122 | GET | `/api/attachments/{att_id}/screen` | partyline/server.py:525 | M with `read` | yes | see Set 2 |
| 123 | POST | `/api/attachments/{att_id}/keys` | partyline/server.py:544 | M with `attach` | yes | see Set 2 |
| 124 | WEBSOCKET | `/ws/{conv_id}` | partyline/server.py:557 | H only | no | chat socket is for humans; machine tokens are closed with 4403; agents poll `read_messages` |
| 125 | GET | `/api/settings/global_prose` | partyline/settings_routes.py:13 | H only | no | global prose is person-only |
| 126 | PUT | `/api/settings/global_prose` | partyline/settings_routes.py:18 | H only | no | global prose is person-only |
| 127 | GET | `/api/conversations/{conv_id}/staffing` | partyline/staffing_routes.py:18 | M with `assign` | yes | see Set 2 |
| 128 | WS | `/ws/attachments/{att_id}/terminal` | partyline/terminal_stream.py:64 | M with `read` on the attachment's line (input needs `attach`) | yes | see Set 2 |
| 129 | POST | `/api/conversations/{conv_id}/tmp/reap` | partyline/tmp_reap_routes.py:25 | H, or root captain | yes | see Set 2 |
| 130 | GET | `/api/conversations/{conv_id}/write-set/request` | partyline/write_set_decisions.py:99 | M with `read` | yes | see Set 2 |
| 131 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/approve` | partyline/write_set_decisions.py:128 | H, or ancestor captain | yes | see Set 2 |
| 132 | DELETE | `/api/conversations/{conv_id}/write-set/request/{request_id}` | partyline/write_set_decisions.py:162 | H only | no | decline is person-only |
| 133 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/deny` | partyline/write_set_decisions.py:176 | H, or ancestor captain | yes | see Set 2 |
| 134 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/withdraw` | partyline/write_set_decisions.py:191 | requesting attachment | yes | see Set 2 |
| 135 | GET | `/api/conversations/{conv_id}/write-set` | partyline/write_set_routes.py:87 | M with `read` | yes | see Set 2 |
| 136 | POST | `/api/conversations/{conv_id}/write-set` | partyline/write_set_routes.py:93 | H grants; M files a request | yes | see Set 2 |

## Set 2: agent-reachable subset (104 routes)

| # | Method | Path | Caller | Disposition | Reason |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/conversations/{conv_id}/accepts` | M with `read` | **excluded** | accept history is not needed by the tool set; captains record accepts through `accept` (row 2) |
| 2 | POST | `/api/conversations/{conv_id}/accept` | L with `accept` | **op**: captain op `accept` | parent captain records a child SHA; `run_gates` runs gates server-side; reviewer identity comes from the credential |
| 4 | POST | `/api/attachments/{att_id}/fresh` | LB with `attach` (human or lead) | **excluded** | loopback-only process lifecycle; the restart flow, not a routine captain tool |
| 5 | POST | `/api/attachments/{att_id}/replace` | H, or M with `assign` | **excluded** | process swaps are rare; captains use `attach_worker` then `detach_worker` |
| 6 | DELETE | `/api/attachments/{att_id}/record` | M with `close` | **excluded** | destructive record delete; no captain need |
| 7 | POST | `/api/auth/register` | anyone (exempt) | **excluded** | human sign-up |
| 8 | POST | `/api/auth/login` | anyone (exempt) | **excluded** | human password login |
| 9 | POST | `/api/auth/refresh` | anyone (exempt) | **excluded** | human session refresh |
| 13 | GET | `/api/bridges` | M with `read` | **excluded** | bridges are person-only; machines get no bridge read |
| 16 | GET | `/api/docs` | H, or lead | **guide**: `guide` (no arguments) | docs index, read on demand |
| 17 | GET | `/api/docs/{category}` | H, or lead | **guide**: `guide` (category) | topic list, read on demand |
| 18 | GET | `/api/docs/{category}/{topic}` | H, or lead | **guide**: `guide` (category, topic); captain op `docs_read` | bounded doc slice; `docs_read` is the lead-only form |
| 19 | POST | `/api/attachments/{att_id}/compact` | M with `attach` | **excluded** | adapter-specific process control; not a captain op |
| 20 | DELETE | `/api/conversations/{conv_id}` | H, or M lead with `archive` on a descendant | **op**: captain op `retire_child` | archive a direct child only; `stop_processes` optional; purge stays excluded (row 28) |
| 21 | GET | `/api/conversations` | H; M for visible lines | **excluded** | `whoami` gives parent, children and home line, which is the targeting the tool set needs; no cross-line listing |
| 23 | GET | `/api/conversations/{conv_id}` | M with `read` | **tool**: via `whoami` (members) and `goal` (get) | line detail is read inside those tools, not as its own tool |
| 24 | PUT | `/api/conversations/{conv_id}/topic` | M with `write` | **excluded** | topic is line context; the captain's goal carries direction (`set_goal`) |
| 25 | PUT | `/api/conversations/{conv_id}/name` | M with `write` | **excluded** | rename is not a captain or worker duty |
| 27 | POST | `/api/conversations/{conv_id}/restore` | M with `archive` | **excluded** | archive lifecycle is outside the tool set |
| 28 | DELETE | `/api/conversations/{conv_id}/purge` | M with `archive` | **excluded** | purge excluded: hard delete of an archived line |
| 29 | POST | `/api/conversations/{conv_id}/attachments` | M with `attach` | **op**: captain op `attach_worker` (`preset_name` is a read-only match) | lead staffs workers; the server refuses parallel-worker and sideways attaches |
| 30 | GET | `/api/docker-relay` | H, or lead (own rows) | **excluded** | host infrastructure |
| 31 | GET | `/api/docker-workloads` | H; M for visible rows | **excluded** | host infrastructure |
| 32 | POST | `/api/docker-workloads/{container_id}/stop` | owning principal | **excluded** | destructive, host-level container stop |
| 33 | GET | `/api/docker-gpu` | any principal | **excluded** | host GPU admission state; not captain or worker scope |
| 36 | PUT | `/api/conversations/{conv_id}/goal` | M with `assign`, or H | **tool**: `goal` (set) and captain op `set_goal` | line goal; both forms reach this route, and `goal` set needs `assign` |
| 37 | GET | `/api/heartbeat` | H, or root-lead attachment | **excluded** | root heartbeat belongs to the root manager, not captain or worker scope |
| 38 | POST | `/api/heartbeat` | root-lead machine (H refused) | **excluded** | root heartbeat belongs to the root manager |
| 39 | GET | `/api/heartbeat/status` | root-lead attachment | **excluded** | root heartbeat belongs to the root manager |
| 40 | GET | `/api/heartbeat/snapshots/{digest}` | root-lead attachment | **excluded** | root heartbeat belongs to the root manager |
| 41 | DELETE | `/api/heartbeat` | root-lead attachment | **excluded** | root heartbeat belongs to the root manager |
| 42 | GET | `/api/capabilities` | any principal | **tool**: `whoami` | identity, role, actions and depth; the first call for every agent |
| 43 | GET | `/api/conversations/{conv_id}/briefing` | M with `read`, and lead | **excluded** | captain briefing is not exposed; the role brief reaches the process through the hook path (rows 52-53) |
| 44 | GET | `/api/conversations/{conv_id}/lead` | M with `read`, or H | **tool**: via `whoami` (members, `is_lead`, parent) | who captains the line is reported inside `whoami` |
| 45 | POST | `/api/conversations/{conv_id}/lead` | H, or M with `appoint_lead` | **op**: captain op `appoint_lead` | lead appointment is a captain op; an empty `attachment_id` clears the lead |
| 47 | POST | `/api/conversations/{conv_id}/children` | L with `create_child` | **op**: captain op `create_child` | refused with live workers and at the depth cap |
| 48 | GET | `/api/conversations/{conv_id}/children` | M with `read` | **tool**: via `whoami` (children) | children are reported inside `whoami` |
| 49 | GET | `/api/conversations/{conv_id}/reports` | L with `read_reports` | **tool**: `reports` (list) | reports received from child lines |
| 50 | POST | `/api/conversations/{conv_id}/reports` | L with `report` (or `notify`) | **tool**: `reports` (post; `notify` flag) | captain reports to its parent |
| 51 | POST | `/api/conversations/{conv_id}/reports/{report_id}/ack` | L with `read_reports` | **op**: captain op `ack_report` | acknowledges a child report |
| 52 | POST | `/api/hooks/{att_id}/{token}` | attachment token in path | **excluded** | adapter hook transport |
| 53 | GET | `/api/hooks/{att_id}/{token}/rebrief` | attachment token in path | **excluded** | adapter hook transport |
| 54 | GET | `/api/conversations/{conv_id}/base` | M with `read` | **excluded** | git base read; not needed by the tool set |
| 55 | GET | `/api/conversations/{conv_id}/tip` | M with `read` | **excluded** | git tip read; not needed by the tool set |
| 56 | POST | `/api/conversations/{conv_id}/refresh-base` | M with `write` | **excluded** | base-mirror refresh is a git-side effect; the tool set does not change git refs |
| 57 | PUT | `/api/conversations/{conv_id}/gates` | H, or M with `assign` | **op**: captain op `set_gates` | declared gate commands; timeout capped at 14400 s |
| 58 | GET | `/api/conversations/{conv_id}/gates` | M with `read` | **excluded** | the captain declares gates with `set_gates` (row 57); reading them back is not needed by the tool set |
| 59 | GET | `/api/conversations/{conv_id}/notes` | M with `read` | **tool**: `notes` (get) | line, tree or own attachment scope |
| 60 | PUT | `/api/conversations/{conv_id}/notes` | M, by scope | **tool**: `notes` (set) | attachment notes are own only; line and tree need captain `assign`; 4000-character cap |
| 61 | POST | `/api/conversations/{conv_id}/attachments/close` | M with `close` | **excluded** | bulk stop; captains detach one worker at a time (`detach_worker`) |
| 62 | GET | `/api/media/{file_id}/{variant}` | H; M with `read`; handed-to process | **tool**: `get_media` | downloads to a new local path with a size bound |
| 63 | POST | `/api/conversations/{conv_id}/files` | M with `write` | **tool**: `upload_file` | sends one local file through the `/files` route |
| 64 | POST | `/api/conversations/{conv_id}/images` | M with `write` | **excluded** | no separate tool; `upload_file` posts to `/files` (row 63), so images travel as files |
| 65 | GET | `/api/conversations/{conv_id}/files` | M with `read` | **excluded** | file listing is not needed; file references arrive in messages and `get_media` fetches by id (row 62) |
| 66 | GET | `/api/conversations/{conv_id}/images` | M with `read` | **excluded** | image listing is not needed; same as row 65 |
| 67 | GET | `/api/conversations/{conv_id}/memory-request` | M with `read` | **excluded** | host memory budget; adjustments belong to the approved memory-lease design, where the root captain adjudicates |
| 68 | POST | `/api/attachments/{att_id}/memory-requests` | M with `attach` | **excluded** | host memory budget; same design as row 67 |
| 69 | POST | `/api/memory-requests/{request_id}/approve` | M with `assign`, not the requester; or H | **excluded** | host memory budget; same design as row 67 |
| 70 | DELETE | `/api/memory-requests/{request_id}` | M with `assign`, not the requester; or H | **excluded** | host memory budget; same design as row 67 |
| 71 | GET | `/api/attachments/{att_id}/memory` | M with `read` | **excluded** | host memory budget |
| 72 | PUT | `/api/attachments/{att_id}/memory` | M with `attach` (self-grant refused); H | **excluded** | a process cannot raise its own limit; host budget |
| 73 | POST | `/api/conversations/{conv_id}/messages/{message_id}/forward` | M with `read` (source), `write` (target) | **excluded** | `post_message` carries cross-line speech; forwarding is not needed by the tool set |
| 74 | GET | `/api/conversations/{conv_id}/messages` | M with `read` | **tool**: `read_messages` | history page, limit 1 to 50 |
| 75 | GET | `/api/conversations/{conv_id}/messages/around` | M with `read` | **tool**: `read_messages` (`around_id`) | page around one message id |
| 76 | POST | `/api/conversations/{conv_id}/messages` | M with `write` (own) or `assign` (other) | **tool**: `post_message` (other lines only) | own-line posts are refused so the transcript stays the only speech path and nothing is posted twice |
| 78 | GET | `/api/conversations/{conv_id}/pins` | M with `read` | **excluded** | pins are person-curated; reading them is not needed by the tool set |
| 82 | POST | `/api/conversations/{conv_id}/prereview` | M with `read` | **excluded** | pre-review is not a captain op; `accept` takes `run_gates` for the gate step (row 2) |
| 83 | GET | `/api/presets` | any authenticated caller | **op**: captain op `list_presets` (read-only) | presets are read-only for captains; writes are person-only (rows 84-86) |
| 87 | GET | `/api/conversations/{conv_id}/process-overview` | M with `read` | **op**: captain op `process_overview` | live phase and RSS for the line's attachments |
| 88 | POST | `/api/attachments/{att_id}/signal` | owning process or line captain | **excluded** | destructive pid signal; pids do not resolve through the host namespace from inside the fence |
| 89 | POST | `/api/messages/{message_id}/reactions` | H, or machine on the message's line | **tool**: `react` (add) | own line only; the reactor's line must be the message's line |
| 90 | DELETE | `/api/messages/{message_id}/reactions/{emoji}` | H, or machine on the message's line | **tool**: `react` (remove) | own line only; same rule as row 89 |
| 91 | POST | `/api/leases` | process (`attachment_id` required) | **excluded** | leases are for timing and device-exclusive runs taken by the process itself (AGENTS.md) |
| 92 | GET | `/api/leases` | any authenticated caller | **excluded** | leases are for timing and device-exclusive runs (AGENTS.md) |
| 93 | DELETE | `/api/leases/{name}` | holding process | **excluded** | leases are for timing and device-exclusive runs (AGENTS.md) |
| 94 | GET | `/api/resources` | any authenticated caller | **excluded** | host telemetry |
| 99 | GET | `/api/restart-request` | any authenticated caller | **excluded** | restart requests are a person's decision; a captain files one with `request_restart` |
| 100 | POST | `/api/conversations/{conv_id}/restart-request` | M with `assign`, or H | **op**: captain op `request_restart` | approval stays with a person |
| 103 | POST | `/api/conversations/{conv_id}/review-worktrees` | M with `write` | **op**: captain op `review_worktree` | AGENTS.md requires a Partyline-managed review worktree before accept |
| 104 | GET | `/api/conversations/{conv_id}/review-worktrees` | M with `read` | **excluded** | review-worktree listing is not needed; `review_worktree` (row 103) is the captain's path to a review checkout |
| 105 | POST | `/api/conversations/{conv_id}/scratch-worktrees` | M with `write` | **excluded** | scratch checkouts are not needed by the tool set |
| 106 | GET | `/api/conversations/{conv_id}/scratch-worktrees` | M with `read` | **excluded** | scratch checkouts are not needed by the tool set |
| 107 | DELETE | `/api/conversations/{conv_id}/scratch-worktrees/{sha}` | M with `write` | **excluded** | scratch checkouts are not needed by the tool set |
| 108 | GET | `/` | anyone (exempt) | **excluded** | browser shell |
| 109 | GET | `/api/version` | anyone (exempt) | **excluded** | unauthenticated version string; not needed by the tool set |
| 110 | GET | `/api/running` | any authenticated caller (visible lines for M) | **excluded** | covered per line by row 87 (`process_overview`) |
| 111 | POST | `/api/restart-plan` | loopback with `allows_restart_plan` | **excluded** | restart planning on loopback; the restart flow is in `docs/restart.md` |
| 113 | GET | `/api/features` | any authenticated caller | **excluded** | instance configuration |
| 114 | GET | `/api/fence/status` | any authenticated caller | **excluded** | fence diagnosis; EROFS denials are answered by the write-set path (row 136) |
| 115 | GET | `/api/adapters` | any authenticated caller | **excluded** | instance configuration |
| 119 | POST | `/api/attachments/{att_id}/resume` | M with `attach`, or H | **excluded** | resume belongs to the restart and resume flow |
| 120 | PATCH | `/api/attachments/{att_id}` | M with `attach`, loopback, stopped attachment | **excluded** | changes a stopped process's command; loopback only |
| 121 | DELETE | `/api/attachments/{att_id}` | M with `close`, or H | **op**: captain op `detach_worker` | stops one worker on the target line; server stop rules apply; the worker's token stops resolving (design.md section 7), and the caller's own token is unaffected |
| 122 | GET | `/api/attachments/{att_id}/screen` | M with `read` | **excluded** | screen text is never speech (AGENTS.md); debugging only |
| 123 | POST | `/api/attachments/{att_id}/keys` | M with `attach` | **excluded** | raw keystrokes into another process's PTY |
| 127 | GET | `/api/conversations/{conv_id}/staffing` | M with `assign` | **op**: captain op `staffing` | who works the line |
| 128 | WS | `/ws/attachments/{att_id}/terminal` | M with `read` on the attachment's line (input needs `attach`) | **excluded** | raw PTY stream, not structured speech; the watch-any-attachment gap is fixed on this branch by bf8573a (per-line `read` and `attach` checks, rechecked while open); MCP still excludes it |
| 129 | POST | `/api/conversations/{conv_id}/tmp/reap` | H, or root captain | **excluded** | destructive temp reap; root captain or person |
| 130 | GET | `/api/conversations/{conv_id}/write-set/request` | M with `read` | **op**: captain op `write_set_requests` (read-only) | lists pending requests (this row) and current grants (row 135) on a line the caller may read, so `decide_write_set` callers can find a request id |
| 131 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/approve` | H, or ancestor captain | **op**: captain op `decide_write_set` (approve) | ancestor captain only inside its own grants; the route enforces that rule |
| 133 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/deny` | H, or ancestor captain | **op**: captain op `decide_write_set` (deny; reason required) | ancestor captain only inside its own grants; the route enforces that rule |
| 134 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/withdraw` | requesting attachment | **op**: captain op `decide_write_set` (withdraw) | withdraw is the requester's act; captain ops need a live lead, so a worker withdraws on the route |
| 135 | GET | `/api/conversations/{conv_id}/write-set` | M with `read` | **op**: captain op `write_set_requests` (read-only) | lists current grants on a line the caller may read; pending requests are row 130 |
| 136 | POST | `/api/conversations/{conv_id}/write-set` | H grants; M files a request | **op**: captain op `request_write_set` (lead) | a person or ancestor captain decides; worker requests keep the fence message's direct POST; Docker mode is person-only (403) |

## Implemented names and the routes they reach

| Name | Kind | Routes |
| --- | --- | --- |
| `whoami` | core tool | 23, 42, 44, 48 |
| `guide` | core tool | 16, 17, 18 |
| `read_messages` | core tool | 74, 75 |
| `notes` | core tool | 59, 60 |
| `goal` | core tool | 23, 36 |
| `post_message` | core tool | 76 |
| `upload_file` | core tool | 63 |
| `get_media` | core tool | 62 |
| `reports` | core tool | 49, 50 |
| `react` | core tool | 89, 90 |
| `staffing` | captain op | 127 |
| `list_presets` | captain op | 83 |
| `attach_worker` | captain op | 29 |
| `detach_worker` | captain op | 121 |
| `create_child` | captain op | 47 |
| `appoint_lead` | captain op | 45 |
| `retire_child` | captain op | 20 |
| `accept` | captain op | 2 |
| `review_worktree` | captain op | 103 |
| `request_write_set` | captain op | 136 |
| `write_set_requests` | captain op | 130, 135 |
| `decide_write_set` | captain op | 131, 133, 134 |
| `request_restart` | captain op | 100 |
| `process_overview` | captain op | 87 |
| `ack_report` | captain op | 51 |
| `set_goal` | captain op | 36 |
| `set_gates` | captain op | 57 |
| `docs_read` | captain op | 18 |

## Decisions

1. **Loopback lifecycle (rows 4, 111, 120).** Excluded from MCP. An on-host lead passes the loopback check, so these routes stay agent-reachable, but process lifecycle is not a captain tool.
2. **Child retirement and purge (rows 20, 26, 28).** Retirement is captain op `retire_child`: a direct child only, archive only, `stop_processes` optional. Purge is excluded; hard delete is never reachable through MCP.
3. **Lead appointment (row 45).** Captain op `appoint_lead`; an empty `attachment_id` clears the lead.
4. **Bridges (rows 12-15).** Person-only. Machines get no bridge tool and no bridge read.
5. **Decline (rows 102, 132).** Person-only. Captains approve or deny write-set requests (131, 133) and withdraw their own (134); decline is not reachable by machines. Captains find request ids through captain op `write_set_requests` (rows 130, 135).
6. **Presets (rows 83-86).** `list_presets` is a read-only captain op; create, update, and delete are person-only.
7. **Terminal socket, screen, and keys (rows 122, 123, 128).** Excluded. The terminal stream is raw PTY output, not speech; screen text is debugging only; keystrokes are never sent through MCP.
8. **Terminal socket authentication (row 128).** Fixed on this branch by bf8573a. The socket checks per-line `read` (and `attach` for input) and rechecks while open. MCP still excludes it: raw PTY output is not speech.
9. **Chat socket (row 124).** Machines have no push feed in this slice. Agents poll `read_messages` (row 74).
10. **Memory (rows 67-72).** Excluded in this slice. The approved memory-lease design routes adjustment requests through the root captain, so no captain tool is added here.
11. **Root heartbeat (rows 37-41).** Excluded. It is the root manager's surface, not captain or worker scope.
12. **Write-set requests (row 136).** A lead requests through captain op `request_write_set`. Worker requests keep the fence message's direct POST, which is outside MCP in this slice.
13. **Docs (rows 16-18).** Read through `guide`. Captain op `docs_read` is the lead-only form of row 18.
14. **Shared-branch and parallel-worker refusals (row 29).** Enforced by the server on the route; MCP passes the refusal text back unchanged.

## Limitations

- **Write-set decisions are visible on `read`, enforced on the route.** `decide_write_set` is offered to a live lead through the MCP check with `read` (`tools_captain.py` `_ACTION`). The routes enforce the ancestor-captain rule (`write_set_decisions.py` `_machine_decision_error`). The route is the authority; the MCP check only filters what is offered.
- **Captain ops need a live lead.** A worker cannot withdraw its own write-set request through MCP (row 134); it stays on the route.
- **Image upload.** Row 64 has no separate tool; `upload_file` posts to `/files` (row 63).
- **Detach and token revocation.** Every route that detaches an attachment (for example rows 61, 121,
  and the write-set approval routes) makes that attachment's token stop resolving, because the bearer
  lookup accepts only `starting` and `running` rows (`auth_store.attachment_by_api_token`). The rows
  above do not repeat this for each route. design.md section 7 has the lifecycle table and its tests.

## Coverage

136 routes in total: 104 agent-reachable (Set 2) + 32 not agent-reachable (Set 1 notes) = 136. Route numbers 1-136 each appear exactly once in Set 1, and each agent-reachable number appears exactly once in Set 2. Dispositions in Set 2: 16 tool, 19 op, 3 guide, 66 excluded.
