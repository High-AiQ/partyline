# Polling audit — 2026-11-11

The Phase 1 inventory was posted to the no-polling-audit line before edits.
These are starting-checkout locations (11429ed); grouped locations share a wait.
The scope is `partyline/`, `partyline_helper/`, `frontend/src`, and production
scripts, excluding tests, generated static files and other worktrees.

| Category | Starting location | What was waiting; disposition |
| --- | --- | --- |
| (a) | `partyline/adapters/jsonl_receipts.py:204,249` | Claim marker, append, partial record; native directory notifications, reopen on unlink/rotation |
| (a) | `partyline/adapters/bundled/claude/adapter.py:221` | Claimed transcript discovery; filesystem event or single warning deadline |
| (a) | `partyline/adapters/bundled/codex/adapter.py:216,222` | Rollout discovery/readiness resubmission; native file event; repeated resubmissions removed |
| (a) | `partyline/adapters/bundled/codex/thread_history.py:129,137,176` | History database creation and mutation; native file notifications including WAL |
| (a) | `partyline/adapters/bundled/cursor/adapter.py:183,188,194,213,237,256,286` | Session discovery, transcript creation, append, rewrite and rotation; native directory events |
| (a) | `partyline/adapters/bundled/deepseek/adapter.py:192,247,251` | Session-log discovery and partial/complete append; native file events and shared rotating tail |
| (a) | `partyline/adapters/bundled/grok/adapter.py:183,224`, `grok/tail.py` via `_poll`, `grok/resume.py:73` | Discovery, append, replacement and stable snapshot; native notifications and a quiet deadline |
| (a) | `partyline/adapters/bundled/hermes/adapter.py:170,181,211` | Database messages, TUI startup and session discovery; database-file or PTY-output notifications |
| (a) | `partyline/adapters/bundled/muse/adapter.py:229,235,257` | Discovery and transcript appends; native events and shared rotating tail |
| (a) | `partyline/adapters/bundled/opencode/adapter.py:147,214,270`, `opencode/v2.py:265,275` | Session/database/provider-log changes; native file notifications and PTY events |
| (a) | `partyline/adapters/bundled/pi/adapter.py:49,62` | Discovery/readiness resubmission; native file events, repeated resubmissions removed |
| (a) | `partyline/adapters/bundled/raw/adapter.py:86` | Output quiescence and process exit; output/exit event plus one quiet deadline |
| (a) | `partyline/adapters/startup_prompt.py:85` | Startup dialog changes; PTY-output, claim or exit events |
| (a) | `partyline/adapters/process_shutdown.py:34–38`, `partyline/line_process_routes.py:55` | Stop confirmation; native child wait and one final grace deadline rather than spin checks |
| (a) | `partyline/windows_console.py:122–137` | Exit and ConPTY output; blocking OS wait/read off the asyncio loop |
| (a) | `partyline/docker_bridge.py:84`, `docker_bridge_client.py:101` | Owner exit/socket readiness; native exit wait and explicit READY pipe frame |
| (a) | `partyline/runtime_lock.py:60,75` | Ownership release; OS blocking file lock with cancellation cleanup |
| (a) | `partyline/idempotent_posts.py:80` | Concurrent keyed POST completion; cross-loop future notifications |
| (a) | `partyline/restart_lease.py:40` | Ownership becoming available; filesystem event or persisted lease-expiry deadline |
| (a) | `partyline/terminal_stream.py:51` | Quiet-terminal authorization; SQL mutations plus JWT-expiry deadline |
| (a) | `partyline/line_resource_routes.py:69` | Resource grants; SQL mutations and persisted notification recovery deadlines |
| (a) | `partyline/captain_handover.py:277` | Offer expiry; SQL changes and next offered-at deadline |
| (a) | `partyline/captain_handover_completion.py:201` | Confirmation timeout, detach and retention recovery; mutation/deadline wakeups |
| (a) | `partyline/orchestrator_cleanup.py:102` | Task integration and waiting deadlines; SQL mutations, Git metadata notifications and persisted deadlines |
| (a) | `partyline/heartbeat_scheduler.py:247` | Reminder due dates/eligibility; configuration/delivery changes and next-due deadline |
| (a), decision pending | `partyline/memory_sampler.py:267`, `docker_workloads.py:116` | Exact resource gauges; see below |
| (a), decision pending | `partyline/event_loop_lag.py:27,47`, `loop_watchdog.py:51` | Continuous loop-responsiveness measurements; see below |
| (a) | `partyline/mcp/server.py:93` | Watcher initialization; blocking Event, set on shutdown too |
| (a) | `partyline_helper/stopping.py:34,49` | Stop-file creation/helper exit; filesystem notification and native process wait |
| (a) | `partyline_helper/links.py:82` | Old helper releasing run lock; native owner-exit notification followed by one lock attempt |
| (a) | `partyline_helper/terminal.py:45` | Terminal input; notifying queue and one consent deadline |
| (a) | `partyline_helper/uia_process.py:36–43` | UIA readiness/exit; explicit READY pipe frame, OS process wait and separate startup/walk deadlines |
| (a) | `partyline_helper/dialog_proc.py:90` | Parent exit; native process wait |
| (a) | `partyline_helper/control.py:184` | Physical pointer movement; native mouse listener |
| (a) | `partyline_helper/uia_access.py:186`, `window_shares.py:148` | Window destruction/desktop changes; native WinEvent hooks |
| (a) | `frontend/src/state/resources.svelte.ts:19` | Delayed resource refetch; account/line socket snapshot and mutation push |
| (a) | `frontend/src/state/voice-presets.svelte.ts:57`, `components/settings/sections/VoiceSection.svelte:68` | Recognizer retry-fetch; complete socket snapshot on connect/reconnect and on changes |
| (a), sibling-owned | `frontend/src/components/rail/ConversationList.svelte:51`, `components/chat/ScreenControls.svelte:54` | Screen indicators; no-screen-polling owns both files and screen routes |

