"""Pin all reachable workflow revisions and expose their review graph."""

import hashlib
import json
from dataclasses import dataclass

from .screen_workflow_files import Checkout, Revision, current_file, load
from .screen_workflow_format import MAX_REPEAT_DEPTH, Step, Use, binding_type, entries
from .screen_workflow_parameters import compatible
from .screen_workflow_plan import MAX_CALL_DEPTH, expand

MAX_BUNDLE_WORKFLOWS = 32


@dataclass(frozen=True)
class Bundle(Revision):
    pieces: dict[str, Revision]
    space: Checkout

    def current(self):
        return all(current_file(self.space, piece) for piece in self.pieces.values())

    def plan(self, supplied):
        return expand(self.workflow, {name: piece.workflow for name, piece in self.pieces.items()}, supplied)

    @property
    def capabilities(self):
        return sorted({
            capability
            for piece in self.pieces.values()
            for entry, _, _ in entries(piece.workflow.steps, piece.workflow.parameters)
            if isinstance(entry, Step)
            for capability in entry.capabilities
        })

    def review(self):
        return {
            "root": self.workflow.name,
            "requires": self.capabilities,
            "pieces": {
                name: {
                    "path": piece.path,
                    "revision": piece.digest,
                    "definition": piece.workflow.model_dump(exclude_none=True, by_alias=True),
                }
                for name, piece in self.pieces.items()
            },
        }


def _hash(parts):
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def load_bundle(space, name):
    pieces, heights = {}, {}

    def visit(current, ancestors):
        if current in ancestors:
            raise ValueError(f"workflow composition cycle at {current}")
        if len(ancestors) > MAX_CALL_DEPTH:
            raise ValueError(f"workflow call depth exceeds {MAX_CALL_DEPTH}")
        if current in heights:
            if len(ancestors) + heights[current][0] > MAX_CALL_DEPTH:
                raise ValueError(f"workflow call depth exceeds {MAX_CALL_DEPTH}")
            return
        if len(pieces) >= MAX_BUNDLE_WORKFLOWS:
            raise ValueError(f"bundle exceeds {MAX_BUNDLE_WORKFLOWS} workflow files")
        try:
            piece = pieces[current] = load(space, current)
        except FileNotFoundError as exc:
            if not ancestors:
                raise
            raise ValueError(f"missing component workflow {current}") from exc
        call_depth = repeat_depth = 0
        for entry, item, depth in entries(piece.workflow.steps, piece.workflow.parameters):
            repeat_depth = max(repeat_depth, depth)
            if not isinstance(entry, Use):
                continue
            for destination, refs in entry.destinations():
                visit(destination, (*ancestors, current))
                calls, repeats = heights[destination]
                call_depth = max(call_depth, 1 + calls)
                repeat_depth = max(repeat_depth, depth + repeats)
                declares = pieces[destination].workflow.parameters
                if refs.keys() != declares.keys() or any(
                    not compatible(binding_type(ref, piece.workflow.parameters, item), declares[key])
                    for key, ref in refs.items()
                ):
                    raise ValueError(f"{current}/{entry.id} has incompatible bindings for {destination}")
        if repeat_depth > MAX_REPEAT_DEPTH:
            raise ValueError(f"repeat nesting across calls exceeds {MAX_REPEAT_DEPTH}")
        heights[current] = call_depth, repeat_depth

    visit(name, ())
    root = pieces[name]
    digest, stamp = root.digest, root.stamp
    if len(pieces) > 1:
        ordered = sorted(pieces.items())
        digest = _hash([name, [(key, value.path, value.digest) for key, value in ordered]])
        stamp = _hash([(key, value.path, value.stamp) for key, value in ordered])
    return Bundle(root.workflow, root.project, root.path, digest, root.checkout, stamp, pieces, space)
