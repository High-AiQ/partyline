# Blender Python relay: design (phase 1)

2026-11-07. Design plus a throwaway spike (`experiments/blender-relay-spike/spike.py`); nothing is built.
Goal: an agent drives Blender by running Python inside it, sees results through screen share and renders, and
a decision model (OpenAI Decisions, `docs/research/`) tells it which renders need a closer look. Partyline
stays client-agnostic: Blender is one *local tool*; the wire format and consent machinery name no application.

**Non-negotiables (Greg):** no unattended or pre-granted control. Every session needs a fresh local consent
dialog on the person's computer, a visible indicator, and a kill switch that works without the server.
Grants live in memory only: a restart of the server, helper or Blender ends them.

## 1. What blender-mcp does, and what to copy

Source: `github.com/ahujasid/blender-mcp` (README plus a read of `addon.py`, 7,264 lines). Licence **MIT**.
The other projects (Blend AI, a FastAPI "ThreadSafeExecutor" server, a Rust/PyO3 server, a JSON-RPC one) were
read as README summaries only, not audited; all use the same shape, so the pattern is settled.

| Question | blender-mcp | Verdict |
| --- | --- | --- |
| Listener | `socket` server on a daemon thread, one thread per client. Handlers push `(command, client)` onto a `queue.Queue`; **one** `bpy.app.timers` callback registered once from the main thread drains it every 50 ms and runs all `bpy` code there. Its own comments record that registering a timer per command from a client thread lost callbacks. | **Copy** (queue plus single drain timer; no `bpy` off the main thread). |
| Framing | Raw TCP, JSON `{type, params}`; the reader appends 8 KiB chunks and retries `json.loads` until it parses. | **Avoid.** Use HTTP/1.1 (stdlib `http.server`): length framing, status codes, an `Authorization` header. |
| Commands | `execute_code`, `get_scene_info`, `get_object_info`, `get_viewport_screenshot`, `look` (viewport, camera, multi-angle, strips), node/API introspection, asset search and AI-3D-generation integrations, telemetry controls. | **Copy** exec, scene info, screenshot. **Skip** asset and generation integrations, telemetry, node introspection (an agent can `exec` it). |
| Results | `{"status":"success","result":…}` or `{"status":"error","message":…}`. `execute_code` uses a fresh `{"bpy": bpy}` namespace per call, captures stdout with `redirect_stdout`, and returns a JSON string of exception type, message and traceback. | **Copy** the structured error. **Change:** persistent namespace per session; hard output caps. |
| Screenshots | Offscreen `gpu.types.GPUOffScreen.draw_view3d` (their comment: the window grab `screen.screenshot_area` is black when Blender is not composited in the foreground), window grab as fallback. | **Copy** offscreen, with attribution (MIT permits). Untested in the spike: needs a GPU. |
| Timeouts | Client-side socket timeout only. No add-on-side deadline or cancel: a runaway script freezes Blender. | **Avoid.** See section 4. |
| Security | README: `execute_code` is "potentially dangerous"; **no authentication or encryption**; localhost by default, optional remote bind. "Safe mode" (`BLENDER_MCP_SAFE_MODE=1`) lexically screens scripts. Opt-in telemetry of prompts, code and screenshots. | **Avoid all of it.** A lexical filter is not a sandbox; we do not ship a pseudo-sandbox. Security is consent, a secret, a lease, audit and a kill switch. |

**Do not vendor.** MIT allows it, but it is one 7k-line file mixing a socket server with asset integrations
and telemetry, with none of what we need (secret, lease, cancel, caps). Ours is about 500 lines; we take the
patterns above and credit the project in the add-on README.

## 2. Spike: what it settled

Blender 5.2.2 (Python 3.13) on Linux under Xvfb, `--python spike.py`. HTTP server on a thread, bearer secret,
queue drained by a timer, `sys.settrace` deadline around `exec`, a render inside a timer callback.

| Question | Result |
| --- | --- |
| Queue plus one timer drain, stdlib HTTP, loopback, secret | Works. Wrong secret gets 401 before any `bpy` access. |
| Error text | Traceback is returned (tail kept); output beyond the cap is cut and flagged `truncated`. |
| Cancel a Python loop (`while True: pass`, and a sleeping loop) with a 1 s deadline | **Works**: cancelled in 1.0 to 1.05 s, Blender stays alive and answers the next call. |
| Cancel one long C call (`sum(range(10**9))`) | **Not interruptible**: the deadline fired only after the call finished (7.7 s). The trace hook runs between Python lines only. |
| `bpy.ops.render.render(write_still=True)` from a timer callback | **Works** (Workbench, 256 px in 0.06 s, 512 px PNG 164 KB). Not interruptible either. |

