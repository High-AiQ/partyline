# Offline Decisions pilot

2026-11-07. On this exploratory synthetic replay, both Decisions arms met the
numerical target for accepted choices and compact-state p95. The local grounder
missed the choice target, and real application diversity remains an open question;
these small samples do not establish safety. A live cascade pilot is not yet justified without stronger
held-out applications, a separately validated abstention gate and a verification
strategy.

## Data and method

`experiments/decisions-pilot/generate.py` creates 200 synthetic 800×600 PNGs
and 60 before/after pairs, with source-derived candidate bounds. Ten application
and task templates are assigned to each split: 100 choices and 30 verification
pairs apiece. Development uses horizontal control rows; held-out templates use
vertical stacks, split columns and L-shaped layouts, with different task labels,
field names and values. Target position is shuffled. A capped no-wait integrity
check regenerates the data and checks disjoint templates, candidate-name sets,
actual control geometries and verification fields, all three target positions,
cases and labels. Examples include settings, forms, dialogs, missing and duplicate
targets, explicitly marked
stale snapshots, popups and adversarial text. No real desktop data or actions were
used.

The first run's split was invalid: its held-out examples replicated development
layouts and tasks with topic names changed. Those measurements are **excluded**
from the tables below, but its generator, responses, local results and charges are
retained for audit. The revised split is stronger, yet still synthetic and highly
regular: the same drawing code, three controls, explicit stale flag and verification
status notes recur across templates. It is not a benchmark of real applications.

Text and image choices share intent and candidates; the latter also receives the
frame. Choice includes abstain. Separate image-plus-structured-state predicates
judge verification; probability >= 0.5 means success. The primary choice results
use no confidence threshold. The threshold rows are post-hoc descriptions, not a
threshold selected on development data. A permutation rerun included 40 held-out
examples per arm: 10 each of normal, absent, duplicate and stale; seeded shuffling
may leave some orders unchanged. Client wall time includes network and upload and
excludes image generation, capture, execution and settling. Percentiles use the
nearest indexed observation.

## Revised held-out results

| Arm | Accepted / total | Correct accepted | Coverage | p50 / p95 ms |
| --- | ---: | ---: | ---: | ---: |
| Decisions text | 70 / 100 | 70 / 70 (100%) | 70% | 241 / 424 |
| Decisions text + image | 65 / 100 | 65 / 65 (100%) | 65% | 285 / 552 |
| GUI-Actor-2B | 90 / 100 | 70 / 90 (77.8%) | 90% | 185 / 186 |

Both Decisions arms met >=95% accepted accuracy at >=60% coverage and had p95
under 750 ms on this set. GUI-Actor missed the accuracy target. Even zero errors
in 65 accepts has a rough 95% upper error bound of 4.6% by the rule of three. These measurements do not establish
accuracy at a lower error rate.

Selective error versus coverage (confidence threshold among non-abstentions;
denominator is 100 examples):

| Minimum confidence | Text accepted, errors | Image accepted, errors |
| ---: | ---: | ---: |
| 0 | 70, 0 | 65, 0 |
| 0.50 | 70, 0 | 63, 0 |
| 0.70 | 70, 0 | 60, 0 |
| 0.80 | 70, 0 | 60, 0 |
| 0.90 | 67, 0 | 60, 0 |
| 0.95 | 65, 0 | 55, 0 |
| 0.99 | 51, 0 | 53, 0 |

Confidence reliability includes abstain choices and scores correctness of the
selected label. Brier scores `(confidence - correct)^2` are 0.018002 text and
0.026640 image. This treats the API's confidence as a correctness probability,
which should be interpreted cautiously. Bins are left-inclusive, with 1 in the
final bin; the table gives count, mean confidence, and correct / count.

| Confidence bin | Text | Image |
| --- | --- | --- |
| 0–0.2 | 0, —, — | 3, 0.137, 0/3 |
| 0.2–0.4 | 1, 0.330, 1/1 | 2, 0.300, 1/2 |
| 0.4–0.6 | 2, 0.490, 2/2 | 4, 0.505, 3/4 |
| 0.6–0.8 | 5, 0.650, 5/5 | 9, 0.670, 9/9 |
| 0.8–1 | 92, 0.973, 92/92 | 82, 0.967, 82/82 |

Candidate permutations changed 1/40 choices in each Decisions arm; this subset
is too small to establish order invariance. Verification produced 0/20 false
successes on failed or unknown outcomes and detected 10/10 successes; p50/p95
was 303/607 ms. A deterministic check of the synthetic field and completion
note also classified 30/30 correctly. These explicit notes make the comparison
easy. The zero-false-success target was observed here only; the rule-of-three
upper error bound is about 15% for 20 non-success cases.

Out-of-region actions, revocation, irreversible actions, screenshot reduction,
matched task time and task success were **not measured**, so the live targets
cannot be assessed. Jev was skipped because no TypeSafe key was available; no
account was created.

## Usage

Both runs and the probe are included. The journal has 1,039 responses plus one
interrupted request; a separate 162-input-token schema probe brings known usage to
624,422 input tokens, including 123,510 cache-write and zero cache-read tokens,
and zero output tokens. With the documented default 30-minute write rate and no
regional premium, known estimated cost is **$0.06552995**. One first-run request
was interrupted by a restart and its actual cost is unknown; it was not retried.
Adding its full $0.50 reserve gives **$0.56552995**. The harness's conservative
tally is **$0.6561055**, pricing all known tokens at the higher 12-hour write rate.
These are estimates, not invoice amounts. The serialized harness journals before
sending, reserves $0.50 for the next request, and stops before its conservative
tally plus that reserve exceeds $4.50. It seeds a new journal from the committed
ledger so the first run's charges are not lost. An unresolved pending request
blocks further calls. [OpenAI Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
and [create reference](https://developers.openai.com/api/reference/resources/decisions/methods/create)
define schema and usage fields.

## Local model

The exact [GUI-Actor-2B checkpoint](https://huggingface.co/microsoft/GUI-Actor-2B-Qwen2-VL)
ran on the RTX 4090 in BF16, batch one, using upstream GUI-Actor commit
`23f27214d5043bc79dce3523af030364aadc4a0e` and checkpoint revision
`8f87b366d004425a9823502553e2097c71116ece`. The upstream FlashAttention dependency
failed to build in the Python 3.13 environment, so inference used eager attention;
this affects latency. Warm-cache model loading took 1.67 seconds; peak reserved
CUDA memory during inference was 5.72 GiB. A predicted point was accepted only
when it fell inside exactly one listed bound. The model received intent and image,
not the explicit stale-state flag. It accepted all ten duplicate-label cases and
five of ten stale cases even though those required abstention. On missing targets,
it accepted five of ten points. No confidence calibration or candidate-order
sensitivity was measured for this point model. It provides a single 90%-coverage,
20/90-error operating point, not a selective curve. Full points and times are in
`actor-results.json`.
