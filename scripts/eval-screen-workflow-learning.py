"""Opt-in synthetic learner evaluation; never imported by CI and never run in gates."""

import json
import os
import pty
import re
import select
import subprocess
import sys
import tempfile
from pathlib import Path

from partyline.screen_workflow_bundle import load_bundle
from partyline.screen_workflow_files import Checkout

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/screen-workflows"


def proposal_from(output):
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    starts = [index for index, char in enumerate(clean) if char == "{"]
    for start in starts:
        try:
            value, _ = json.JSONDecoder().raw_decode(clean[start:])
            if isinstance(value, dict) and isinstance(value.get("files"), dict):
                return value
        except json.JSONDecodeError:
            continue
    raise ValueError("model output did not contain a JSON object with a files map")


def run_model(command, prompt):
    master, slave = pty.openpty()
    child = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                             start_new_session=True, env=os.environ.copy())
    os.close(slave)
    output = bytearray()
    os.write(master, (prompt + "\n").encode())
    try:
        while child.poll() is None:
            ready, _, _ = select.select([master], [], [], 1)
            if ready:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    break
                if data:
                    output.extend(data)
                    sys.stdout.buffer.write(data)
                    sys.stdout.flush()
    finally:
        os.close(master)
    if child.returncode:
        raise subprocess.CalledProcessError(child.returncode, command)
    return output.decode(errors="replace")


def score(proposal, workspace):
    files = proposal.get("files", {})
    root = proposal.get("workflow")
    if not isinstance(root, str) or not isinstance(files, dict):
        raise ValueError("proposal must include workflow name and files map")
    workflow_dir = workspace / ".partyline/workflows"
    workflow_dir.mkdir(parents=True)
    for name, content in files.items():
        if (not isinstance(name, str) or "/" in name or "\\" in name or
                not name.endswith((".yaml", ".yml")) or not isinstance(content, str)):
            raise ValueError("files must map plain YAML filenames to text")
        (workflow_dir / name).write_text(content)
    held_out = json.loads((FIXTURES / "held-out-learning-inputs.json").read_text())
    demonstration = json.loads((FIXTURES / "synthetic-demonstration.json").read_text())
    bundle = load_bundle(Checkout(workspace, workspace, str(workspace)), root)
    plan = bundle.plan(held_out)
    review = bundle.review()
    serialized = json.dumps(review, ensure_ascii=False)
    observed_names = {target["name"] for call in demonstration["calls"]
                      for target in (call.get("observation") or {}).get("targets", [])}
    repeated_ids = [step_id for step_id, _ in plan if step_id.startswith("module[")]
    observed_scopes = {target["scope"] for call in demonstration["calls"]
                       for target in (call.get("observation") or {}).get("targets", [])
                       if target.get("scope")}
    labels_scoped = all(value in serialized for value in observed_names | observed_scopes)
    unresolved_marked = all("unresolved" in call or call.get("observation")
                            for call in demonstration["calls"])
    publish = next((item for item in plan if item[0].endswith("/publish") or item[0] == "publish"), None)
    confirms_commit = bool(publish and publish[1].confirm)
    inventory = json.loads((FIXTURES / "held-out-target-inventory.json").read_text())
    from partyline.screen_tree import Snapshot
    from partyline.screen_tree_ids import IdSpace
    from partyline.screen_workflow_preview import inspect_plan

    tree = Snapshot("held-out", 0, IdSpace())
    tree.add([{
        "id": node["id"], "control_type": node["role"], "semantic_role": node["role"],
        "name": node["name"], **({"parent": node["parent"]} if "parent" in node else {}),
        **({"value": node["value"]} if "value" in node else {}),
    } for node in inventory["nodes"]])
    preview = inspect_plan(tree, plan)
    all_resolve = all(item["state"] in {"resolved", "not_required"}
                      and all(check["state"] in {"resolved", "not_required"}
                              for check in item["preconditions"])
                      for item in preview)
    repeated_calls = [call for call in demonstration["calls"]
                      if call["index"] in (3, 4, 5)]
    expected_actions = [call["arguments"].get("action") for call in repeated_calls
                        if call["operation"] == "screen_element_action"]
    actual_repeated = [step.action for name, step in plan if name.startswith("module[1]/text-module/")]
    cursor = 0
    for action in actual_repeated:
        if cursor < len(expected_actions) and action == expected_actions[cursor]:
            cursor += 1
    values = [getattr(step.inputs, "value", None) for _, step in plan]
    heldout_mapped = all(value in values for value in (
        held_out["title"], held_out["modules"][0]["headline"],
        held_out["modules"][0]["body"], held_out["modules"][1]["rows"][0]["cells"][0]["text"],
    ))
    return {
        "schema_and_typed_parameters": True,
        "repeated_steps_expand_in_order": (len(repeated_ids) >= len(held_out["modules"])
                                             and repeated_ids == sorted(repeated_ids)
                                             and cursor == len(expected_actions)),
        "observed_labels_and_scopes_preserved": labels_scoped,
        "missing_evidence_unresolved": unresolved_marked,
        "irreversible_step_confirmed": confirms_commit,
        "held_out_read_only_preview_resolves_every_target": all_resolve,
        "held_out_inputs_flow_to_plan": heldout_mapped,
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: eval-screen-workflow-learning.py <interactive-model-command...>")
    demonstration = (FIXTURES / "synthetic-demonstration.json").read_text()
    skill = (ROOT / "skills/learn-screen-workflow/SKILL.md").read_text()
    prompt = model_prompt(demonstration, skill)
    output = run_model(sys.argv[1:], prompt)
    proposal = proposal_from(output)
    with tempfile.TemporaryDirectory(prefix="screen-workflow-eval-") as temporary:
        results = score(proposal, Path(temporary))
    print("\nScoring rules (pass/fail):")
    print(json.dumps(results, indent=2, sort_keys=True))
    print("passed:", sum(results.values()), "/", len(results))
    return 0 if all(results.values()) else 1


def model_prompt(demonstration, skill):
    """Keep held-out inputs private to the deterministic scorer."""
    return ("Use the procedure to propose a complete workflow bundle. Return one JSON object only: "
            '{"workflow":"root-name","files":{"root-name.yaml":"...",'
            '"component.yaml":"..."}}. Include every component file. Do not approve or run actions.\n\n'
            + skill + "\n\nSynthetic demonstration:\n" + demonstration)


if __name__ == "__main__":
    raise SystemExit(main())