Consequences: (1) cancel is **cooperative**; the only hard stop for C-level work is closing Blender, which
loses unsaved work, so the relay never does that itself. (2) It must not queue work behind a call that
overran: the session goes `busy` until the add-on reports idle. (3) Renders are bounded by clamped
resolution and samples, not a deadline. (4) Unverified: Windows, a real GPU (offscreen capture), render
cancel, UI responsiveness while a call runs; phase (a) and (b) have an acceptance test for each.

## 3. Architecture

```
agent (MCP tools, partyline/mcp/tools_blender.py)
  -> server  POST /api/conversations/{id}/local-tools/...   LocalTools hub: grants, limits, audit
  -> helper websocket (existing, hello advertises tools: 1)  tool_call / tool_result (+ binary)
  -> helper  partyline_helper/tools*.py: consent, lease, local audit, kill switch
  -> Blender add-on, http://127.0.0.1:<port>/  Authorization: Bearer <per-install secret>
```

The helper is the **only** component that talks to the add-on; the server never sees the secret or the port.

**Add-on discovery and secret.** On enable, the add-on generates a random 32-byte secret once, binds
`127.0.0.1` on an ephemeral port, and writes `%LOCALAPPDATA%\Partyline\blender-relay.json`
(`{port, secret, pid, blender, file}`, user-only ACL, rewritten at every start). The helper reads it per call,
so a Blender restart needs no re-pairing. Anything running as that user can read it: the same trust level as
the helper's own `helper.json` token, stated in `docs/security.md`. The add-on rejects a wrong secret
(constant-time), any `Origin` header and any `Host` other than `127.0.0.1:<port>` (browser and DNS-rebinding
defence), and sends no CORS headers.

**Add-on lease (second line of defence).** The add-on runs commands only inside a *session* the helper
opened (`POST /session` with a fresh id). The helper renews it every 5 s; the add-on ends the session after
15 s without a renewal and shows a status-bar banner "Agent <name> is connected" with an **End** button.
If the helper crashes, is killed or loses its websocket, the add-on fails closed on its own. One session at
a time; a second `POST /session` while one is live gets 409.

**Wire messages** (new, `tools: 1` in the helper hello like `control: 1`; JSON text, media results followed by
one binary message as frames are today):

| Direction | Message | Fields |
| --- | --- | --- |
| server to helper | `tools_request` | `session_id, tool, requested_by, line_name, checker?` |
| helper to server | `tools_granted` / `tools_revoked` | `session_id, checker, info{blender, file} / reason` |
| server to helper | `tool_call` | `session_id, call_id, op, args, timeout` |
| helper to server | `tool_result` | `call_id, ok, result \| error, truncated, started, mime?` |
| server to helper | `tool_cancel`, `tools_revoked` | `call_id` / `session_id, reason` |

`checker?` is true only when the agent asked for it (`blender_request(checker=true)`); that alone makes the dialog
offer the render-check checkbox. `tools_granted.checker` is what the person ticked, nothing else.

## 4. Consent, kill switch, audit, limits

**Consent.** `blender_request` (an MCP tool, like `screen_control_request`) returns at once; the helper shows
the existing native dialog (`consent_dialog.confirm`, 60 s, silence declines, foreground bring-up) reading:
"*<agent>* (line *<line>*) asks to run Python in Blender (*<file name>*). It can read and change every open
scene and run any Python with your account's rights, including files and the network. Save your work first.
Ctrl+Alt+Esc or the tray menu ends it. Allow?" and, when the server has a checker, a separate checkbox,
**unchecked by default**: "Also let Partyline send renders from this session to OpenAI to check them." Python
can be allowed without it. The agent is @mentioned with the answer, as for control.
**The checker scope belongs to the local grant.** It exists only when `blender_request(checker=true)` was asked
and the box was ticked. Adding it to a live exec-only session needs a new request and a fresh dialog showing
only that box; decline or silence leaves the session as it was. Revoke, expiry or the tray item "Stop render
checks" removes it. The helper marks each render it returns `checkable` from its *current* grant, and the
server stores that mark with the media.
There is **no** `--allow-...-without-prompt` flag for tools; the helper refuses a `tool_call` unless it holds
a live local grant, so a compromised or buggy server cannot forge one. A grant is bound to the requesting
agent (others get "held by X") and to one session: it is not tied to a screen share (a share is advisable so
the agent can look at the UI, but Python needs none), and it ends on any revoke below.