A second pass found three one-second timeout loops: `jsonl_receipts.py:142`,
`cursor/wakes.py:133`, and `opencode/wakes.py:100`. They now await a receipt
or explicit process-exit/stop notification without a timer.

## Retained categories

- **(b), scheduled one-shot:** `goal_stall.py:25,154`, `return_path.py:243`,
  `runtime_delivery_credit.py:61,145`, audit flushes in `screen_control.py:269`
  and `local_tools.py:252`, `screen_elements.py:77`, transcriber idle unload,
  walkthrough expiry, restart exit, adapter startup/paste/action pacing and
  wake-settlement grace periods. Helper consent guards, picker/dialog expiry,
  action/drag pacing and tools idle expiry are deadlines too.
- **(c), protocol keepalive:** helper `client.py:199` sends a websocket ping
  through otherwise idle proxies and enforces its heartbeat deadline. Helper
  `tools.py:227` and `restart_lease.py:45` renew an existing ownership lease;
  these are protocol renewal messages, not requests to discover changed state.
- **(d), local UI ticker:** `WorkingBadge.svelte:22`, `clock.svelte.ts:14`,
  `mic-meter.ts:59`, `voice-recorder.ts:140`. They make no network request.
  Other browser deadlines clear highlights/feedback, dismiss notices, cap
  recordings or defer a DOM action; they are (b).
- **(e), bounded backoff retry:** chat/account and terminal websocket
  reconnects; helper transport reconnect; MCP capability-request recovery;
  foreground raising after a failed native attempt. Success ends retries.
  Failed resource health commands also retry with a capped five-second delay
  until success; failed handover detach/reap operations also retain bounded
  failure recovery. Healthy resources are never checked on a timer.
  Recognizer retry-fetches are explicitly (a), per Greg's follow-up ruling.

`MCPServer._watch_step` uses an event-driven server request; its HTTP timeout
only renews an idle streaming request. It does not scan state on a timer.
Single `poll()` calls used to answer an event-driven liveness question are
not process spin-waits. `scripts/uishot.py:255–262` is screenshot development
tooling, not a production script. No production shell polling was found.

## Decisions reserved for Greg

These remain visible rather than being relabeled as allowed timers:

1. **Exact memory/Docker gauges:** `/proc`, cgroup `memory.current` and the
   current process-table APIs provide snapshots. Pressure/limit/exit events do
   not signal every change to the exact working-set, file-cache, host-free or
   Docker-memory numbers currently displayed and used by the advisory warning
   policy. Replacing their sampler requires choosing a different telemetry and
   warning contract, rather than pretending pressure is equivalent to usage.
2. **Loop-lag diagnostics:** the existing monitor and watchdog actively measure
   responsiveness against periodic probes. There is no passive event for every
   otherwise-idle loop-lag sample. Replacing/removing this diagnostic requires
   a decision about which measurements to retain.
