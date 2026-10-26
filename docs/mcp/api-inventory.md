# Agent-facing HTTP API inventory

Scope: every HTTP and WebSocket route registered under `partyline/`, found by an AST pass over route decorators, `add_api_route` calls, and websocket registrations. Route numbers come from that pass and are fixed.

This document has two labelled sets:

- **Set 1: all routes found by the AST pass (136).** Method, path, source handler and current registration line, caller class, and whether an agent principal can call the route. Handler names are the stable reference; registration lines are a locator for this source revision.
- **Set 2: agent-reachable subset (104).** Every route Set 1 marks reachable, with its MCP disposition and reason.

**Agent-reachable** means a machine token or an attachment token passes the route's guard. Routes exempt from the bearer guard count as reachable because the guard admits any caller (rows 7-9, 108, 109). Human-only routes, the operator-token route (77), and the restart report-token route (98) are not agent-reachable.

Sources of truth for the implemented surface: `partyline/mcp/tools_core.py` (`tool_list`, `call`), `partyline/mcp/captain_schemas.py` (`OPERATIONS`), `partyline/mcp/captain_ops.py` (`execute`), and `partyline/mcp/tools_captain.py` (`permitted`).

## Caller key

**H** = human (JWT user, `Principal.kind == "user"`); **M** = any machine token on its own line (`allows(...)` decides); **L** = machine that is the line's lead/captain (`is_lead`) acting on its home line or a descendant; **LB** = loopback request (`require_loopback`). `allows()` rules come from `partyline/machine_scope.py:allows`; anything not listed there is refused for machines. **Attachment token** = the per-attachment `runtime_owner` token in the path. **Operator token** = one-use token for local operator approval. **Report token** = restart machinery capability.

## Disposition vocabulary

- **tool**: a core tool in `partyline/mcp/tools_core.py`, named in backticks.
- **op**: a fixed captain operation in `partyline/mcp/captain_schemas.py`. A line captain reaches it as `captain(op, args)`, and as a named tool of the same name when the live check permits it.
- **guide**: read on demand through the core `guide` tool.
- **excluded**: never exposed to MCP. The reason states the rule.

## Set 1: all 136 routes (AST pass)