**Revocation (all take effect before queued calls run; each cancels a running call cooperatively).**

| Source | How |
| --- | --- |
| Tray | New menu item "End agent session" and **Quit** (extends `Status`/`Tray`; new state `tools`, violet). |
| Hotkey | **Ctrl+Alt+Esc**, the existing control kill switch: `Inputs.listen` also starts for a tools session. |
| In Blender | The banner's End button (add-on closes its session; the helper sees it and tells the server). |
| Partyline UI | A Revoke button beside the control one (`DELETE /api/local-tools/sessions/{id}`). |
| Automatic | Helper disconnect, server restart, add-on lease expiry, 15 min without a call. |

After a *local* revoke (tray, hotkey, End) the agent may not re-ask for 10 minutes; after that a new request
shows a new dialog (boxes unchecked again).

**Undo.** Each `exec` runs after `bpy.ops.ed.undo_push(message="agent <sha8>")`, so one Ctrl+Z in Blender
steps back over a script (file writes are not undone). At session start the add-on saves a copy of the open
file (`save_as_mainfile(copy=True)`, `<name>.agent-backup.blend`); an unsaved scene has none, and the dialog
says so.

**Audit** (every script, always). Two copies, so neither side can edit the other's:
1. *Helper, authoritative:* `%LOCALAPPDATA%\Partyline\tools-audit.jsonl`, appended before the script is sent
   to Blender: time, session, agent, op, SHA-256 and byte length of the code, the full code (up to 64 KB),
   outcome, and the previous line's hash (a hash chain, as the server's control audit does).
2. *Server:* table `local_tool_audit` (new idempotent entry in `partyline/db_schema.py`) with the same chain,
   the full code, and the outcome. A system note is posted to the line in batches like "Agent control audit",
   showing first line, size and hash per script, plus "[audit sha256: …]". Notes wake no process.

**Limits** (all env-tunable like `ControlLimits`): code 64 KB; one call in flight; 60 calls per minute;
500 per session; `exec` default 20 s, max 120 s; render default 60 s, max 180 s. Results are cut to 16 KB
(head 12 KB plus tail 4 KB, `truncated: true`); tracebacks 4 KB; scene info 16 KB with an explicit "more"
cursor; images re-encoded to at most 3.5 MiB and 2048 px long edge (the websocket ceiling is 4 MiB).

**Timeouts and cancel.** The server waits `timeout + 5 s`. The add-on installs the spike's `settrace` deadline,
so Python loops stop within about a second. On expiry or `blender_cancel` the helper calls `POST /cancel`; a
call stuck in C cannot be stopped, so the agent gets "timed out; Blender is still busy", the session goes
`busy` (no new calls until the add-on reports idle) and the chat says so; the person decides whether to wait
or close Blender. Renders are bounded by clamping long edge (2048), samples (64) and frames (1).

## 5. MCP tools (agent view)

New module `partyline/mcp/tools_blender.py`, listed like `tools_control` (only with write access); the
server enforces grants, the tool list does not hide them.

| Tool | Arguments | Returns |
| --- | --- | --- |
| `blender_request` | `checker?` (default false) | pending; @mention on answer. Asks for a session, or, on a live one, only for the extra scope |
| `blender_exec` | `code`, `timeout_s?` | `{ok, stdout, result?, error{type,message,traceback}, truncated, undo}`. Namespace persists for the session; the last expression value is returned. |
| `blender_scene_info` | `detail?` (`summary` \| `objects` \| `object` + `name`), `project_to_camera?` | compact JSON: units, frame, camera, objects with name, type, parent, collection, world bbox, and (opt.) camera-space bbox and `in_frame` |
| `blender_render` | `camera?`, `width`, `height`, `engine?` (`workbench` default, `eevee`), `samples?`, `frame?`, `reference?` (line media id), `overlay_opacity?` (0..1, default 0.5) | media reference (same shape as `screen_frame`; fetch with `get_media`) plus the settings actually used (clamps are reported, never silent) |
| `blender_screenshot` | `max_size?` | media of the 3D viewport via offscreen capture; for the whole window use `screen_frame` |
| `blender_cancel` | none | cooperative cancel result |
| `render_check` (phase c) | see section 6 | verdicts, flagged media only |

