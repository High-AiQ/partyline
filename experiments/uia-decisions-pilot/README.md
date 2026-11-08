# Recorded Windows UIA Decisions follow-up

Status: collection and evaluation tooling, **not measured results**. Do not substitute
synthetic examples when a stock app or the interactive desktop is unavailable.
No screenshots, pixel capture, personal desktop, service connection, or API key is
needed for collection. Required CI checks are unchanged.

## Capture (captain dispatches)

Push the reviewed commit, then dispatch `.github/workflows/uia-decisions-corpus.yml`
on that exact ref with `acknowledge_ephemeral_runner=true`. Only `workflow_dispatch`
can start it. It runs on GitHub-hosted `windows-latest`, refuses other environments,
and uploads `uia-decisions-corpus-<run-id>` (JSON and JSONL only, 30-day retention).
Download and preserve that artifact before expiry; retain its run URL and commit.

The equivalent runner command is:

```powershell
uv run --locked --extra helper python experiments/uia-decisions-pilot/record.py --ephemeral-runner --output corpus
```

The script launches Notepad, Calculator, Character Map, a Tk/native-Win32 fixture,
a WinForms fixture, and the Open/Save common dialogs. Calculator may be absent or
brokered into another process: it is reported unavailable rather than selecting
an unrelated existing window. Each isolated worker selects only a window owned
by its launched process tree. A separate observer uses the existing window
enumerator (which otherwise hides its own descendants). Each selected window gets
a local marker, `WindowAccess.choose/snapshot` supplies the same
`screen_elements` schema, and the grant is revoked after recording.
No screenshot path is imported or called. Process cleanup uses owned PIDs.

The workflow explicitly opts into access on the disposable runner; it does not
exercise the interactive human picker, the server transport, or pixel sharing.
`ActionWorker.perform` supplies the existing dispatch barrier, timeout, live
identity/pattern checks, and durable experiment audit, with a local runner-only
session grant. No production consent bypass is added. No file-save, registry,
service, system-setting, or calculator button actions are executed. Only a bounded
`set_value` on an editable control and an intentionally refused unknown-id call
are attempted; neither action is retried.

An unavailable/truncated provider remains visible in the artifact. Collection
exits nonzero for missing apps; the artifact upload still runs. Read the
per-application records before evaluating a partial corpus. A timeout kills the
owned recorder/app tree; never treat it as a successful recording.

## Application split and tasks

The split is fixed in `protocol.py` before collection:

| Development | Held out |
| --- | --- |
| Notepad, Calculator, Tk/native-Win32 fixture | Character Map, WinForms fixture, Open and Save dialogs |

The WinForms fixture and both common dialogs form one family, entirely held out.
Do not move an unavailable app between splits. Development receives no held-out
responses during threshold selection. Fixtures are known challenge applications,
so stock-app results must also be inspected separately; this does not establish
generalization to arbitrary unseen Windows software.

Tasks are literal, prewritten intent rules instantiated from the **recorded**
element names and types, with at most 12 normal controls per app. The resulting
intents and gold element-id/action pairs are in `dataset.json`; labels, cases and
splits never enter model evidence. This tests grounding under explicit wording,
not natural-language diversity. Absent targets, duplicate labels, disabled,
offscreen, incompatible Toggle, and actually changed before/after snapshots
require abstention. Cases that a real provider omits are reported missing rather
than fabricated. A stale task presents the earlier snapshot and the actual later
snapshot ID; that is an observable freshness signal, not a hidden staleness
inference benchmark. Normal tasks represent the instant of the original snapshot.

The text arm receives intent, the recorded snapshot, and latest snapshot ID. Choice
values encode both element ID and action; incompatible pairs are retained so the
model must abstain on wrong-pattern cases. The deterministic validator rejects
unknown IDs, changed snapshot IDs, truncated evidence, disabled/offscreen targets,
missing action/patterns, and ambiguous type/name pairs. This offline validator
cannot establish current application state on a real desktop; production still
needs its own live revalidation.

## Evaluate (after preserving and inspecting the Windows artifact)

From the repository root, with `OPENAI_API_KEY` set:

```sh
uv run --locked python experiments/uia-decisions-pilot/run.py --corpus PATH/TO/dataset.json --phase dev
uv run --locked python experiments/uia-decisions-pilot/run.py --corpus PATH/TO/dataset.json --phase heldout
```

These commands incur charges. Do not start concurrent copies or reset generated
state. The driver reuses `../decisions-pilot/run.py`'s serialized call function,
historical ledger/probe charge, $0.50 request reserve, $4.50 stop, and pending-call
journal. It flushes the pending intent to disk before HTTP, uses one fixed `generated/` state directory, an exclusive process lock,
and binds that ledger to the corpus digest. The original historical reserve is
included; this is not a fresh $4.50 allowance. Failure leaves `pending.json` and
blocks all further calls. Never delete a pending file to retry an uncertain call.
Reconcile actual usage and account for its reserve before any continuation.
A crash may also leave `evaluation.lock`; inspect both files before removing a
stale lock. Preserve the full journal when moving the study.

Development freezes `gate.json` before any held-out requests: select the threshold
with most accepts among 0, .5, .7, .8, .9, .95, .99 that has zero development
errors and at least ten accepts after deterministic vetoes (ties use the lower
threshold). Otherwise freeze reject-all at 1.01. This is an empirical calibration
rule, not a safety guarantee. Held-out execution verifies the development evidence
hashes and gate, then writes raw, validator-only and frozen-gate metrics to
`generated/results.json`. Missing responses count against coverage. Refusals and
malformed responses abstain. Missing case/app counts remain visible.

Metrics include accepted accuracy, coverage, errors, one-sided exact 95% binomial
error upper bounds, and per-app/per-case results. Zero accepts gives no accuracy
estimate and an error upper bound of 1. Tasks in one application are correlated;
these task-level bounds assume independence and are **not** application-level
safety bounds. Do not tune on the held-out table.

Verification is deterministic UIA predicate replay. Where Value is exposed, record
a genuine unchanged second read, an after-read following a refused unknown-id
action, and an after-read following a real `set_value` via `ActionWorker`.
The postcondition identifies the same element and requires
`value == "uia-corpus-complete"`. Completion requires available, complete before
and after trees, the observed property before dispatch, and a false-to-true
transition. Report false successes over all failed/unknown pairs and their 95%
upper bound, plus detected successes. These test visible field state only, not
durable saving or broader task completion. No model verification API calls are
needed for this deterministic strategy.

## Integrity checks

```sh
./scripts/capped-test -- uv run --locked python experiments/uia-decisions-pilot/test_protocol.py
```

These no-network tests use small in-memory snapshots only to check protocol
mechanics. They are not corpus recordings or benchmark measurements. They cover
vetoes, application split, dev-only calibration, uncertainty/budget handling,
evidence/label separation, corpus binding, phase order, confidence parsing and
verification transitions. Repository gates still apply before committing.

Retain reviewed recording JSON, generated intents, gate, full spending journal and
results in durable storage, then update the research report. No live pilot is
justified by this tooling alone.
