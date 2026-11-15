"""Whether the keyboard focus sits in a password field, asked of UI Automation. Windows only."""


def focused_password(user, scope):  # pragma: no cover - Windows only
    """True when the focused element is a password field, False when it is not, None when it cannot be told
    (UI Automation failed, or the focus is not inside the granted window's own process)."""
    try:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as uia
        automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
        element = automation.GetFocusedElement()
        if element is None or element.CurrentProcessId != scope.pid:
            return None
        return bool(element.CurrentIsPassword)
    except Exception:  # noqa: BLE001 - COM raises its own errors; whatever fails, the answer is "cannot tell"
        return None