**Reference overlay.** `blender_render(reference="<line media id>", overlay_opacity=0.5)`
stores the composited overlay as its returned media. The server resolves only media on that
line, reads at most 20 MiB, converts to PNG and sends `reference: {id, png_base64}` through
the existing helper transport (at most 700 KiB decoded). Base64 plus the call envelope must
fit the helper's 1,000,000-byte receive limit and the add-on's 3 MiB HTTP body limit; the full message is checked before sending.
This conservative cap supports installed helpers with the 1 MB limit without an update.
Each reference side must be 16..2048 pixels; oversized references are refused, never resized.
The add-on renders with transparent film at the reference's exact dimensions, with square
pixels and no render border. The scene's camera-frame aspect, or explicit width/height,
must match within 0.5%; otherwise it refuses. The default frame uses the unclamped scene
resolution, percentage and pixel aspect; explicit dimensions describe square pixels. All
overrides are temporary. Samples/frame
clamps, cancellation, deadlines and discarded late artifacts retain the ordinary render path.
The reusable add-on `overlay.render_overlay` also works in background scripts; its optional
`proxies` selection draws flat translucent colours and outlines and restores visibility and
colours afterwards. Composition uses bpy images and numpy, with no Pillow dependency in Blender.

Errors are plain strings the agent can act on ("not granted; call blender_request", "Blender is busy").

## 6. Render verification

Flow: `blender_render` for N cameras or variants, then one `render_check` call, then the agent fetches **only
flagged** media with `get_media`. Unflagged renders are returned as ids with `verdict: pass` and are never
shown to the agent unless it asks.

