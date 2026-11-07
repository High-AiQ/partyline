# Offline Decisions pilot

From the repository root, run `uv run --locked python experiments/decisions-pilot/generate.py`.
The generator uses Pillow and writes synthetic PNGs and labels to `generated/`.
The development and held-out templates have different task content and layouts.
Run the integrity check with `./scripts/capped-test -- uv run --locked python
experiments/decisions-pilot/test_dataset.py`.

`run.py` sends synthetic evidence to OpenAI and incurs charges. Read its budget and
journal handling first. It seeds its generated journal from the committed
`responses.jsonl`, which retains the first (invalid split) run, the interrupted
request reserve, and the revised run. Keys prefixed `v2-` are the revised dataset.
A pending request must be reconciled before rerunning. The probe is in `probe.json`.
Run `analyze.py` after generation to summarize the revised held-out results. The
harness is a research artifact, not an action executor.

`actor.py` requires the upstream GUI-Actor package and compatible dependencies,
a CUDA-capable PyTorch installation, and the specified checkpoint. The run used
GUI-Actor commit `23f27214d5043bc79dce3523af030364aadc4a0e`, Transformers 4.51.3,
and eager attention. Its output is `actor-results.json`; the invalid first run is
retained as `legacy-actor-results.json`. Model weights are not in this repository.
`legacy_generate.py` reproduces the first dataset, whose split was invalid.
