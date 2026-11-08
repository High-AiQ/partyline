# Recorded Windows UIA Decisions follow-up

2026-11-08. **A live, gated pilot is not justified.** The first hosted Windows
recording is real UIA evidence, but two applications have incomplete trees,
offscreen challenge coverage is missing after excluding them, and verification
labels are circular. On the usable held-out subset, 16/27 choices were accepted with no observed
errors, but the 95% upper error bound is 17.1%.

## Recording audit, completed before paid calls

The [successful Windows run](https://github.com/High-AiQ/partyline/actions/runs/42484211467)
recorded Windows Server 2025 (build 26100) at commit
`022692429dd6ce861a8098e5952254b1069664af`.
Artifact `uia-decisions-corpus-42484211467`, ID `13618672802`, contains 15 text
JSON/JSONL files only. The source dataset is 6,589,104 bytes, SHA-256
`ac7a9d67941f573ae360e9cd3d17fcc916e8ff5d87d51e4516553f3da69f49c5`.
No artifact code was executed: loading and evaluation use Python `-I`, with
only the trusted experiment source directory added to imports.

[recorded-42484211467.json](../../experiments/uia-decisions-pilot/recorded-42484211467.json)
durably preserves the complete dataset using repeated-snapshot references, plus
audit entries and original file digests. Expansion reproduces the source JSON
semantically, including excluded recordings and original gold tasks.

Each app has four distinct snapshot IDs (before, unchanged, refused-action after,
and attempted-edit after). Element counts below follow that order.

| Application | Split | Snapshots | Elements per snapshot | Truncated | Evaluation |
| --- | --- | ---: | --- | ---: | --- |
| Notepad | Dev | 4 | 27, 27, 27, 27 | 0 | Included |
| Calculator | Dev | 4 | 45, 45, 45, 45 | 0 | Included |
| Tk/native Win32 fixture | Dev | 4 | 14, 14, 14, 14 | 0 | Included |
| Character Map | Held out | 4 | 26, 26, 26, 26 | 0 | Included |
| WinForms fixture | Held out | 4 | 13, 13, 13, 13 | 0 | Included |
| Open dialog | Held out | 4 | 31, 56, 66, 61 | 4 | Excluded |
| Save dialog | Held out | 4 | 45, 59, 49, 52 | 4 | Excluded |

The initial green workflow checked only for nonempty elements. All eight dialog
walks stopped early, so a green recording job did not establish complete evidence.
The updated collector treats `truncated:true` as incomplete, and preflight
excludes an entire application's choices and verification if any read is
incomplete. The 41 dialog rows are excluded before model calls, rather than
letting the validator veto every choice. Splits and family assignments are
unchanged; the WinForms fixture and both common dialogs remain held out.

## Task counts and spending preflight

The original data has 42 development and 68 held-out rows. Applying completeness
selection and finite case caps leaves 42 development and 27 held-out rows:

| Case | Dev original / selected | Held-out original / selected |
| --- | ---: | ---: |
| Normal | 27 / 27 | 41 / 17 |
| Absent target | 3 / 3 | 4 / 2 |
| Duplicate label | 1 / 1 | 2 / 1 |
| Disabled | 6 / 6 | 3 / 3 |
| Offscreen | 0 / 0 | 10 / 0 |
| Wrong pattern | 3 / 3 | 4 / 2 |
| Stale | 2 / 2 | 4 / 2 |

Per application, cap normal at 12, disabled and offscreen at 4 each, and every
other case at 1. These caps do not remove any further rows from the usable
subset. All 27 normal dev gold choices pass the deterministic validator, so
the maximum of 27 correct accepts exceeds the calibration rule's minimum of 10.
No thresholds or split assignments were adjusted using held-out predictions.
Intents remain literal, generated from recorded names/types; this is not a
benchmark of varied natural user requests. Freshness IDs explicitly expose stale
state. Offscreen handling has **no usable recorded cases**.

Before sending requests, serialized bodies total 663,866 bytes for dev and
302,341 for held out (maximum request 23,099 bytes). A deliberately loose planning
envelope of two input tokens per body byte plus 4,096 framing tokens per call,
at the historical conservative $0.25/M rate, gives $0.374941 dev plus $0.1788185
held out: **$0.5537595** new spending. This is an envelope, not a tokenizer count
or invoice. The carried ledger starts at **$0.6561055**; including the next-call
$0.50 reserve gives a planned total of **$1.709865**, below the $4.50 stop.
The original serialized harness still enforces that stop before every call.
No uncertain call is retried.

The driver writes atomic, fsynced partial metrics on a caught phase stop and
keeps the spending journal and pending marker. It also refuses all paid calls
if the dev corpus cannot reach ten correct accepted choices, or if the
whole-study planning envelope plus reserve exceeds the remaining budget.

## Choice results

The unchanged calibration rule selected **threshold 0** on dev: 25/42 accepts,
zero errors (59.5% coverage). Thresholds 0 through .95 tied at 25 accepts; .99
accepted 22. The lower threshold wins the predeclared tie-break. The gate and
evidence hashes froze before any held-out call. Frozen gate file SHA-256:
`ee0b6f7277342a20195f348644ee373e44fd57d239891f92cafc7b5d1b1806b4`.

The same 27 held-out responses support three operating points:

| Operating point | Accepted / tasks | Correct accepted | Coverage | 95% error upper bound |
| --- | ---: | ---: | ---: | ---: |
| Raw Decisions text | 16 / 27 | 16 / 16 | 59.3% | 17.1% |
| Deterministic validator | 16 / 27 | 16 / 16 | 59.3% | 17.1% |
| Frozen dev gate + validator | 16 / 27 | 16 / 16 | 59.3% | 17.1% |

The validator vetoed zero predictions, so this recording provides no measured
incremental protection from the gate. The threshold adds no confidence filtering.
Coverage also falls below the earlier exploratory 60% target. Zero observed
accepted errors is a point estimate, not evidence of a low underlying error rate.

| Held-out application | Accepted / tasks | Correct accepted | Coverage | 95% error upper bound |
| --- | ---: | ---: | ---: | ---: |
| Character Map (stock app) | 11 / 16 | 11 / 11 | 68.8% | 23.8% |
| WinForms fixture | 5 / 11 | 5 / 5 | 45.5% | 45.1% |

All 16 accepts were normal cases (16/17 normal intents). The model abstained on
all ten non-normal held-out cases: absent 2, duplicate 1, disabled 3, stale 2,
wrong-pattern 2. There are zero usable offscreen cases. It also abstained on the
fixture's normal-labeled `Outside view` button. This exposes another label
limitation: the provider reported `offscreen:false` for the deliberately placed
outside control, so the original property-derived gold called it normal. Dev
likewise abstained on `Development outside` and Notepad's `System` menu.
Labels and thresholds were not changed after these observations.

Held-out client wall latency p50/p95 was **271/520 ms**; dev was 290/475 ms.
These times include HTTP but exclude recording, actions and application settling.
Error upper bounds are one-sided exact binomial at 95%: for zero errors among
`n` accepts, `1 - 0.05**(1/n)`. They assume independent accepted tasks; controls
within an app are correlated. Only one held-out stock app remains, so the
task-level bounds cannot establish generalization across applications.

## Actual usage and durable evidence

All **69 serialized calls** completed (42 dev, then 27 held out), with no new
uncertain requests or retries. Usage: 345,022 input tokens, including 168,511
30-minute cache-write tokens and zero cache-read tokens; output tokens were zero.
At the carried conservative rate of $0.25/M for every input token, this run adds
**$0.0862555**, for a cumulative **$0.742361** including the historical
$0.6561055 (which already reserves $0.50 for the old interrupted request).
These are conservative estimates, not invoice amounts; the $4.50 stop was not hit.

The new journal is [responses.jsonl](../../experiments/uia-decisions-pilot/responses.jsonl).
Combined with the unchanged original pilot ledger, it has 1,109 entries. Fresh
evaluation state seeds both ledgers atomically, preserving paid keys and costs.
The [frozen gate](../../experiments/uia-decisions-pilot/gate.json),
[preflight](../../experiments/uia-decisions-pilot/preflight.json),
[metrics](../../experiments/uia-decisions-pilot/results.json), final partial
checkpoint and compact recorded corpus are committed text evidence. Run
`uv run --locked python -I experiments/uia-decisions-pilot/summarize.py`
to recompute the results offline; it validates the frozen gate and exact response
coverage without API calls.

## Verification audit

The recorder chose the first enabled, onscreen Value-pattern control. This did
not establish writeability:

| Application | Attempted edit | Predicate label |
| --- | --- | --- |
| Notepad | Text Editor value changed to the exact string | Success |
| Calculator | Result Text control was read-only; helper refused | Unknown; no success pair |
| Tk fixture | Native Edit value changed to the exact string | Success |
| Character Map | Edit accepted text but appended a carriage return | Unknown; exact predicate false |
| WinForms fixture | Corpus value changed to the exact string | Success |
| Open / Save dialogs | Command Module toolbar was read-only; helper refused | Unknown; also excluded as truncated |

The included held-out subset has six verification pairs: two unchanged controls,
two refused unknown-id controls, Character Map's unknown exact-value outcome,
and one WinForms predicate-labeled success. False success is **0/5 by
construction**, and the one predicate-labeled success has a matching transition.
This is a consistency check, **not verifier recall, robustness, or an independent
false-success estimate**. Success labels reuse the same predicate being scored;
the unknown-id refusal stops in ActionWorker before reaching UIA. No independent
95% false-success bound is claimed.

A defensible next verification study needs independently labeled app-observed
outcomes, genuine dispatched failures/no-ops, writable-field selection and
application-specific state predicates. Do not normalize Character Map's trailing
carriage return after inspecting this held-out result and count it as a new success.

## Local validation

All 17 no-network experiment tests pass under the verified 4 GiB cap, including
truncation exclusion, row caps, insufficient-dev no-spend, partial budget stops,
fresh-state ledger preservation and lossless compaction. Offline recomputation
matches the committed results exactly. Repository gates passed: Ruff, 4,285
backend tests (29 platform skips), 92% combined line/branch coverage, source line
limits, no-media checks, frontend verification (786 tests) and build. The rebuilt
bundle is unchanged. No production code or release version changed.

## Reproduction and remaining evidence

See the [experiment instructions](../../experiments/uia-decisions-pilot/README.md).
The first follow-up should raise the experiment walk budget for common dialogs,
then re-record and check completeness; more held-out stock applications and
independent verification cases are required. The current workflow accepts
`acknowledge_ephemeral_runner=true`; it has no walk-budget input, so a longer
budget requires a reviewed recorder change before another captain dispatch.
Do not tune the measured gate on the current held-out apps.

Request schema/confidence follow the official
[Decisions guide](https://developers.openai.com/api/docs/guides/decisions) and
[create reference](https://developers.openai.com/api/reference/resources/decisions/methods/create).
