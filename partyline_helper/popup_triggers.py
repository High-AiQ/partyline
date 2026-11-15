"""Popup hints from standard ARIA properties, without requiring an explicit widget role."""
import re


def controlled_types(provider, node, aria):
    """ControllerFor is the native relation; an ARIA IDREF can also name an AutomationId in this grant."""
    from .uia_windows import TYPES
    targets = provider.prop(node, "ControllerFor")
    kinds = [TYPES.get(provider.prop(targets.GetElement(i), "ControlType"))
             for i in range(min(targets.Length, 32))] if targets else []
    if any(kind in ("List", "Menu") for kind in kinds):
        return kinds
    references = re.findall(r"(?:^|;)\s*(?:aria-)?(?:controls|owns)=([^;]*)", aria, re.IGNORECASE)
    ids = " ".join(references).split()[:32]
    if ids:
        cache = provider.request(1)  # TreeScope_Element
        for ident in ids:
            condition = provider.automation.CreatePropertyCondition(30011, ident)  # AutomationId
            target = provider.root().FindFirstBuildCache(4, condition, cache)  # Descendants, within grant
            if target and provider.same_window(target):
                kinds.append(TYPES.get(provider.prop(target, "ControlType")))
    return kinds


def uia_popup(props, aria, controlled_types=()):
    attributes = dict(re.findall(r"(?:^|;)\s*([\w-]+)=([^;]*)", aria.lower()))
    popup = attributes.get("haspopup", attributes.get("aria-haspopup"))
    expanded = attributes.get("expanded", attributes.get("aria-expanded"))
    if popup in ("true", "listbox", "menu") or expanded is not None or any(
            kind in ("List", "Menu") for kind in controlled_types):
        if props.get("control_type") in ("Button", "Group", "Pane", "Custom", "Edit", "ComboBox"):
            props.update(control_type="ComboBox", popup=popup or "true")
            if expanded in ("true", "false"):
                props["expand_state"] = "expanded" if expanded == "true" else "collapsed"
    return props
