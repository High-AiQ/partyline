# Learned screen workflows

A person demonstrates a repeated screen task once with a strong model at high
reasoning effort. The model saves a parameterized workflow in the project, and
the person approves it for unattended use. A server-side runner with no model
replays each step through the existing window grant and verifies the outcome
before advancing. The format and runner are source-agnostic across UI Automation
(UIA), Chrome DevTools Protocol (CDP), and guarded point input. Browser checks
that depend on the DOM and direct file attachment are explicitly CDP-only. A small model gets one
chance to propose a repair when a step fails.

1. Record a successful demonstration or reconstruct it from an authorized line history.
2. Distil the run into semantic targets, typed inputs, checks, and confirmation stops.
3. Review the whole workflow bundle and approve its exact revision for unattended use.
4. Start a run with parameters and an existing window grant. Resolve, act, and verify one step at a time.
5. On an eligible failure, ask the small model for one proposal. Escalate unresolved failures with evidence.
6. Resume from the first unverified action after correcting the live view, or start a new run at step one.
7. Post the outcome to the line and retain a run audit.

## Motivation

In one long desktop browser session, roughly 35 module edits across 7
documents took about 4,800 seconds in screen tools and 4,300 seconds in
model turns. Model turns took about 3.3 seconds each at a median context of
250K tokens. Median element reads took 5.1 seconds and element actions
3.4 seconds. Most edits repeated the same sequence of opening a dialog,
picking a type, attaching an image with alt text, filling text fields and a
table, saving, and checking the saved notice. The parallel screen latency work
targets helper read time. This design removes the model turn from each
successful step. These are field observations from one session. [Telemetry](../telemetry.md)

## Workflow file

Use versioned YAML with a JSON-compatible data model. A workflow has a name,
a short description, `use_when` guidance, typed parameter declarations, and
an ordered list of steps with unique IDs. Keep the YAML readable so a person
or a model can understand the reviewed plan and follow it manually when
needed.
Parameters support text, enumerated text, media IDs, and bounded lists of typed
items or records. A list can bind directly to an action input or expand a
bounded sequence of steps, such as filling table rows in input order. Expand
and validate the plan before sending input. Reject unknown fields, unsupported
versions, duplicate keys, and invalid or out-of-range bindings. Bind parameters
as typed values, including in names or check expectations, without evaluating
templates as code. Action verbs, capability declarations, and confirmation
requirements are fixed by the approved workflow.

Each step defines the following fields.

| Field | Meaning |
| --- | --- |
| `id` | A stable step name for progress, repair, and audit records. |
| `target` | A semantic role with an accessible name or label text where exposed, optionally scoped to a named ancestor or landmark. Use a one-based ordinal only as a last resort within an explicitly named scope and with the expected match count. |
| `action` and `inputs` | One helper-backed action and its literal or parameter-bound arguments. The vocabulary is `invoke`, `click`, `set_value`, `type`, `key`, `select`, `set_files`, and `scroll`, with guarded point fallback as a route. |
| `requires` | Explicit source or feature requirements for steps that depend on specific capabilities, such as `cdp.set_files` or `cdp.screen_eval`. The validator rejects a missing declaration for either capability. |
| `preconditions` | Optional predicates over the current view, such as the expected dialog being open or the destination field being empty. |
| `postcondition` | Required predicate and bounded timeout. A distinct semantic target can describe the expected result, such as a notice after a save. |
| `confirm` | Required boolean. Set it to `true` for any irreversible or externally committing effect and supply an `effect` description. Review covers the effect of keys and dialog responses as well as labeled buttons. |
| `allow_point` | Optional boolean, off by default. Enables the guarded point route for the declared action. |
| `allowed_dismissals` | Optional list of semantic dialog targets and approved dismiss actions. Empty by default. |
| `navigation` | Optional expected document transition with a destination landmark to verify. Default is to stay in the current document. |

Match exact semantics under the chosen scope and require a unique, supported
match. UIA and CDP both support role, accessible name, and ancestry, with
source-specific role and state normalization. Use label text when the source
exposes it or its association. Ordinals require a complete scope, an unchanged
expected count, and an authored ordering rule. Per-read IDs, backend IDs, look
marks, and coordinates are transient execution evidence and never appear as
persisted target identity.

