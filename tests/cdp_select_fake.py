"""Model native popup preview separately from committed selection and trusted changes."""
from partyline_helper.cdp_recipes import SELECT_PLAN
from partyline_helper.cdp_select import BLUR, STATUS, UNWATCH, WATCH


class NativeSelect:
    blur = BLUR

    def __init__(self, socket):
        self.socket = socket
        self.mode, self.open, self.highlight = "native", False, None
        self.watches = {}
        self.navigate_on_change = False
        self.committed_values = []

    def enabled(self):
        return [i for i, option in enumerate(self.socket.options) if not option.get("disabled")]

    def function(self, backend, params):
        recipe, args = params["functionDeclaration"], params["arguments"]
        state = self.socket.states[backend]
        token = args[0]["value"] if args else None
        if recipe == SELECT_PLAN:
            matches = [i for i, o in enumerate(self.socket.options) if token in (o["label"], o["value"])]
            if len(matches) != 1 or matches[0] not in self.enabled():
                return {"error": "option missing, disabled or ambiguous"}
            index, current = matches[0], state["selected_index"]
            down = index > current
            steps = len([i for i in self.enabled() if current < i <= index or index <= i < current])
            return dict(index=index, current=current, label=self.socket.options[index]["label"],
                        direction="ArrowDown" if down else "ArrowUp", steps=steps,
                        popup=state.get("popup", True))
        if recipe == WATCH:
            self.watches[token] = len(self.socket.input_events)
        elif recipe == UNWATCH:
            self.watches.pop(token, None)
        elif recipe == STATUS:
            events = self.socket.input_events[self.watches[token]:]
            return dict(index=state["selected_index"], count=state["selected_count"], open=self.open,
                        trusted_input_events=events.count(("input", True)),
                        trusted_change_events=events.count(("change", True)))
        elif recipe == BLUR:
            self.open = False
        return {}

    def commit(self, state, index):
        if index != state["selected_index"]:
            state.update(selected_index=index, selected_count=1, value=self.socket.options[index]["value"])
            self.socket.input_events.extend([("input", True), ("change", True)])
            self.committed_values.append(state["value"])
            if self.navigate_on_change:
                self.socket.event("Page.frameNavigated", frame={"id": "main"})

    def key(self, params):
        state = self.socket.states.get(self.socket.focused, {})
        if state.get("tag") != "SELECT":
            return
        name = params["key"]
        if name == "ArrowDown" and params["modifiers"] == 1:
            if self.mode != "unsupported":
                self.open, self.highlight = True, state["selected_index"]
            return
        if self.open:
            if self.mode == "ignored_all" or self.mode == "ignored" and name != "Escape":
                return
            if name == "Escape":
                self.open = False
            elif name == "Enter":
                self.commit(state, self.highlight)
                self.open = False
            elif name in ("ArrowDown", "ArrowUp"):
                choices = [i for i in self.enabled() if i > self.highlight] if name == "ArrowDown" else [
                    i for i in self.enabled() if i < self.highlight]
                if choices:
                    self.highlight = min(choices) if name == "ArrowDown" else max(choices)
                    if self.mode == "premature":
                        self.commit(state, self.highlight)
        elif name in ("ArrowDown", "ArrowUp"):
            choices = [i for i in self.enabled() if i > state["selected_index"]] if name == "ArrowDown" else [
                i for i in self.enabled() if i < state["selected_index"]]
            if choices:
                self.commit(state, min(choices) if name == "ArrowDown" else max(choices))