| # | Method | Path | Source handler (registration line) | Caller | Agent-reachable | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/conversations/{conv_id}/accepts` | partyline/accept_history.py:accepts (registration line 38) | M with `read` | yes | see Set 2 |
| 2 | POST | `/api/conversations/{conv_id}/accept` | partyline/accept_sha.py:accept (registration line 239) | L with `accept` | yes | see Set 2 |
| 3 | GET | `/api/conversations/{conv_id}/approvals` | partyline/approval_bubble.py:approvals (registration line 132) | H only | no | approval queue is decided by people; machines never see it |
| 4 | POST | `/api/attachments/{att_id}/fresh` | partyline/attachment_lifecycle_routes.py:fresh_attachment (registration line 69) | LB with `attach` (human or lead) | yes | see Set 2 |
| 5 | POST | `/api/attachments/{att_id}/replace` | partyline/attachment_lifecycle_routes.py:replace_attachment (registration line 87) | H, or M with `assign` | yes | see Set 2 |
| 6 | DELETE | `/api/attachments/{att_id}/record` | partyline/attachment_lifecycle_routes.py:remove_attachment_record (registration line 156) | M with `close` | yes | see Set 2 |
| 7 | POST | `/api/auth/register` | partyline/auth_routes.py:register (registration line 119) | anyone (exempt) | yes | see Set 2 |
| 8 | POST | `/api/auth/login` | partyline/auth_routes.py:login (registration line 130) | anyone (exempt) | yes | see Set 2 |
| 9 | POST | `/api/auth/refresh` | partyline/auth_routes.py:refresh (registration line 140) | anyone (exempt) | yes | see Set 2 |
| 10 | GET | `/api/auth/me` | partyline/auth_routes.py:me (registration line 153) | H only | no | human account; a machine token gets 401; identity comes from `/api/capabilities` (row 42) |
| 11 | PATCH | `/api/auth/me` | partyline/auth_routes.py:change_handle (registration line 157) | H only | no | human account management |
| 12 | POST | `/api/bridges` | partyline/bridge_routes.py:post_bridge (registration line 38) | H only | no | bridges are opened only by people |
| 13 | GET | `/api/bridges` | partyline/bridge_routes.py:get_bridge (registration line 44) | M with `read` | yes | see Set 2 |
| 14 | DELETE | `/api/bridges/{bridge_id}` | partyline/bridge_routes.py:delete_bridge (registration line 52) | H only | no | bridges are closed only by people |
| 15 | GET | `/api/bridges/{bridge_id}/messages` | partyline/bridge_routes.py:bridge_messages (registration line 59) | H only | no | bridge traffic crosses lines; person-only audit |
| 16 | GET | `/api/docs` | partyline/captain_docs.py:docs_index (registration line 140) | H, or lead | yes | see Set 2 |
| 17 | GET | `/api/docs/{category}` | partyline/captain_docs.py:docs_category (registration line 145) | H, or lead | yes | see Set 2 |
| 18 | GET | `/api/docs/{category}/{topic}` | partyline/captain_docs.py:docs_topic (registration line 153) | H, or lead | yes | see Set 2 |
| 19 | POST | `/api/attachments/{att_id}/compact` | partyline/compact_routes.py:compact_attachment (registration line 30) | M with `attach` | yes | see Set 2 |
| 20 | DELETE | `/api/conversations/{conv_id}` | partyline/conversation_archive.py:archive_conversation (registration line 41) | H, or M lead with `archive` on a descendant | yes | see Set 2 |
| 21 | GET | `/api/conversations` | partyline/conversation_routes.py:conversations (registration line 58) | H; M for visible lines | yes | see Set 2 |
| 22 | POST | `/api/conversations` | partyline/conversation_routes.py:create_conversation (registration line 67) | H only | no | only a person opens a top-level line |
| 23 | GET | `/api/conversations/{conv_id}` | partyline/conversation_routes.py:conversation_detail (registration line 77) | M with `read` | yes | see Set 2 |
| 24 | PUT | `/api/conversations/{conv_id}/topic` | partyline/conversation_routes.py:set_topic (registration line 85) | M with `write` | yes | see Set 2 |
| 25 | PUT | `/api/conversations/{conv_id}/name` | partyline/conversation_routes.py:rename_conversation (registration line 105) | M with `write` | yes | see Set 2 |
| 26 | DELETE | `/api/conversations/archived` | partyline/conversation_routes.py:purge_all_archived (registration line 129) | H only | no | purge of all archived lines; person-only and destructive |
| 27 | POST | `/api/conversations/{conv_id}/restore` | partyline/conversation_routes.py:restore_conversation (registration line 140) | M with `archive` | yes | see Set 2 |
| 28 | DELETE | `/api/conversations/{conv_id}/purge` | partyline/conversation_routes.py:purge_conversation (registration line 155) | M with `archive` | yes | see Set 2 |
| 29 | POST | `/api/conversations/{conv_id}/attachments` | partyline/conversation_routes.py:attach (registration line 168) | M with `attach` | yes | see Set 2 |
| 30 | GET | `/api/docker-relay` | partyline/docker_relay_routes.py:relay_status (registration line 11) | H, or lead (own rows) | yes | see Set 2 |
| 31 | GET | `/api/docker-workloads` | partyline/docker_workload_routes.py:workloads (registration line 21) | H; M for visible rows | yes | see Set 2 |
| 32 | POST | `/api/docker-workloads/{container_id}/stop` | partyline/docker_workload_routes.py:stop (registration line 28) | owning principal | yes | see Set 2 |
| 33 | GET | `/api/docker-gpu` | partyline/docker_workload_routes.py:gpu_state (registration line 32) | any principal | yes | see Set 2 |
| 34 | POST | `/api/docker-gpu/clear` | partyline/docker_workload_routes.py:gpu_clear (registration line 37) | H only | no | GPU admission clear is person-only |
| 35 | PUT | `/api/docker-gpu` | partyline/docker_workload_routes.py:gpu_slots (registration line 43) | H only | no | GPU slot count is person-only |
| 36 | PUT | `/api/conversations/{conv_id}/goal` | partyline/goal.py:put_goal (registration line 62) | M with `assign`, or H | yes | see Set 2 |
| 37 | GET | `/api/heartbeat` | partyline/heartbeat_routes.py:get_heartbeat (registration line 69) | H, or root-lead attachment | yes | see Set 2 |
| 38 | POST | `/api/heartbeat` | partyline/heartbeat_routes.py:enable_heartbeat (registration line 74) | root-lead machine (H refused) | yes | see Set 2 |
| 39 | GET | `/api/heartbeat/status` | partyline/heartbeat_routes.py:get_heartbeat_snapshot (registration line 95) | root-lead attachment | yes | see Set 2 |
| 40 | GET | `/api/heartbeat/snapshots/{digest}` | partyline/heartbeat_routes.py:get_saved_snapshot (registration line 116) | root-lead attachment | yes | see Set 2 |
| 41 | DELETE | `/api/heartbeat` | partyline/heartbeat_routes.py:disable_heartbeat (registration line 130) | root-lead attachment | yes | see Set 2 |
| 42 | GET | `/api/capabilities` | partyline/hierarchy_routes.py:get_capabilities (registration line 65) | any principal | yes | see Set 2 |
| 43 | GET | `/api/conversations/{conv_id}/briefing` | partyline/hierarchy_routes.py:get_briefing (registration line 69) | M with `read`, and lead | yes | see Set 2 |
| 44 | GET | `/api/conversations/{conv_id}/lead` | partyline/hierarchy_routes.py:get_lead (registration line 82) | M with `read`, or H | yes | see Set 2 |
| 45 | POST | `/api/conversations/{conv_id}/lead` | partyline/hierarchy_routes.py:appoint_lead (registration line 88) | H, or M with `appoint_lead` | yes | see Set 2 |
| 46 | PUT | `/api/conversations/{conv_id}/parent` | partyline/hierarchy_routes.py:link_parent (registration line 132) | H only | no | parent links are person-only |
| 47 | POST | `/api/conversations/{conv_id}/children` | partyline/hierarchy_routes.py:create_child (registration line 142) | L with `create_child` | yes | see Set 2 |
| 48 | GET | `/api/conversations/{conv_id}/children` | partyline/hierarchy_routes.py:list_children (registration line 203) | M with `read` | yes | see Set 2 |
| 49 | GET | `/api/conversations/{conv_id}/reports` | partyline/hierarchy_routes.py:list_reports (registration line 211) | L with `read_reports` | yes | see Set 2 |
| 49a | GET | `/api/conversations/{conv_id}/reports/{report_id}` | partyline/hierarchy_routes.py:read_report | L with `read_reports` | yes | see Set 2 |
| 50 | POST | `/api/conversations/{conv_id}/reports` | partyline/hierarchy_routes.py:post_report (registration line 216) | L with `report` (or `notify`) | yes | see Set 2 |
| 51 | POST | `/api/conversations/{conv_id}/reports/{report_id}/ack` | partyline/hierarchy_routes.py:ack_report (registration line 270) | L with `read_reports` | yes | see Set 2 |
| 52 | POST | `/api/hooks/{att_id}/{token}` | partyline/hook_routes.py:hook_event (registration line 115) | attachment token in path | yes | see Set 2 |
| 53 | GET | `/api/hooks/{att_id}/{token}/rebrief` | partyline/hook_routes.py:rebrief (registration line 119) | attachment token in path | yes | see Set 2 |
| 54 | GET | `/api/conversations/{conv_id}/base` | partyline/line_base.py:get_base (registration line 167) | M with `read` | yes | see Set 2 |
| 55 | GET | `/api/conversations/{conv_id}/tip` | partyline/line_base.py:line_tip (registration line 179) | M with `read` | yes | see Set 2 |
| 56 | POST | `/api/conversations/{conv_id}/refresh-base` | partyline/line_base.py:post_refresh_base (registration line 202) | M with `write` | yes | see Set 2 |
| 57 | PUT | `/api/conversations/{conv_id}/gates` | partyline/line_gates.py:put_gates (registration line 151) | H, or M with `assign` | yes | see Set 2 |
| 58 | GET | `/api/conversations/{conv_id}/gates` | partyline/line_gates.py:get_gates_route (registration line 166) | M with `read` | yes | see Set 2 |
| 59 | GET | `/api/conversations/{conv_id}/notes` | partyline/line_notes.py:get_notes (registration line 107) | M with `read` | yes | see Set 2 |
| 60 | PUT | `/api/conversations/{conv_id}/notes` | partyline/line_notes.py:put_notes (registration line 119) | M, by scope | yes | see Set 2 |
| 61 | POST | `/api/conversations/{conv_id}/attachments/close` | partyline/line_process_routes.py:close_line_processes (registration line 235) | M with `close` | yes | see Set 2 |
| 62 | GET | `/api/media/{file_id}/{variant}` | partyline/media_routes.py:serve_media (registration line 200) | H; M with `read`; handed-to process | yes | see Set 2 |
| 63 | POST | `/api/conversations/{conv_id}/files` | partyline/media_routes.py:upload_files (registration line 165) | M with `write` | yes | see Set 2 |
| 64 | POST | `/api/conversations/{conv_id}/images` | partyline/media_routes.py:upload_files (registration line 172) | M with `write` | yes | see Set 2 |
| 65 | GET | `/api/conversations/{conv_id}/files` | partyline/media_routes.py:list_files (registration line 185) | M with `read` | yes | see Set 2 |
| 66 | GET | `/api/conversations/{conv_id}/images` | partyline/media_routes.py:list_files (registration line 192) | M with `read` | yes | see Set 2 |
| 67 | GET | `/api/conversations/{conv_id}/memory-request` | partyline/memory_requests.py:pending (registration line 42) | M with `read` | yes | see Set 2 |
| 68 | POST | `/api/attachments/{att_id}/memory-requests` | partyline/memory_requests.py:file (registration line 47) | M with `attach` | yes | see Set 2 |
| 69 | POST | `/api/memory-requests/{request_id}/approve` | partyline/memory_requests.py:approve (registration line 111) | M with `assign`, not the requester; or H | yes | see Set 2 |
| 70 | DELETE | `/api/memory-requests/{request_id}` | partyline/memory_requests.py:deny (registration line 152) | M with `assign`, not the requester; or H | yes | see Set 2 |
| 71 | GET | `/api/attachments/{att_id}/memory` | partyline/memory_routes.py:get_memory (registration line 31) | M with `read` | yes | see Set 2 |
| 72 | PUT | `/api/attachments/{att_id}/memory` | partyline/memory_routes.py:set_memory (registration line 36) | M with `attach` (self-grant refused); H | yes | see Set 2 |
| 73 | POST | `/api/conversations/{conv_id}/messages/{message_id}/forward` | partyline/message_forward.py:forward_message (registration line 39) | M with `read` (source), `write` (target) | yes | see Set 2 |
| 74 | GET | `/api/conversations/{conv_id}/messages` | partyline/message_routes.py:messages (registration line 44) | M with `read` | yes | see Set 2 |
| 75 | GET | `/api/conversations/{conv_id}/messages/around` | partyline/message_routes.py:messages_around (registration line 67) | M with `read` | yes | see Set 2 |
| 76 | POST | `/api/conversations/{conv_id}/messages` | partyline/message_routes.py:post_message (registration line 98) | M with `write` (own) or `assign` (other) | yes | see Set 2 |
| 77 | POST | `/api/restart-request/operator-approve` | partyline/operator_restart.py:operator_approve (registration line 59) | operator token (loopback) | no | local operator approval with a one-use operator token |
| 78 | GET | `/api/conversations/{conv_id}/pins` | partyline/pin_routes.py:get_pins (registration line 36) | M with `read` | yes | see Set 2 |
| 79 | POST | `/api/conversations/{conv_id}/pins` | partyline/pin_routes.py:post_pin (registration line 41) | H only | no | pins are person-only |
| 80 | PUT | `/api/conversations/{conv_id}/pins/{message_id}` | partyline/pin_routes.py:put_alias (registration line 54) | H only | no | pin aliases are person-only |
| 81 | DELETE | `/api/conversations/{conv_id}/pins/{message_id}` | partyline/pin_routes.py:delete_pin (registration line 69) | H only | no | pin removal is person-only |
| 82 | POST | `/api/conversations/{conv_id}/prereview` | partyline/prereview.py:prereview (registration line 284) | M with `read` | yes | see Set 2 |
| 83 | GET | `/api/presets` | partyline/preset_routes.py:presets (registration line 18) | any authenticated caller | yes | see Set 2 |
| 84 | POST | `/api/presets` | partyline/preset_routes.py:create_preset (registration line 22) | H only | no | instance configuration; person-only |
| 85 | PUT | `/api/presets/{preset_id}` | partyline/preset_routes.py:update_preset (registration line 26) | H only | no | instance configuration; person-only |
| 86 | DELETE | `/api/presets/{preset_id}` | partyline/preset_routes.py:delete_preset (registration line 32) | H only | no | instance configuration; person-only |
| 87 | GET | `/api/conversations/{conv_id}/process-overview` | partyline/process_overview.py:get_process_overview (registration line 98) | M with `read` | yes | see Set 2 |
| 88 | POST | `/api/attachments/{att_id}/signal` | partyline/process_signal.py:signal_descendant (registration line 80) | owning process or line captain | yes | see Set 2 |
| 89 | POST | `/api/messages/{message_id}/reactions` | partyline/reaction_routes.py:post_reaction (registration line 104) | H, or machine on the message's line | yes | see Set 2 |
| 90 | DELETE | `/api/messages/{message_id}/reactions/{emoji}` | partyline/reaction_routes.py:delete_reaction (registration line 108) | H, or machine on the message's line | yes | see Set 2 |
| 91 | POST | `/api/leases` | partyline/resource_leases.py:post_lease (registration line 217) | process (`attachment_id` required) | yes | see Set 2 |
| 92 | GET | `/api/leases` | partyline/resource_leases.py:list_leases (registration line 236) | any authenticated caller | yes | see Set 2 |
| 93 | DELETE | `/api/leases/{name}` | partyline/resource_leases.py:delete_lease (registration line 241) | holding process | yes | see Set 2 |
| 94 | GET | `/api/resources` | partyline/resource_routes.py:resources (registration line 16) | any authenticated caller | yes | see Set 2 |
| 95 | GET | `/api/settings/resources` | partyline/resource_routes.py:get_resource_settings (registration line 22) | H only | no | resource settings are person-only |
| 96 | PUT | `/api/settings/resources` | partyline/resource_routes.py:put_resource_settings (registration line 35) | H only | no | resource settings are person-only |
| 97 | POST | `/api/settings/resources/reset` | partyline/resource_routes.py:reset_resource_settings (registration line 64) | H only | no | resource settings are person-only |
| 98 | POST | `/api/restart-plan/failure` | partyline/restart_report.py:report_restart_failure (registration line 31) | report token (loopback) | no | restart machinery capability, not an agent credential |
| 99 | GET | `/api/restart-request` | partyline/restart_requests.py:pending (registration line 121) | any authenticated caller | yes | see Set 2 |
| 100 | POST | `/api/conversations/{conv_id}/restart-request` | partyline/restart_requests.py:file_request (registration line 126) | M with `assign`, or H | yes | see Set 2 |
| 101 | POST | `/api/restart-request/{request_id}/approve` | partyline/restart_requests.py:approve (registration line 171) | H only | no | restart approval is a person's decision |
| 102 | DELETE | `/api/restart-request/{request_id}` | partyline/restart_requests.py:decline (registration line 205) | H only | no | restart decline is person-only |
| 103 | POST | `/api/conversations/{conv_id}/review-worktrees` | partyline/review_worktrees.py:create (registration line 243) | M with `write` | yes | see Set 2 |
| 104 | GET | `/api/conversations/{conv_id}/review-worktrees` | partyline/review_worktrees.py:index (registration line 265) | M with `read` | yes | see Set 2 |
| 105 | POST | `/api/conversations/{conv_id}/scratch-worktrees` | partyline/scratch_worktrees.py:create (registration line 251) | M with `write` | yes | see Set 2 |
| 106 | GET | `/api/conversations/{conv_id}/scratch-worktrees` | partyline/scratch_worktrees.py:index (registration line 274) | M with `read` | yes | see Set 2 |
| 107 | DELETE | `/api/conversations/{conv_id}/scratch-worktrees/{sha}` | partyline/scratch_worktrees.py:drop (registration line 282) | M with `write` | yes | see Set 2 |
| 108 | GET | `/` | partyline/server.py:index (registration line 243) | anyone (exempt) | yes | see Set 2 |
| 109 | GET | `/api/version` | partyline/server.py:version (registration line 263) | anyone (exempt) | yes | see Set 2 |
| 110 | GET | `/api/running` | partyline/server.py:running (registration line 315) | any authenticated caller (visible lines for M) | yes | see Set 2 |
| 111 | POST | `/api/restart-plan` | partyline/server.py:plan_restart (registration line 327) | loopback with `allows_restart_plan` | yes | see Set 2 |
| 112 | POST | `/api/shutdown` | partyline/server.py:shutdown (registration line 343) | H only (loopback) | no | instance shutdown is a human operator act |
| 113 | GET | `/api/features` | partyline/server.py:list_features (registration line 377) | any authenticated caller | yes | see Set 2 |
| 114 | GET | `/api/fence/status` | partyline/server.py:fence_status (registration line 383) | any authenticated caller | yes | see Set 2 |
| 115 | GET | `/api/adapters` | partyline/server.py:adapters (registration line 389) | any authenticated caller | yes | see Set 2 |
| 116 | POST | `/api/adapters/import` | partyline/server.py:import_adapters (registration line 394) | H only | no | adapter import is human-only instance configuration |
| 117 | POST | `/api/adapters/reload` | partyline/server.py:reload_adapter_definitions (registration line 403) | H only | no | adapter reload is human-only instance configuration |
| 118 | DELETE | `/api/adapters/{adapter_name}` | partyline/server.py:remove_adapter (registration line 412) | H only | no | adapter removal is human-only instance configuration |
| 119 | POST | `/api/attachments/{att_id}/resume` | partyline/server.py:resume_attachment (registration line 458) | M with `attach`, or H | yes | see Set 2 |
| 120 | PATCH | `/api/attachments/{att_id}` | partyline/server.py:edit_attachment (registration line 489) | M with `attach`, stopped attachment | yes | see Set 2 |
| 121 | DELETE | `/api/attachments/{att_id}` | partyline/server.py:detach (registration line 514) | M with `close`, or H | yes | see Set 2 |
| 122 | GET | `/api/attachments/{att_id}/screen` | partyline/server.py:attachment_screen (registration line 524) | M with `read` | yes | see Set 2 |
| 123 | POST | `/api/attachments/{att_id}/keys` | partyline/server.py:attachment_key (registration line 543) | M with `attach` | yes | see Set 2 |
| 124 | WEBSOCKET | `/ws/{conv_id}` | partyline/server.py:ws_endpoint (registration line 556) | H only | no | chat socket is for humans; machine tokens are closed with 4403; agents poll `read_messages` |
| 125 | GET | `/api/settings/global_prose` | partyline/settings_routes.py:get_global_prose (registration line 12) | H only | no | global prose is person-only |
| 126 | PUT | `/api/settings/global_prose` | partyline/settings_routes.py:put_global_prose (registration line 17) | H only | no | global prose is person-only |
| 127 | GET | `/api/conversations/{conv_id}/staffing` | partyline/staffing_routes.py:staffing (registration line 14) | M with `assign` | yes | see Set 2 |
| 128 | WS | `/ws/attachments/{att_id}/terminal` | partyline/terminal_stream.py:terminal_endpoint (registration line 105) | M with `read` on the attachment's line (input needs `attach`) | yes | see Set 2 |
| 129 | POST | `/api/conversations/{conv_id}/tmp/reap` | partyline/tmp_reap_routes.py:reap_tmp (registration line 24) | H, or root captain | yes | see Set 2 |
| 130 | GET | `/api/conversations/{conv_id}/write-set/request` | partyline/write_set_decisions.py:pending (registration line 97) | M with `read` | yes | see Set 2 |
| 131 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/approve` | partyline/write_set_decisions.py:approve (registration line 126) | H, or ancestor captain | yes | see Set 2 |
| 132 | DELETE | `/api/conversations/{conv_id}/write-set/request/{request_id}` | partyline/write_set_decisions.py:decline (registration line 160) | H only | no | decline is person-only |
| 133 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/deny` | partyline/write_set_decisions.py:deny (registration line 175) | H, or ancestor captain | yes | see Set 2 |
| 134 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/withdraw` | partyline/write_set_decisions.py:withdraw (registration line 190) | requesting attachment | yes | see Set 2 |
| 135 | GET | `/api/conversations/{conv_id}/write-set` | partyline/write_set_routes.py:list_write_set (registration line 85) | M with `read` | yes | see Set 2 |
| 136 | POST | `/api/conversations/{conv_id}/write-set` | partyline/write_set_routes.py:grant_or_request_write_set (registration line 92) | H grants; M files a request | yes | see Set 2 |

## Set 2: agent-reachable subset (104 routes)

| # | Method | Path | Caller | Disposition | Reason |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/conversations/{conv_id}/accepts` | M with `read` | **excluded** | accept history is not needed by the tool set; captains record accepts through `accept` (row 2) |
| 2 | POST | `/api/conversations/{conv_id}/accept` | L with `accept` | **op**: captain op `accept` | parent captain records a child SHA; `run_gates` runs gates server-side; reviewer identity comes from the credential |
| 4 | POST | `/api/attachments/{att_id}/fresh` | M with `attach` (human or lead) | **excluded** | process lifecycle; the restart flow, not a routine captain tool |
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
| 21 | GET | `/api/conversations` | H; M for visible lines | **excluded** | no tool lists conversations across the caller's visible lines; `whoami` reports only its own line and children |
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
| 42 | GET | `/api/capabilities` | any principal | **excluded** | MCP authorization preflight and capability refresh use this route; it is not a separately named tool route |
| 43 | GET | `/api/conversations/{conv_id}/briefing` | M with `read`, and lead | **excluded** | captain briefing is not exposed; the role brief reaches the process through the hook path (rows 52-53) |
| 44 | GET | `/api/conversations/{conv_id}/lead` | M with `read`, or H | **excluded** | `whoami` does not call the lead route; its role/action state comes from capability preflight |
| 45 | POST | `/api/conversations/{conv_id}/lead` | H, or M with `appoint_lead` | **op**: captain op `appoint_lead` | lead appointment is a captain op; an empty `attachment_id` clears the lead |
| 47 | POST | `/api/conversations/{conv_id}/children` | L with `create_child` | **op**: captain op `create_child` | refused with live workers and at the depth cap |
| 48 | GET | `/api/conversations/{conv_id}/children` | M with `read` | **tool**: `whoami` | child summaries are fetched by the `whoami` handler |
| 49 | GET | `/api/conversations/{conv_id}/reports` | L with `read_reports` | **tool**: `reports` (list) | reports received from child lines; `limit` (default 50, max 200), `before_id`, `after_id`; newest first unless `after_id` |
| 49a | GET | `/api/conversations/{conv_id}/reports/{report_id}` | L with `read_reports` | **tool**: `reports` (get) | one report; 404 for another parent's report |
| 50 | POST | `/api/conversations/{conv_id}/reports` | L with `report` (or `notify`) | **tool**: `reports` (post; `notify` flag) | captain reports to its parent |
| 51 | POST | `/api/conversations/{conv_id}/reports/{report_id}/ack` | L with `read_reports` | **op**: captain op `ack_report` | acknowledges a child report; the op also accepts a captained child line's conv_id and resolves it to the owning (caller's) line |
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
| 63 | POST | `/api/conversations/{conv_id}/files` | M with `upload` | **tools**: `upload_file`, `upload_3d_model`, `upload_files` | sends one file, one glTF/GLB model, or an ordered batch of 1–6 files through the `/files` route |
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
| 87 | GET | `/api/conversations/{conv_id}/process-overview` | M with `read` | **op**: captain op `process_overview` | live phase and RSS for the line's attachments; bounded real/mirror branch visibility for every task workspace |
| 88 | POST | `/api/attachments/{att_id}/signal` | owning process or line captain | **excluded** | destructive pid signal; pids do not resolve through the host namespace from inside the fence |
| 89 | POST | `/api/messages/{message_id}/reactions` | H, or machine on the message's line | **tool**: `react` (POST toggles the reaction) | own line only; the reactor's line must be the message's line |
| 90 | DELETE | `/api/messages/{message_id}/reactions/{emoji}` | H, or machine on the message's line | **tool**: `react` (DELETE removes the reaction) | own line only; same rule as row 89 |
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
| 120 | PATCH | `/api/attachments/{att_id}` | M with `attach`, stopped attachment | **excluded** | changes a stopped process's command |
| 121 | DELETE | `/api/attachments/{att_id}` | M with `close`, or H | **op**: captain op `detach_worker` | stops one worker on the target line; server stop rules apply; the worker's token stops resolving (design.md section 7), and the caller's own token is unaffected |
| 122 | GET | `/api/attachments/{att_id}/screen` | M with `read` | **excluded** | screen text is never speech (AGENTS.md); debugging only |
| 123 | POST | `/api/attachments/{att_id}/keys` | M with `attach` | **excluded** | raw keystrokes into another process's PTY |
| 127 | GET | `/api/conversations/{conv_id}/staffing` | M with `assign` | **op**: captain op `staffing` | who works the line |
| 128 | WS | `/ws/attachments/{att_id}/terminal` | M with `read` on the attachment's line (input needs `attach`) | **excluded** | raw PTY stream, not structured speech; the watch-any-attachment gap is fixed on this branch by bf8573a (per-line `read` and `attach` checks, rechecked while open); MCP still excludes it |
| 129 | POST | `/api/conversations/{conv_id}/tmp/reap` | H, or root captain | **excluded** | destructive temp reap; root captain or person |
| 130 | GET | `/api/conversations/{conv_id}/write-set/request` | M with `read` | **op**: captain op `write_set_requests` (read-only) | lists pending requests (this row) and current grants (row 135) on a line the caller may read, so `decide_write_set` callers can find a request id |
| 131 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/approve` | H, or ancestor captain | **op**: captain op `decide_write_set` (approve) | ancestor captain only inside its own grants or writable checkout; the route enforces that rule |
| 133 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/deny` | H, or ancestor captain | **op**: captain op `decide_write_set` (deny; reason required) | ancestor captain only inside its own grants or writable checkout; the route enforces that rule |
| 134 | POST | `/api/conversations/{conv_id}/write-set/request/{request_id}/withdraw` | requesting attachment | **op**: captain op `decide_write_set` (withdraw) | withdraw is the requester's act; captain ops need a live lead, so a worker withdraws on the route |
| 135 | GET | `/api/conversations/{conv_id}/write-set` | M with `read` | **op**: captain op `write_set_requests` (read-only) | lists current grants on a line the caller may read; pending requests are row 130 |
| 136 | POST | `/api/conversations/{conv_id}/write-set` | H grants; M files a request | **op**: captain op `request_write_set` (lead) | a person or ancestor captain decides; worker requests keep the fence message's direct POST; Docker mode is person-only (403) |