Predicates cover element presence or absence, exact value, state such as
checked, expanded, or selected, dialog closed, and notice text. Browser checks
can use a read-only `screen_eval` predicate. That existing tool evaluates
JavaScript, so a workflow may select only reviewed, server-owned read-only
predicates with typed arguments and bounded Boolean results. The runner
accepts no free-form JavaScript or model-authored expressions. A false result
keeps the check pending until the deadline. Missing or unsupported state,
truncation that hides the relevant scope, and an unavailable subscription
cannot prove absence or success. For recurring notices, require evidence of a
fresh occurrence or state transition from the pre-action observation.

This excerpt shows the syntax for a portable field edit and a CDP-only attachment.

```yaml
version: 1
name: edit-module
description: Attach an image and fill its alternative text.
use_when: The edit dialog is open in a granted window.
parameters:
  alt_text: {type: text, max_length: 500}
  images: {type: list, items: media_id, min_items: 1, max_items: 1}
steps:
  - id: attach-image
    target: {role: file_input, name: Image, within: {role: dialog, name: Edit module}}
    action: set_files
    requires: [cdp.set_files]
    inputs:
      files: {param: images}
    preconditions:
      - {check: file_count_equals, requires: [cdp.set_files], expected: 0}
    postcondition:
      check: file_count_equals
      requires: [cdp.set_files]
      expected: 1
      timeout_ms: 5000
    confirm: false

  - id: set-alt-text
    target: {role: textbox, name: Alternative text, within: {role: dialog, name: Edit module}}
    action: set_value
    inputs:
      value: {param: alt_text}
    postcondition:
      check: value_equals
      target: step_target
      expected: {param: alt_text}
      timeout_ms: 3000
    confirm: false
```

The step's effective requirements include those of its checks. The file-count
example verifies attachment count. A workflow that needs stronger evidence
can use supported file read-back for expected names and count. Media IDs must
be readable by the requesting attachment and use the existing staging and
size limits. Workflows in the initial format accept only media IDs for
`set_files`.

### Source capabilities

The matrix describes the existing helper underneath the proposed runner.
An action or property is usable only when the live target and helper expose
the required capability. [Screen helper](../screen-helper.md)

| Source or route | Target fields | Actions | Checks |
| --- | --- | --- | --- |
| Windows UI Automation | Control role/type, accessible name, exposed label, named element ancestry or landmark, scoped ordinal | `invoke` via Invoke, `set_value` via Value, `select` via SelectionItem or combo box, and `scroll` via Scroll or ScrollItem. The helper exposes Toggle and ExpandCollapse where supported. `key` maps to scoped `press` for Enter, Tab, or Escape when supported. Use the point route for `click` and `type`. | Presence/absence, values, checked/selected/expanded state, dialog closure, readable notice text, all subject to provider coverage. |
| CDP page | Accessibility role/name, exposed label, document or element ancestry/landmark, scoped ordinal | `invoke`, `set_value`, `select`, scoped `press`, and `scroll_into_view` on supported elements. The helper also exposes `toggle`. Use point input for wheel scrolling, `click`, or `type`. Direct `set_files` requires a CDP file input. | Presence/absence, values, exposed state, dialog closure, readable notice text, file read-back, and guarded CDP-only `screen_eval` predicates. |
| Guarded point input | Semantic target from a fresh marked look when available. For a purely visual target, a person identifies the point from the current granted-window image. | `click`, point `scroll`, and window-scoped `type` and `key` after a verified focus click in the same run and grant. The helper chooses page input or the consented real cursor route. | Landing, focus, and input receipts support diagnosis. Postconditions use the available UIA/CDP observation or explicit human verification for a purely visual result. |

