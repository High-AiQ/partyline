"""Popup hints from standard ARIA properties, without requiring an explicit widget role."""
import re


def controlled_types(provider, node, aria):
    """Use the native relation, then one cached target index per provider read, never a walk per IDREF."""
    from .uia_windows import TYPES
    targets = provider.prop(node, "ControllerFor")
    kinds = [TYPES.get(provider.prop(targets.GetElement(i), "ControlType"))
             for i in range(min(targets.Length, 32))] if targets else []
    if any(kind in ("List", "Menu") for kind in kinds):
        return kinds
    references = re.findall(r"(?:^|;)\s*(?:aria-)?(?:controls|owns)=([^;]*)", aria, re.IGNORECASE)
    ids = " ".join(references).split()[:32]
    if ids:
        index = getattr(provider, "popup_target_types", None)
        if index is None:
            index = provider.popup_target_types = {}
            automation = provider.automation
            condition = automation.CreateOrCondition(automation.CreatePropertyCondition(30003, 50008),
                                                      automation.CreatePropertyCondition(30003, 50009))
            cache = provider.request(1)  # TreeScope_Element; only List/Menu matches are cached
            targets = provider.root().FindAllBuildCache(4, condition, cache)
            for i in range(min(targets.Length, 2000)):
                target = targets.GetElement(i)
                if provider.same_window(target):
                    index[str(provider.prop(target, "AutomationId"))] = TYPES.get(
                        provider.prop(target, "ControlType"))
        kinds.extend(index[ident] for ident in ids if ident in index)
    return kinds


def uia_popup(props, aria, controlled_types=()):
    attributes = dict(re.findall(r"(?:^|;)\s*([\w-]+)=([^;]*)", aria.lower()))
    popup = attributes.get("haspopup", attributes.get("aria-haspopup"))
    expanded = attributes.get("expanded", attributes.get("aria-expanded"))
    if popup in ("true", "listbox", "menu") or expanded is not None or any(
            kind in ("List", "Menu") for kind in controlled_types):
        props["popup"] = popup or "true"
        if (props.get("control_type") in ("Group", "Pane", "Custom") and
                props.get("aria_role", "") in ("", "generic", "group", "none", "presentation")):
            props["control_type"] = "ComboBox"
        if expanded in ("true", "false"):
            props["expand_state"] = "expanded" if expanded == "true" else "collapsed"
    return props
