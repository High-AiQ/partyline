"""Version 1 workflow format and deterministic expansion to a typed action plan."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from .screen_workflow_parameters import (
    EnumParameter,
    Label,
    ListParameter,
    MediaList,
    MediaParameter,
    Parameter,
    RecordItem,
    Slug,
    Strict,
    Text,
    WorkflowName,
    check_depth,
)

MAX_DECLARED_STEPS = 128
MAX_REPEAT_DEPTH = 4
Capability = Literal["uia", "cdp", "cdp.set_files"]


class Param(Strict):
    param: Slug


class Item(Strict):
    item: Slug | Literal[True]


Binding = Param | Item


class Scope(Strict):
    role: Slug
    name: Label | Binding


class Target(Scope):
    within: Scope | None = None
    ordinal: int | None = Field(default=None, ge=1, le=100)
    match_count: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def ordinal_scope(self):
        if self.ordinal is None and self.match_count is None:
            return self
        if self.within is None or self.ordinal is None or (self.match_count or 0) < self.ordinal:
            raise ValueError("an ordinal requires a named scope and expected match_count")
        return self


class Check(Strict):
    check: Literal["present", "absent", "value_equals", "notice_text", "file_count_equals"]
    target: Target | Literal["step_target"] = "step_target"
    expected: Text | Binding | Annotated[int, Field(ge=0, le=10)] | None = None
    requires: list[Capability] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def expectation(self):
        if self.check in ("present", "absent"):
            valid = self.expected is None
        elif self.check == "file_count_equals":
            valid = type(self.expected) is int and "cdp.set_files" in self.requires
        else:
            valid = isinstance(self.expected, (str, Param, Item))
        if not valid:
            raise ValueError("check requires an expectation and capabilities appropriate to its kind")
        return self


class Postcondition(Check):
    timeout_ms: int = Field(ge=1, le=60000)


class Inputs(Strict):
    value: Text | Binding | None = None
    files: MediaList | Binding | None = None


class Step(Strict):
    id: Slug
    target: Target
    action: Literal["invoke", "set_value", "select", "set_files"]
    inputs: Inputs = Field(default_factory=Inputs)
    requires: list[Capability] = Field(default_factory=list, max_length=3)
    preconditions: list[Check] = Field(default_factory=list, max_length=10)
    postcondition: Postcondition
    confirm: bool
    effect: Label | None = None
    allow_point: bool = False

    @model_validator(mode="after")
    def action_inputs(self):
        if self.confirm and not self.effect:
            raise ValueError("confirmation requires an effect description")
        fields = {key for key, value in self.inputs.model_dump().items() if value is not None}
        if self.action == "set_files":
            if "cdp.set_files" not in self.requires or fields != {"files"}:
                raise ValueError("set_files requires cdp.set_files and a media list")
        else:
            allowed = {"value"} if self.action in ("set_value", "select") else set()
            if fields - allowed or (self.action == "set_value" and not fields):
                raise ValueError("inputs do not match the action")
            if self.action == "select" and self.target.role == "combobox" and self.inputs.value in (None, ""):
                raise ValueError("select on a combobox requires a nonempty option")
        if "uia" in self.capabilities and self.capabilities.intersection({"cdp", "cdp.set_files"}):
            raise ValueError("a step cannot require both UIA and CDP")
        return self

    @property
    def capabilities(self):
        checks = [*self.preconditions, self.postcondition]
        return set(self.requires).union(*(check.requires for check in checks))


class DispatchBy(Strict):
    by: Slug
    cases: dict[Text, WorkflowName] = Field(min_length=1, max_length=50)


class Use(Strict):
    id: Slug
    use: WorkflowName | DispatchBy
    with_: dict[Slug, Binding] = Field(default_factory=dict, max_length=32, alias="with")
    case_bindings: dict[Text, dict[Slug, Binding]] = Field(default_factory=dict, max_length=50)

    def destinations(self):
        if isinstance(self.use, str):
            return [(self.use, self.with_)]
        return [
            (name, {**self.with_, **self.case_bindings.get(choice, {})})
            for choice, name in self.use.cases.items()
        ]


class Repeat(Strict):
    for_each: Slug | Binding
    steps: list[Entry] = Field(min_length=1, max_length=MAX_DECLARED_STEPS)


Entry = Step | Use | Repeat
Repeat.model_rebuild()


def bindings(value):
    if isinstance(value, (Param, Item)):
        yield value
    elif isinstance(value, Strict):
        for field in type(value).model_fields:
            yield from bindings(getattr(value, field))
    elif isinstance(value, list):
        for entry in value:
            yield from bindings(entry)


def bound_value(ref, parameters, item):
    if isinstance(ref, Param):
        return parameters[ref.param]
    return item if ref.item is True else item[ref.item]


def bind(value, parameters, item=None):
    if isinstance(value, (Param, Item)):
        return bound_value(value, parameters, item)
    if isinstance(value, Strict):
        return {field: bind(getattr(value, field), parameters, item) for field in type(value).model_fields}
    if isinstance(value, list):
        return [bind(entry, parameters, item) for entry in value]
    return value


def binding_type(ref, parameters, item):
    if isinstance(ref, Param):
        return parameters.get(ref.param)
    if ref.item is True:
        return item
    return item.fields.get(ref.item) if isinstance(item, RecordItem) else None


def check_bindings(step, parameters, item):
    files = step.inputs.files
    for ref in bindings(step):
        decl = binding_type(ref, parameters, item)
        if ref is files:
            if not isinstance(decl, ListParameter) or not isinstance(decl.items, MediaParameter):
                raise ValueError(f"{step.id} files must bind a list of media IDs")
        elif decl is None or isinstance(decl, (MediaParameter, ListParameter, RecordItem)):
            raise ValueError(f"{step.id} requires a declared text binding")


def entries(steps, parameters, item=None, depth=0):
    """Yield authored leaves together with their lexical item declaration."""
    for entry in steps:
        if isinstance(entry, Repeat):
            if depth >= MAX_REPEAT_DEPTH:
                raise ValueError(f"repeat nesting exceeds {MAX_REPEAT_DEPTH}")
            decl = (
                parameters.get(entry.for_each) if isinstance(entry.for_each, str)
                else binding_type(entry.for_each, parameters, item)
            )
            if not isinstance(decl, ListParameter):
                raise ValueError("for_each requires a declared list")
            yield from entries(entry.steps, parameters, decl.items, depth + 1)
        else:
            yield entry, item, depth


def check_use(entry, parameters, item):
    if isinstance(entry.use, DispatchBy):
        spec = binding_type(Item(item=entry.use.by), parameters, item)
        if not isinstance(spec, EnumParameter) or entry.use.cases.keys() != set(spec.choices):
            raise ValueError(f"{entry.id} cases must exactly cover the item enum")
        if entry.case_bindings.keys() - entry.use.cases.keys():
            raise ValueError(f"{entry.id} bindings name an unknown case")
    elif entry.case_bindings:
        raise ValueError(f"{entry.id} case_bindings requires enum dispatch")
    for _, refs in entry.destinations():
        if any(binding_type(ref, parameters, item) is None for ref in refs.values()):
            raise ValueError(f"{entry.id} requires declared parameter or item bindings")


class Workflow(Strict):
    version: Literal[1]
    name: WorkflowName
    description: Label
    use_when: Label
    parameters: dict[Slug, Parameter] = Field(default_factory=dict, max_length=32)
    steps: list[Entry] = Field(min_length=1, max_length=MAX_DECLARED_STEPS)

    @model_validator(mode="after")
    def references(self):
        for spec in self.parameters.values():
            check_depth(spec)
        seen = set()
        for entry, item, _ in entries(self.steps, self.parameters):
            if entry.id in seen or len(seen) >= MAX_DECLARED_STEPS:
                raise ValueError(f"step IDs must be unique and limited to {MAX_DECLARED_STEPS}")
            seen.add(entry.id)
            (check_use if isinstance(entry, Use) else check_bindings)(entry, self.parameters, item)
        return self

    def plan(self, supplied):
        from .screen_workflow_plan import expand

        return expand(self, {self.name: self}, supplied)


def workflow_name(value):
    return TypeAdapter(WorkflowName).validate_python(value)