## Implemented names and the routes they reach

| Name | Kind | Routes |
| --- | --- | --- |
| `whoami` | core tool | 23, 48 |
| `guide` | core tool | 16, 17, 18 |
| `read_messages` | core tool | 74, 75 |
| `notes` | core tool | 59, 60 |
| `goal` | core tool | 23, 36 |
| `post_message` | core tool | 76 |
| `upload_file` | core tool | 63 |
| `upload_3d_model` | core tool | 63 |
| `upload_files` | core tool | 63 |
| `get_media` | core tool | 62 |
| `reports` | core tool; captain fallback operation | 49, 49a, 50 |
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

1. **Process lifecycle (rows 4, 111, 120).** Excluded from MCP. Row 111 is loopback-only; rows 4 and 120 are gated by `attach`. Process lifecycle is not a captain tool.
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

## Orchestrator additions

These entries extend both inventory sets above. Registration handlers are in
`orchestrator_routes.orchestrator_router` and `settings_routes.settings_router`.

| Method | Path | Handler | Caller | Agent-reachable | MCP disposition |
| --- | --- | --- | --- | --- | --- |
| PUT | `/api/conversations/{conv_id}/captain-style` | `captain_style` | H, root line only | no | excluded: human chooses captain style and default review policy |
| POST | `/api/conversations/{conv_id}/tasks` | `create` | H or orchestrator root captain | yes | tool: `create_task` |
| GET | `/api/conversations/{conv_id}/tasks` | `listing` | H or orchestrator root captain | yes | tool: `tasks`; includes bounded per-workspace real/mirror tips and unaccepted commits |
| GET | `/api/conversations/{conv_id}/task` | `detail` | M with `read` | yes | guide: current structured task state, including after compaction |
| POST | `/api/conversations/{conv_id}/blocked` | `block` | exact task implementer | yes | tool: `blocked` |
| POST | `/api/conversations/{conv_id}/waiting` | `waiting` | exact task implementer | yes | tool: `waiting`; declares a long wait (`reason`, `seconds` 60–3600) that defers the stall reminder and the stall report |
| POST | `/api/conversations/{conv_id}/request-review` | `review` | exact task implementer | yes | tool: `request_review`; `sha` or `repositories: [{repository, sha}]` (1–8, not both) |
| POST | `/api/conversations/{conv_id}/review-verdict` | `verdict` | exact task reviewer, or root captain with `override=true` (staffed reviews) or under captain policy | yes | tool: `review_verdict`; override supersedes the reviewer (told once), records `overridden_by`, refused with 409 when no review is open or the task is settled |
| POST | `/api/conversations/{conv_id}/task/reopen` | `reopen` | H, or root captain | yes | tool: `reopen_task`; returns an approved/done task to implementing (409 otherwise) |
| POST | `/api/conversations/{conv_id}/task/message` | `message` | H, or root captain | yes | tool: `message_task`; private wake-up message to the task's live implementer or reviewer (409 otherwise) |
| POST | `/api/conversations/{conv_id}/task/share-ref` | `share_ref` | H, or root captain | yes | captain op: `share_ref`; publish `refs/partyline/shared/<name>` in a live task's mirror, then privately notify its implementer |
| POST | `/api/conversations/{conv_id}/task/resume` | `resume` | implementer, H, or root captain | yes | tool: `resume_work`; clears a blocked task; the root/person form requires `note` and wakes the implementer with it (409 unless blocked) |
| POST | `/api/conversations/{conv_id}/task/implementer` | `implementer` | H, or root captain | yes | tool: `restart_implementer`; relaunches a detached implementer of an implementing, idle or blocked task (409 if running) |
| POST | `/api/conversations/{conv_id}/task/reviewer` | `reviewer` | H, or root captain | yes | tool: `restart_reviewer`; revives a dead reviewer of a task in review |
| GET | `/api/settings/auto_clean_task_history` | `get_auto_clean` | H only | no | excluded: global history-retention setting |
| PUT | `/api/settings/auto_clean_task_history` | `put_auto_clean` | H only | no | excluded: human opt-in to task history cleanup |

Existing archive/retire operations refuse machine requests for task lines, including
root-captain `force_discard` and recursive retirement containing task descendants.
Task attachment creation is server-owned; shared-branch overrides do not bypass it.
