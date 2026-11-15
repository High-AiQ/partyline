"""Extra live pattern state, read only for action targets."""
EXPAND_STATES = {0: "collapsed", 1: "expanded", 2: "partial", 3: "leaf"}
WINDOW_STATES = {0: "normal", 1: "maximized", 2: "minimized"}


class PatternState:
    def state(self, node, props):
        """Add the state the extra patterns expose, for an action target only (never a snapshot)."""
        try:
            self.pattern_state(node, props["patterns"], props)
        except Exception:  # a misbehaving provider only loses extra state; actions then fail closed
            pass

    def pattern_state(self, node, patterns, result):
        if "SelectionItem" in patterns and "selected" not in result:
            result["selected"] = bool(self.pattern(node, 10010, "SelectionItem").CurrentIsSelected)
        if "ExpandCollapse" in patterns and "expand_state" not in result:
            state = self.pattern(node, 10005, "ExpandCollapse").CurrentExpandCollapseState
            result["expand_state"] = EXPAND_STATES.get(int(state), "unknown")
        if "RangeValue" in patterns:
            pattern = self.pattern(node, 10003, "RangeValue")
            result.update(range_value=pattern.CurrentValue, range_min=pattern.CurrentMinimum,
                          range_max=pattern.CurrentMaximum, range_read_only=bool(pattern.CurrentIsReadOnly))
        if "Scroll" in patterns:
            pattern = self.pattern(node, 10004, "Scroll")
            result.update(h_scrollable=bool(pattern.CurrentHorizontallyScrollable),
                          v_scrollable=bool(pattern.CurrentVerticallyScrollable),
                          h_scroll_percent=pattern.CurrentHorizontalScrollPercent,
                          v_scroll_percent=pattern.CurrentVerticalScrollPercent)
        if "Window" in patterns:
            pattern = self.pattern(node, 10009, "Window")
            result.update(can_minimize=bool(pattern.CurrentCanMinimize),
                          can_maximize=bool(pattern.CurrentCanMaximize),
                          window_state=WINDOW_STATES.get(int(pattern.CurrentWindowVisualState), "unknown"))
        if "Transform" in patterns:
            pattern = self.pattern(node, 10016, "Transform")
            result.update(can_move=bool(pattern.CurrentCanMove), can_resize=bool(pattern.CurrentCanResize))
