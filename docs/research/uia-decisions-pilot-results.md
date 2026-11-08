# Recorded Windows UIA Decisions follow-up

2026-11-08. **A live, gated pilot is not justified.** This follow-up has a
manual Windows recorder and a replay evaluation protocol, but the Windows corpus
has not been collected and Decisions has not been measured against it. No claim
of validated abstention, selective accuracy, coverage or false-success rate is
supported yet. The earlier synthetic results are not evidence for this corpus.

## Evidence status

| Measurement | Recorded Windows result |
| --- | --- |
| Stock application snapshots | Pending captain dispatch |
| Held-out choice accuracy / coverage | Not measured |
| Development-selected abstention threshold | Not selected |
| Held-out 95% error upper bound | Not estimable |
| False success on failed/unchanged after-snapshots | Not measured |
| New Decisions calls / cost | 0 / $0 |

Implementation and reproducible commands are in
[experiments/uia-decisions-pilot](../../experiments/uia-decisions-pilot/README.md).
The recorder reuses the helper's real `WindowAccess` snapshots and
`ActionWorker` actions, without pixel capture or production changes.
Only a disposable hosted runner is accepted. Existing required checks are
unchanged; the new workflow is manual only.

Development applications are Notepad, Calculator when available, and a Tk/native
Win32 fixture. Held-out applications are Character Map and a WinForms family
comprising its fixture and the Open/Save common dialogs. All members of that
family stay held out. The model receives literal intent, actual UIA elements and
snapshot freshness IDs, then chooses an element-id/action pair or abstains.
Recorded properties supply normal, absent, duplicate, disabled, offscreen and
wrong-pattern labels; a changed recorded after-state supplies stale cases.
Missing providers or case categories stay missing. Fixture results must be
distinguished from stock application evidence.

Threshold candidates and the selection rule are fixed before recording. Select
the highest development coverage with zero observed development errors and at
least ten accepted choices after deterministic vetoes; otherwise reject all.
Freeze the development evidence hashes and threshold before requesting held-out
predictions. The validator checks freshness, completeness, target existence,
enabled/onscreen state, action/pattern support and label ambiguity. Report raw,
validator-only and gated results separately, including per-application and
per-case counts.

The error upper bound is one-sided exact binomial at 95%; zero errors among
`n` accepted choices gives `1 - 0.05**(1/n)`. It is 1 when no choices are
accepted. Task-level bounds assume independent trials; controls within the same
application are correlated. These bounds cannot establish safety on unseen apps.

The verification subset uses UIA predicates requiring the target's value to
change from its recorded prior value to a fixed experiment string. The recorder
takes real unchanged, refused-action, and executed-action after-snapshots.
The verifier requires complete before/after evidence and a false-to-true
postcondition transition. Its false-success denominator includes failed and
unknown outcomes. This is a field-state strategy, not proof of save durability,
server consent handling, or broad task completion.

The evaluation driver reuses the previous serialized, journaled harness with its
historical spending ledger, probe cost, $0.50 per-request reserve and $4.50 total
stop. It adds a single fixed state directory, exclusive execution lock, corpus
digest binding and mandatory dev/held-out phase order. Uncertain requests remain
pending and are never automatically retried. The text-arm schema and confidence
field follow the official [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
and [create reference](https://developers.openai.com/api/reference/resources/decisions/methods/create).

## Local validation

All 11 no-network protocol tests pass under the verified 4 GiB cap. Repository
gates passed: Ruff, 4,285 backend tests (29 platform skips), 92% combined line/
branch coverage, source line limits, no-media checks, frontend verification
(786 tests), and the frontend build. These checks validate tooling mechanics;
they do not replace the Windows recording or held-out measurement.

## Required next run

The captain must push the reviewed SHA and dispatch
`.github/workflows/uia-decisions-corpus.yml` on that exact ref with input
`acknowledge_ephemeral_runner=true` (no API secrets or other inputs).
Preserve the resulting `uia-decisions-corpus-<run-id>` JSON/JSONL artifact and run
URL before its 30-day expiry. Availability failures still upload diagnostics;
do not report a failed or partial recording as a complete benchmark.

Then inspect recording integrity, run the documented development phase, preserve
the frozen gate, and run the held-out phase with the same corpus and journal.
Persist the corpus, intents, gate, journal and machine-readable metrics in durable
storage and replace this pending table with measured counts. More held-out stock
applications, richer intents and enough independent verification failures would
still be needed before a defensible decision about a live pilot.