3. **Windows screen capture — resolved:** Windows shares now use a
   `Windows.Graphics.Capture` window item selected by HWND. The frame-arrived
   callback forwards changed frames and drops bursts above the upload cap; it
   never samples images or schedules a capture timer. The capture item closing
   stops and revokes the share. macOS and Linux capture are explicitly
   unsupported pending ScreenCaptureKit and XDG desktop-portal backends.

The guard pins the exact existing memory and lag sleep calls; screen capture
now reacts to Windows Graphics Capture events, and the sibling-owned screen
intervals were removed by 969006e8. It rejects additional calls; these audit
exceptions are not (b)–(e) approvals. Windows-only native hook code is isolated
from ordinary tests; hook consumers are exercised with explicit fake events.

## Recovery checks from review

Failed resource-grant and task-report delivery arms bounded failure backoff;
success clears it. Persisted in-flight report claims wake maintenance at their
lease expiry after restart, and resource claims are reclaimable at the exact
expiry boundary. Task cleanup watches the Git metadata for every reviewed and
registered workspace repository, and re-registers on workspace changes. Fake
clock/event tests prove each recovery without unrelated database mutations.

## Native watch scope and idle behavior

`FileEvents` no longer uses watchfiles. Linux uses one nonblocking inotify fd
registered with `loop.add_reader`; macOS uses a readable kqueue plus directory
and exact-file vnode fds (directory events alone miss child-file appends).
Windows arms a non-recursive overlapped `ReadDirectoryChangesW` before scanning,
then blocks on its completion event. A shallow parent guard observes renames
of a watched directory itself, which ReadDirectoryChangesW does not report.
`CancelIoEx` signals completion on shutdown;
the thread is joined before its handles and OVERLAPPED storage are released.
There are no step timers, debounce loops, stop-event checks on a timer, or idle
callbacks. Native descriptors/readers are removed directly on Unix shutdown.

Literal files watch only their containing directory, including SQLite's WAL,
SHM and journal names; literal directories watch their own direct entries and
their parent for replacement. Missing prefixes watch the deepest existing
ancestor **non-recursively** and advance as native creation events arrive.
Notifications are armed before scanning each level. Recursive `**` patterns are
rejected. Explicit patterns have finite depth and a hard per-context limit of
4,096 registrations; exceeding the limit or native capacity fails explicitly
and closes partial registrations, without a recursive or timer fallback.

| Caller | Declared paths and reason |
| --- | --- |
| Shared JSONL tail | The claimed transcript file; its directory observes append, unlink, rename and recreation |
| Restart lease | The database file and its SQLite sidecars; a DB directly in the home directory needs one shallow watch on Linux, regardless of nested projects |
| Helper stop | `run.stop`; only its containing lock directory matters |
| Retained-job recovery | `.pending-reaps` and its direct manifest entries; retained directory contents are not traversed |
| Task cleanup | Each integration Git metadata directory's direct entries, `packed-refs`, symbolic HEAD targets and linked-worktree HEADs; `worktrees` entries trigger re-registration. Object stores, working files, node_modules and virtual environments are not traversed |
| Claude discovery | The attachment's pinned transcript glob and `~/.claude/projects/*/*.jsonl`; only the one project-directory level is observed for the claim-bearing structured log |
| Codex discovery | The private attachment home's `sessions/*/*/*/rollout-*.jsonl` (year/month/day) and `thread_history_1.sqlite`; configuration and unrelated home directories are not traversed |
| Cursor discovery | This cwd's `chats/<cwd-hash>/*/*` and `projects/<cwd-slug>/agent-transcripts/*/*.jsonl`; other Cursor projects and caches are not traversed |
| DeepSeek discovery | Its session root's `*/*/session.v*.jsonl*` (project/session); includes compressed-log creation so the existing diagnostic still reacts |
| Grok discovery | `~/.grok/sessions/*/<pinned-UUID>/chat_history.jsonl`; one date level and the pinned session |
| Hermes / OpenCode | Their exact SQLite file and sidecars; OpenCode v2 additionally watches its exact provider log |
| Muse discovery | Its private session root's `*/*/*/*/session.jsonl` (year/month/day/session); bounded history directories only |
| Pi discovery | The attachment's own session directory, direct JSONL entries only |
| Antigravity discovery | The attachment's exact hook log and `brain/*/.system_generated/logs/transcript.jsonl`; only the documented conversation/log levels |

Native and injected-source tests prove constant watch count beside 100 nested
project trees, missing-parent re-arming, rotation/unlink recovery, bounded
pattern depth, explicit overflow failure, idle virtual hours without reads,
macOS append observation, and Windows completion/cancellation without timeouts.
