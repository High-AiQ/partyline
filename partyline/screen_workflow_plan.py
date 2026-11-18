"""Expand typed workflow calls and repeats before any screen input."""

from .screen_workflow_format import Repeat, Step, Use, bind, bound_value
from .screen_workflow_parameters import validate_input

MAX_EXPANDED_STEPS = 4096
MAX_EXPANSION_ENTRIES = 16384
MAX_CALL_DEPTH = 4


def inputs(workflow, supplied):
    if supplied.keys() != workflow.parameters.keys():
        raise ValueError(f"{workflow.name}: supply exactly the declared parameters")
    return {
        name: validate_input(spec, supplied[name])
        for name, spec in workflow.parameters.items()
    }


def expand(root, workflows, supplied):
    result = []
    visited = 0

    def walk(entries, parameters, item=None, prefix="", indexes=""):
        nonlocal visited
        for entry in entries:
            visited += 1
            if visited > MAX_EXPANSION_ENTRIES:
                raise ValueError(f"plan expansion exceeds {MAX_EXPANSION_ENTRIES} entries")
            if isinstance(entry, Repeat):
                values = parameters[entry.for_each] if isinstance(entry.for_each, str) else bind(
                    entry.for_each, parameters, item
                )
                for index, value in enumerate(values, 1):
                    walk(entry.steps, parameters, value, prefix, indexes + f"[{index}]")
                continue
            step_id = prefix + entry.id + indexes
            if isinstance(entry, Use):
                refs = entry.with_
                name = entry.use
                if not isinstance(name, str):
                    choice = item[name.by]
                    name = name.cases[choice]
                    refs = {**refs, **entry.case_bindings.get(choice, {})}
                if name not in workflows:
                    raise ValueError(f"{step_id} references an unavailable workflow")
                child = workflows[name]
                values = {key: bound_value(ref, parameters, item) for key, ref in refs.items()}
                walk(child.steps, inputs(child, values), prefix=f"{step_id}/{name}/")
            else:
                if len(result) >= MAX_EXPANDED_STEPS:
                    raise ValueError(f"expanded plan exceeds {MAX_EXPANDED_STEPS} steps")
                result.append((step_id, Step.model_validate(bind(entry, parameters, item))))

    walk(root.steps, inputs(root, supplied))
    if not result:
        raise ValueError("a run requires at least one expanded step")
    return result