A plain Windows application gets UIA where its provider exposes the controls,
plus consented point input. Chrome gets CDP page capabilities when its
transport is approved and the helper can prove the window/tab mapping, with
UIA available when CDP is unavailable. The current mapping is specific to
Chrome. Edge uses UIA and the consented point route today even though it is
Chromium-based. Firefox uses UIA and the consented point route as well. An
UIA-only run lacks CDP-only checks and direct `set_files`, so an upload would
require a separately authored and reviewed dialog path, with its own grant
if the dialog is a separate window. macOS AX and Linux AT-SPI remain planned
sources. [Window elements](../screen-helper.md#read-a-windows-windows-ui-elements) ·
[CDP window mapping](../../partyline_helper/cdp_mapping.py)

For a future attended point fallback, the runner may resolve a unique reviewed semantic
target to the matching mark in a fresh `screen_window_look` only when the step
explicitly permits the route. It sends the current mark or snapshot-bound
point through the existing guarded window tools. For point `type` and `key`,
the runner checks that the named field still has the focus established by a
verified click in the run. A purely visual target or check pauses for the
person. Never reuse a coordinate from a recording or
silently turn a refused element action into point input. Check declared
capabilities before starting where known, and again against the live source at
each step. A refusal names the step, required capability, and observed source
(for example, `attach-image requires cdp.set_files; current source is uia`).
[Marked looks](../screen-helper.md#look-at-a-window) ·
[Point input](../screen-helper.md#point-input-in-the-chosen-window)

## Learning and approval

The learner is a strong model at **high** reasoning effort. It works from
either an explicitly started recording of one successful live run or a
person-selected interval of an existing line. The live recording captures the
ordered authorized helper calls, relevant semantic observations and outcomes,
and the intended result of each step. For historical distillation, the line's
`tool_calls` records give approximate chronology, operation names, timing, and
outcome categories. They are best-effort telemetry and contain neither
arguments nor result bodies. Use the authorized structured transcript for
arguments, reads, and the user's intent where the adapter retained them. When
evidence is missing, mark the step unresolved and request a focused
demonstration. Use the recording path for adapters with incomplete transcripts.
[Tool and turn telemetry](../telemetry.md)

The learner extracts the repeated sequence, turning instance data into typed
parameters and keeping stable control roles, labels, and scopes. For example,
derive a row scope from its header or a supplied row label, then resolve the
field by its column label. Treat ordering, localization, and optional dialogs
as assumptions from the single example. Use a read-only preview on another
document or input set to surface ambiguity. Select checks from observed
before/after state and ask the person what counts as success when the UI cannot
establish it.

The person reviews a rendered action plan and the file diff, including
parameter types, matching rules, source requirements, expected transitions,
allowed point fallbacks, and irreversible effects. Save approval against the
project, checkout, path, and bundle hash. The hash includes the exact file
revision and relative path of every reachable workflow, including every enum
branch. The review shows the call tree, confirmation effects and union of
capabilities. Editing any piece invalidates all approvals that include it.
The first unattended run and each changed revision require approval. Per-action confirmation still
applies during replay. A learner or repairer may propose a revision through
the project's ordinary write fence and review path. [Line checkouts](../hierarchy.md#the-checkout-a-line-works-in)

### Generated workflow skills

Each approval publishes a thin, line-local skill where supported. It contains
the workflow name, its description and `use_when` from YAML, the typed
parameters, and the bundle's source and feature requirements. It points to
`screen_workflow_start` for the approved top-level workflow with its parameters,
existing grant ID and a stable client key. It also points to status and resume
for a stopped run. The runner executes each component directly from the YAML.

Partyline regenerates the skill on approval and withdraws it when the
revision changes or a person revokes approval. Phase 1 installs the projection
into private Codex attachment homes on Linux and macOS. It writes no
generated files into the project. Codex on Windows, Claude Code and OpenCode
v2 use MCP discovery until their installation paths are wired. The MCP
catalog is authoritative for all clients. Phase 2 documents the learner
and repairer procedure in a separate repository skill.
[Adapter session files](../adapters.md#locate-the-transcript-unambiguously)

## Server runner and MCP entry points

The runner is a server-side job using the same operations as the existing
window-grant routes under the starting attachment's principal and line.
Factor shared authorization and execution into the route services if needed.
The job receives the exact existing grant ID. It cannot discover, attach, or
swap windows. Recheck grant and line authorization at every read, action, and
check. Keep existing grant budgets, per-window locking, CDP identity proofs,
UIA freshness barriers and pattern checks, point hit tests and consent, and
helper audits. Use helper-issued tokens only for the observation that resolved
them. Allow one running workflow per grant and keep one action in flight.
A concurrent manual or tool action can change state between steps, so each
step must resolve against current evidence and honor its preconditions.
[Helper element actions](../screen-helper.md#act-on-elements-in-the-chosen-window) ·
[CDP identity proof](../../partyline_helper/cdp_identity.py)

For each step, use a narrow read scoped by the semantic target and check, or
reuse a complete matching slice of the same-generation tree. Reuse requires
the same grant, source, and document, and the helper's event-counter freshness
barrier with a live subscription. Partial or busy evidence in the relevant
scope yields an unknown result. Resolve a single supported target, verify
preconditions and any confirmation, and dispatch through the helper with a
scoped `then` where it can answer the postcondition.

Take the initial post-action observation from `then` or make one scoped read.
Then wait for relevant grant-scoped UIA or CDP change events within the
postcondition's monotonic deadline. Use a subscription registered before
dispatch and a counter cursor so changes during dispatch or a read cannot be
missed. The runner may need a grant-scoped event feed from the existing helper
notifications. Coalesce changes, re-read on evidence of a newer relevant
generation, and use a one-shot deadline to stop. A timeout never schedules a
periodic read. When the event feed is unavailable, a complete immediate
observation may pass, but an unresolved check stops as unknown. A helper
receipt or quiet settle interval alone cannot verify the step.
[Helper event barriers](../screen-helper.md#uia-latency-scoped-reads-and-live-state-diagnostics)

MCP advertises start and resume when the attachment has a window grant.
A process on the run's line with access to the original grant can discover
the run and resume it with the original parameters. The initiating
attachment, latest resuming attachment, and authorized people can query
status even after the grant ends. They can also stop an active run. Clients that do not re-list can use
`extras`. [MCP catalog](../../partyline/mcp/catalog.py)

```text
screen_workflow_list() -> {workflows, runs}
screen_workflow_show(workflow) -> {definition, revision, approved}
screen_workflow_start(workflow, window, parameters, client_key)
  -> {run_id, revision, state}
screen_workflow_status(run_id)
  -> {state, verified_steps, total_steps, current_step, outcome?}
screen_workflow_stop(run_id)
  -> {state, current_step, outcome?}
screen_workflow_resume(run_id, parameters)
  -> {run_id, revision, state}
```

Start returns after validating and pinning the workflow bundle and
principal. The same attachment and `client_key` return the original run for
identical request data and reject conflicting reuse. Stop is idempotent and
gates dispatch immediately. Publish a start notice, bounded progress updates
(such as completed groups), confirmation and escalation requests, and a final
outcome on the run's line using server events. Include the run ID, revision,
verified count, current step, and stop reason. Confirmation notices give the
window owner a Confirm or Cancel prompt above the composer. The decision
uses a single-use token and expires after 120 seconds or upon a window change.
Confirmation, paused handoffs, and final outcomes wake the process that
started or resumed the run.
Start and progress notices go to the line without waking a process.
Tool callers can query a snapshot on demand.

### Version 1 interface

Version 1 supports `invoke`, `set_value`, `select` and CDP-only `set_files`
with existing line-readable media IDs. Its checks are `present`, `absent`,
`value_equals`, `notice_text`, and CDP file-count read-back
(`file_count_equals`). A check defaults to the step target. `requires`
supports `uia`, `cdp`, and `cdp.set_files`. For a list of records, write a
`for_each` entry with a list parameter name and nested `steps`. It also
accepts a binding such as `{item: rows}` or `{param: rows}`. Inside a repeat,
`{item: field}` binds a field of the innermost record and `{item: true}`
binds the current item. Records and lists can contain other records and lists.
Ordinals use provider tree order within the named scope and require an exact
`match_count`.

A call step has an `id`, `use` and optional `with`. Bind the receiving
parameters from the caller's parameters or innermost item. To choose a
workflow using a record's enum field, use `use: {by: kind, cases: {...}}`
and cover every declared choice. `case_bindings` adds or overrides common
`with` bindings for a choice. Every call site is checked against the
receiving signature, and every binding in the expanded plan is validated
against its receiving constraints before any input is sent. Components
inherit the same grant, approval and run journal.

The runner allows four levels of calls and four nested repeats across the
call path, enough for a module, row and cell with one extra repeat. Lists
hold at most 32 items and may declare smaller limits. Input JSON is bounded
to 512 KiB when serialized with ASCII escapes. Parameter declarations
allow eight nested containers so the module, row and cell lists can each
contain records. A bundle can reach up to 32 workflow files. Each attempt
expands at most 4,096 actions and visits at most 16,384 entries, counting calls
and repeats even when a branch generates no action. Seven six-column,
ten-row modules can use several actions per cell and still fit. Each attempt
has a 45-minute monotonic deadline so a stalled sequence of checks or
confirmations leaves a record of where it stopped. The existing window
grant's authorization, per-second rate and action budget still apply. A
fully populated seven-table example uses 856 actions. For a job beyond
the default 300-action grant cap, the operator can configure
`PARTYLINE_CONTROL_SESSION_ACTIONS` before granting the window.

The audit journals each verified action with its expanded ID and one-based
index, atomically with the resume cursor. To resume, use the original run ID,
window grant, approved bundle and parameters. Partyline can reuse the inputs
of the last 16 runs in server memory for the window owner or the original
caller. Other processes supply the original parameters when resuming, as do
callers after the cache is cleared. The audit verifies
input identity with keyed digests. The runner captures the live window again,
checks the pinned document and failed step's target and
preconditions, then continues from that step. If input may have been sent
without verification, retry requires explicit preconditions and a fresh
observation that the intended result is still false. A confirmation step
always asks the window owner again. If the grant has ended, start a fresh
run on a new grant.

The runner captures and validates a complete view when it needs to prove
scope, uniqueness, or absence. It reuses a complete view from the same run
only when a live subscription and helper event counter prove it is current.
It uses a freshly resolved semantic target and one helper action per step. An unresolved check waits for the existing
grant-scoped event feed until its one-shot deadline. A missing feed permits
a complete immediate verification. Guarded point input, page navigation,
arbitrary JavaScript and dialog dismissal are outside the Phase 1 runner.
A step that needs point input and declares `allow_point` leaves a paused
handoff for the person. The new helper capability carries request-scoped
cancellation and document identity through the dispatch boundary.

All REST paths below are relative to
`/api/conversations/{conv_id}/screen-workflows`. A person's access token
authenticates review, approval, confirmation, and audit calls.

| Method and path | Request or result |
| --- | --- |
| `GET /` (base path) | List workflow names, revisions and approval state. |
| `GET /definitions/{name}` | Show the typed definition and its revision. |
| `GET /definitions/{name}/review` | Read the exact review plan as a person. |
| `PUT /definitions/{name}/approval` | Approve with `{"revision":"<sha256>"}` after review. |
| `DELETE /definitions/{name}/approval` | Revoke that workflow's approval on this checkout. |
| `GET /runs` | List recent runs visible to the caller, including active runs. |
| `POST /runs` | Start with `workflow`, `window`, `parameters`, and `client_key`. |
| `GET /runs/{run_id}` | Read run status. The window owner sees pending confirmation context and its token. |
| `POST /runs/{run_id}/confirmation` | The window owner decides with `{"token":"<challenge>","allow":true}`. |
| `POST /runs/{run_id}/stop` | Stop the run. |
| `POST /runs/{run_id}/resume` | Resume the same run with `{"parameters":{…}}`. The body can be `{}` while the original parameters are cached. |
| `GET /runs/{run_id}/audit` | Read the content-free run audit. |

The [record lab definition](../../tests/fixtures/screen-workflows/edit-record.yaml)
and `/lab/window-bench/workflow.html` exercise the CDP path. The lab accepts
`?scenario=delayed`, `?scenario=ambiguous`, and `?scenario=interrupted`. The
UIA test runs a native-control fixture without a CDP route. Its image
attachment counterpart requires a separately authored dialog flow.

## Example · Publish rich content for a document

Use the [complete workflow set](../../tests/fixtures/screen-workflows/publish-document)
in `.partyline/workflows/` in the line's assigned checkout. Open the
[window-bench document editor](/lab/window-bench/workflow.html) in a
CDP-capable granted window. In the line's **Workflows** menu, review and
approve `publish-document`. Its top-level repeat dispatches each module.

```yaml
- for_each: modules
  steps:
    - id: module
      use: {by: kind, cases: {image: image-module, text: text-module, table: table-module}}
      case_bindings:
        image: {images: {item: images}, alt: {item: alt}}
        text: {headline: {item: headline}, body: {item: body}}
        table: {rows: {item: rows}}
```

1. Set **Document title**, then add each module in the supplied order.
2. **Image** opens the module and the image file dialog. It attaches the
   supplied line media ID, accepts the dialog, fills **Alternative text**, and
   saves the module into the draft.
3. **Text** adds a module, fills **Headline** and **Body text**, and saves it
   into the draft.
4. **Comparison table** repeats over up to ten rows. Each row has a
   **Reference** field and up to five later columns. Those columns each have
   an independent dropdown. **Included** and **Excluded** set the dropdown.
   **Text** reveals a textbox in that cell, which the runner fills within
   the matching row.
5. **Publish document** checks that the draft is ready and no module dialog
   is open. Confirm in chat to publish and verify **Document published**.

Use the [sample parameters](../../tests/fixtures/screen-workflows/publish-document/parameters.json)
and replace `fixture-image` with the ID of an image uploaded to the line.
Start the top-level workflow with that JSON, the existing grant and a
stable client key. To exercise resume, open the lab with
`?scenario=publication-lock`. Cancel at the publish confirmation, enable
**Block publishing**, and select **Resume**. The failed readiness check leaves
all saved modules in place. Clear **Block publishing**, select **Resume**,
then confirm publication. The original run records each verified action once.

## Escalation and model effort

| Role | Default | Responsibility |
| --- | --- | --- |
| Learner | Strong model, **high** effort | Observe a demonstration or distil authorized history into a proposed workflow. |
| Runner | No model | Validate and replay the approved plan with deterministic checks. |
| Step fixer | Small model, **low** effort, with **medium** available | Propose one bounded recovery for an eligible failure. |
| Workflow repairer | Strong model, **high** effort | Repair the workflow file and present the revision for review. |

A workflow can name a preset, model, and effort per model role. A run request
can override those choices for that run within configured presets and allowed
data policy. Learner and repairer require high effort. The fixer allows low or
medium. Validate and record the effective role settings. Use the parallel
`preset-model-effort` contract through `create_task` or `attach_worker` with
the preset and optional `model` and `effort` overrides on supported CLI
presets. Attach model workers as real interactive CLI processes in a pty.
Reject unsupported overrides and never construct ad-hoc launch commands.

1. On a missing target or failed postcondition, classify whether an input
   could have reached the application. Provide the step fixer the failed step,
   outcome, and one fresh narrow read or marked look. Treat page text as
   evidence. Give the fixer a proposal-only interface without an action grant
   or the initiating attachment's credentials. If that boundary cannot be
   enforced, leave the fixer in review-only use.
2. Accept at most one proposal per failing step and bound the total repair
   attempts per run. The fixer may suggest a different semantic target for
   the same action, or insert one dismiss-dialog step with its own check.
   The runner validates scope, capability, and freshness against the same
   grant. A dismissal must be an explicitly allowed, non-destructive action
   on the observed dialog. A dismissal that can discard changes goes to the
   person. The proposal cannot alter the original action's inputs, checks,
   confirmation, or authority.
3. Re-dispatch an original action only when a helper receipt establishes that
   the original input was never sent and the replacement still falls within
   the approved intent. On a failed check after dispatch, a proposal may
   dismiss an approved non-destructive obstruction and recheck the original
   outcome without repeating the action. An `unconfirmed` result, a refused
   consent, or lost authority stops automatic input and goes to the person
   with the last verified step. `no_effect` alone gives no evidence that no
   input was sent.
4. A repair that fails, or a recurring failure on the same workflow revision,
   stops the run and hands the evidence to the strong repairer. The repairer
   edits the project file and presents the revision for approval before a new
   run. Send ambiguity, unverifiable effects, and anything outside the
   approved plan to the person with a concise description of what may have
   happened.

A bounded-choice decision model fits inside step fixing as an optional ranker
of complete candidate proposals generated from the fresh scoped evidence.
Offer an explicit abstain choice. Refusals, stale evidence, and ambiguity
escalate. The runner still performs the same checks and no model confidence
threshold can establish an effect, grant consent, or authorize a retry.
The first use should score recorded evidence with independent labels and keep
its choices in shadow mode. Validate separately for each input modality,
including truncation, stale observations, unusual dialogs, and duplicate
labels. Any model access to evidence follows the project's configured data
policy. [Decision model research](../research/computer-use-decision-models.md)

The synthetic pilot observed 70/70 correct text accepts at 70% coverage and
65/65 correct text-plus-image accepts at 65% coverage. The examples were
highly regular, with no desktop actions. Its synthetic deterministic
verifier matched the model verifier on all 30 labeled outcomes. The recorded
UIA follow-up accepted 16/27 held-out choices with zero observed errors and a
17.1% upper error bound under independent-sample assumptions. Two dialogs were
excluded for truncated trees, usable offscreen cases were absent, and its
verification labels reused the tested predicate. These results support offline
evaluation and say little about live repair risk or end-to-end savings.
[Synthetic pilot](../research/decisions-pilot-results.md) ·
[Recorded UIA follow-up](../research/uia-decisions-pilot-results.md)

## Storage and sharing

Store workflows under `<project>/.partyline/workflows/<name>.yaml` and version
them with the project. The runner resolves a workflow name using the server's
assigned line working directory, then walks its filesystem parents up to and
including the configured project root. The nearest file wins. Reject paths in
the name, symlinks or junctions in workflow paths, and invalid nearer files. Use the line's
authorized project path and open and pin the validated bytes so edits during
execution cannot change a run. Never search a parent line's separate worktree
or accept a server filesystem path from the caller.

Lines share workflows by checking out the project's committed files. The approval
record identifies the project, checkout, and relative file path. A file
change, replacement, or copy requires approval of the resolved file again.
Workflow sharing conveys the plan only.
Keep the review record and run data in Partyline. The Partyline repository
ships the format, runner, and generic examples. Application-specific workflows
live in the projects that own them. [Line checkout rules](../hierarchy.md#the-checkout-a-line-works-in)

## Authority, interruption, and audit

- **Authority.** An existing explicit or standing window grant is required for
  the whole run. Standing access and inheritance follow their current rules,
  with normal local consent on the real-cursor route. Workflow approval adds
  no screen privileges and does not authorize an irreversible step.
- **Confirmation.** Pause before each irreversible action, including publish,
  submit, delete, and equivalent effects triggered by a key or dialog. Treat
  an unknown effect as requiring the person. Show the intended effect,
  destination, and relevant inputs. Take an authenticated, single-use human
  confirmation bound to the run, revision, step instance, action inputs and
  verified target context. Expire it on relevant changes or deadline. Reprove
  target, grant, and preconditions immediately before dispatch. An absent or
  denied confirmation ends the run without that action. A generic verb can
  have application-specific effects, so the human review must classify each
  action in context. Overrides and repairs cannot clear a confirmation.
- **Kill switch and revocation.** A person can stop the run from its line and
  can revoke the share from the tray or web as usual. Stop, revocation,
  disconnect, or loss of the starting attachment closes the runner's dispatch
  gate, cancels waits and proposals, and clears outstanding confirmations.
  Carry per-operation cancellation through to the helper's final dispatch
  gate so queued input, including input awaiting consent, is dropped. An
  action already sent may still take effect. Record uncertainty when its
  outcome is unknown and never auto-resume after a stop or restart.
- **Navigation.** Track tab and document identity as well as window identity.
  A new document or tab discards cached targets, point evidence, and
  confirmations. Unexpected navigation stops the run even if the grant
  remains valid. An approved navigation step can continue only after a
  confirmed helper receipt, fresh destination identity, and a checked
  destination landmark within the grant. If an iframe changes, invalidate
  its affected scope and require fresh evidence before continuing. When a
  provider cannot prove a required boundary, pause for the person.
- **Lock screen or secure desktop.** Pause reads and dispatch immediately and
  discard pending approvals and transient observations. Require a person to
  resume after unlock and revalidate the same live grant and document before
  any further input. If an action was interrupted after dispatch or the
  outcome is unknown, end automatic replay and let the person inspect.
- **Audit.** Correlate a durable run record with existing helper and server
  window audit records. Record who started or stopped it, project revision
  and workflow digest, grant reference, source, timestamps, verified step
  IDs, dispatch/check outcomes, confirmations, attempted repairs, model and
  effort, and final state. Write dispatch intent before input and preserve
  the outcome or its uncertainty. An intent left open after restart remains
  unconfirmed. Store metadata with existing line-scoped audit access and
  retention rules. Exclude submitted text, file names and media IDs, screen
  contents, and raw model prompts from the run audit.

[Window authority and revocation](../screen-helper.md#standing-window-access)

## Controlled comparison

Add replay as a third arm to the already-approved text-first and look-first
comparison. Run the same tasks with the same inputs, helper build, platform,
window-grant rules, and step and outcome definitions. Reset application state
and use fresh browser/application and agent sessions for each repeat. Balance
arm order across tasks, keep training demonstrations out of scored repeats,
and freeze the approved workflow before measurement. Keep helper latency
changes fixed across all three arms. Preserve the approved live task scope.
Evaluate the model fixer offline until live use has separate approval, then
measure it as a labeled variant of the replay arm.

Preregister repeats, seeded inputs, task order, success and stop criteria,
what counts as a completed step, and the analysis plan. Measure wall time
from step eligibility through independently verified completion, including
reads, waits, and model time. Report per-step and per-task wall time with p50
and p95, completed steps over attempted steps, and time to stop for incomplete
runs. Count refusals, errors, unconfirmed outcomes, false successes, and
human interventions separately. Report tokens by role, with uncached input,
cache read/write, and output, and keep estimated image context separate.
Separate one-time learning/review cost from replay cost and report the
amortized cost over the measured repeats.

Use run IDs and per-step spans for internal helper calls, since server replay
does not produce an MCP call for each action. Reuse content-free helper
timings and structured transcript usage where available, and mark missing or
estimated data accordingly. Label outcomes from independent evidence, such as
the generic test page's saved-state record. [Telemetry](../telemetry.md)

## Phased plan

| Phase | Scope and exit | Estimated engineering effort |
| --- | --- | --- |
| 1. Format and deterministic runner | Implement review, start/stop, audit, and a few action types (`invoke`, `set_value`, `select`) with presence, absence, value, and notice checks on a generic test page. Include CDP file input and file-count read-back. Exercise UIA and CDP where exposed, including delayed saves, ambiguous targets, capability refusals, and interruption. Add replay to the comparison once it supports the matched task steps. | 5–8 working days |
| 2. Learning and distillation | Record a live demonstration, support transcript-backed drafts, and show a reviewable workflow and preview. Validate parameterization and target scope on held-out inputs. | 4–6 working days |
| 3. Model-assisted repair | Add the small-model proposal role and strong-model file repair. Test with independent offline labels, then seek a decision on a live reversible pilot. Measure whether repair improves task completion and time. | 5–8 working days, excluding time to collect held-out recordings |

Estimated effort assumes reuse of the current grant services and helper event
sources. Wiring a reliable event feed for delayed checks and enforcing the
fixer's proposal-only capability are the largest uncertainties.

## Decisions

1. Phase 1 covers a generic lab flow that opens a dialog, selects a type,
   attaches an image, fills its alt text and other text fields, fills a
   small table, saves, and checks a saved notice. Include delayed saves,
   ambiguous targets, and interruptions. Exercise CDP and UIA, including
   a non-CDP UIA path with fakes. Keep test data and fixtures generic.
2. A person approves the exact content hash within the project. Any edit
   voids the approval. Captains and models can propose revisions. Approval
   does not transfer to another project's copy.
3. Keep evidence at existing destinations. In Phases 2–3 only presets
   already permitted to see the line's screen may see workflow evidence.
   Give the small fixer one narrow element read or marked look. A full
   screenshot requires a step declared visual. Optional demonstration
   recordings expire after 30 days. Run audit follows screen-audit retention.
4. Unattended point fallback is disabled in Phases 1–2. Pause for the person
   when a step needs it. An attended point route requires explicit permission
   in the approved step. Revisit after collecting comparison data.
5. Keep a separate small stress set for app changes and interruptions.
   Use the preregistered comparison's repeats and budget.
6. Edge continues to use UIA and guarded point input. CDP for that browser
   is a separate follow-up.