**Deterministic first, as heuristics.** The add-on measures what geometry can: `world_to_camera_view` for
frame margins, `mathutils.bvhtree` mesh overlap for clipping, a downward ray cast for floating. These are
heuristics with stated assumptions, reported with the tolerance used (`blender_scene_info(project_to_camera)`),
and fed to the checker as evidence (the research doc's rule: cheap deterministic checks before paying a model).
Assumptions: the evaluated (modifier-applied) mesh is used; "off-frame" means outside the camera frustum by a
margin; "floating" means gravity and one named support, with the gap above a tolerance. Touching faces, thin
or open meshes, intentional interpenetration (a plant in soil), hanging or leaning objects, several supports
and instanced or particle geometry are **unsupported or ambiguous**: they return `unsupported`, never a pass,
and go to visual review. Validation in (c) includes counterexamples: a resting-contact pair a bounding box
wrongly flags, an object floating above an off-centre support, a leaning object, a shell with an open edge.
The model covers what geometry cannot ("matches the reference", "which variant", "is the material
plausible") and reviews the unsupported cases visually.

**Request** (server-side, `POST /v1/decisions`, `gpt-6-luna`, as in `docs/research/computer-use-decision-models.md`):
shared `input` is the render (image) and the scene JSON; `questions` are `predicate`s ("The object visibly
intersects the floor.", "Any part of the subject is cut off by the frame edge.") or a `choice` over variants
(`A`, `B`, `abstain`). Independent questions go in one request (up to 400); a dependent one needs another.
The agent supplies questions in plain words; the server adds a fixed instruction to abstain when the image
does not settle it. A reference image is a second image in `input`.

**Where the key lives.** Server only: `OPENAI_API_KEY` in the server's `.env` (as for voice input, same
set/not-set indicator in settings, optional `PARTYLINE_DECISIONS_KEY` to use a separate key). It is never sent
to the helper, add-on or agent. Renders leave the host for OpenAI (like `openai-compatible` ASR), so the
separate checkbox above is the consent, and the server refuses `render_check` for media not produced
by `blender_render` in this session, **and refuses unless the session holds the checker scope and the media is `checkable`**; the
server, the only caller of OpenAI, states the reason in the error. Tests: exec-only session, declined
escalation, accepted escalation, revoke or tray removal mid-run, media rendered before the scope existed.

**Cost.** Billed at $0.10 per million input tokens, no output charge. Assuming about 2,000 billed tokens per
request (one image at 1024 px plus questions; an assumption to measure in phase c), that is $0.0002 per
check, so 50 checks cost one cent. A per-session cap (default 200 checks, `PARTYLINE_RENDER_CHECK_MAX`)
stops runaway loops. Pilot latency was 0.3 to 0.55 s p50 (synthetic); expect about 1 s with a 1 MB render.

**Abstentions and thresholds.** The pilot's accepted-answer accuracy (100%, n=65 to 70 at 65 to 70% coverage)
is synthetic UI, not 3D scenes, so this design assumes **nothing** about accuracy and fails toward *looking*:
- predicate: `p(problem) >= 0.2` flags; `p <= 0.05` passes; between is `uncertain`, shown like a flag;
- choice: `abstain`, a refusal, or confidence below 0.7 is `uncertain`;
- an API error or budget exhaustion returns `unchecked` for every frame: the agent looks at them all.

Only confident passes are skipped, so the checker saves looks at the risk of a *wrong skip*; phase (d),
which would have tuned the thresholds, is dropped (section 7).

## 7. Phased build

Every file stays under the 300-line rule; `screen_hub.py` (274) and `client.py` (276) only gain a one-line
dispatch into new modules. Tests mirror the screen-control ones (`tests/test_local_tools_*.py`); the
add-on's tests fake `bpy`.

**(a) Relay plus exec MVP** (one PR per repo, add-on first).
- `partyline-addons/blender/partyline_relay/`: `blender_manifest.toml`; `__init__.py` (register, banner, End
  button, about 100); `server.py` (HTTP, secret, Host/Origin checks, lease, queue and timer drain, about 170);
  `commands.py` (exec with namespace, deadline, caps, undo; scene info, about 170); `README.md` crediting
  blender-mcp. Extension zip built in CI.
- `partyline/`: `local_tools.py` (hub: sessions, holder, scopes, limits, routing, about 250);
  `local_tools_link.py` (message dispatch out of `screen_hub.py`); `local_tools_routes.py`;
  `local_tools_audit.py` plus a `db_schema.py` entry; `mcp/tools_blender.py`; `docs/local-tools.md`.
- `partyline_helper/`: `tools.py` (dispatch, grant state, about 150); `tools_consent.py` (dialog, lease
  renewal, revoke fan-in, about 120); `tools_addon.py` (discovery file, threaded HTTP client, about 120);
  `tools_audit.py` (about 60); small edits to `client.py`, `status.py`, `tray.py`, `control.py`.
- Acceptance on Windows: dialog in front; decline, silence, hotkey, tray Quit, Blender End, helper kill (lease)
  and network loss each stop the next call; wrong secret and a browser fetch are refused; a runaway Python
  loop is cancelled; both audit copies match.

**(b) Render as media.** Add-on `render.py` (clamps, camera select, temp dir, artifact id; about 120) and
`screenshot.py` (offscreen, about 80); helper `tools_media.py` (fetch artifact by id, re-encode, send binary,
about 80); server stores via `screen_frame_store.store_frame` and returns the `screen_frame` reference shape;
`tools_blender.py` gains `blender_render` and `blender_screenshot`. Open risks: GPU offscreen on Greg's
machine, render cancel, 4 MiB ceiling. Built; the risks are tracked in `docs/local-tools.md`.

**(c) Decision-model checker.** `partyline/render_check.py` (Decisions client, thresholds, budget, about 200),
`render_check_routes.py`, `mcp/tools_check.py`; add-on `geometry.py` (camera-space bbox, overlap, support
ray cast, about 120). Uses the pilot's client conventions from `experiments/decisions-pilot/run.py`.
Built (partyline 2.98.0, add-on 0.3.0); how it behaves and what is still open: `docs/local-tools.md`.

**(d) Evaluation — dropped (Greg, 2026-11-08).** Decision models will not judge whether Blender scenes look
correct, so no `experiments/blender-eval/` harness is built. It would have measured task correctness and checker
detection (flags against seeded labels) across 18 tasks, with and without `render_check`.

## 8. Decisions (Greg, 2026-11-07)

1. A Blender session is **not** tied to a screen share; per-session consent on the computer is still required.
2. Idle expiry 15 minutes; 10 minute re-ask cooldown after a local kill.
3. The render checker (OpenAI) is a separate checkbox in the same dialog, unchecked by default. Python can be
   allowed without sending images; `render_check` refuses when it is off.
4. The add-on lives in the public `partyline-addons` repo as a Blender extension zip built by CI. A first
   test on Windows with Blender 5.x only is enough.
5. The add-on saves a backup copy of the open file at session start.
6. Phase (d) budget (about $5 of checker calls plus agent tokens) is withdrawn, Greg, 2026-11-08: phase (d) is dropped.
