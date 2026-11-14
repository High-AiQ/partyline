"""UI Automation change subscriptions scoped to one explicitly granted window."""
import sys
import threading


PROPERTIES = (30010, 30045, 30086, 30079, 30070, 30005)


def register_handlers(automation, uia, root, changed, com_object):
    """Bind the exact UIA sink methods while keeping handler objects strongly referenced."""
    class PropertyHandler(com_object):
        _com_interfaces_ = [uia.IUIAutomationPropertyChangedEventHandler]

        def HandlePropertyChangedEvent(self, sender, property_id, new_value):
            changed()

    class StructureHandler(com_object):
        _com_interfaces_ = [uia.IUIAutomationStructureChangedEventHandler]

        def HandleStructureChangedEvent(self, sender, change_type, runtime_id):
            changed()

    handlers = []
    properties, structure = PropertyHandler(), StructureHandler()
    try:
        automation.AddPropertyChangedEventHandler(root, 7, None, properties, list(PROPERTIES))
        handlers.append(("property", root, properties))
        automation.AddStructureChangedEventHandler(root, 7, None, structure)
        handlers.append(("structure", root, structure))
    except Exception:
        remove_handlers(automation, handlers)
        raise
    return handlers


def remove_handlers(automation, handlers):
    for kind, root, handler in reversed(handlers):
        if kind == "property":
            automation.RemovePropertyChangedEventHandler(root, handler)
        else:
            automation.RemoveStructureChangedEventHandler(root, handler)


class UIAEventSubscription:
    """Keep the UIA COM handlers alive on a message-pumping apartment thread."""

    def __init__(self, hwnd, changed):
        self.hwnd, self.changed = hwnd, changed
        self.thread = None
        self.ready = threading.Event()
        self.cancelled = threading.Event()
        self.state_lock = threading.Lock()
        self.started = False

    def start(self):
        if sys.platform != "win32":
            return False
        with self.state_lock:
            if self.cancelled.is_set():
                return False
            self.thread = threading.Thread(target=self._run, name="uia-events", daemon=True)
            self.thread.start()
        self.ready.wait(3)
        return self.started

    def _mark_started(self, thread_id, automation, handlers):
        """Publish the message loop only if revocation did not race startup."""
        with self.state_lock:
            if self.cancelled.is_set():
                self.ready.set()
                return False
            self.thread_id, self.automation, self.handlers = thread_id, automation, handlers
            self.started = True
            self.ready.set()
            return True

    def _run(self):  # pragma: no cover - native Windows COM event loop
        import ctypes
        import comtypes
        import comtypes.client
        from ctypes import wintypes

        handlers = []
        user = ctypes.WinDLL("user32", use_last_error=True)
        initialized = False
        user.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM,
                                            wintypes.LPARAM]
        try:
            comtypes.CoInitialize()
            initialized = True
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as uia
            from comtypes import COMObject

            automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
            root = automation.ElementFromHandle(self.hwnd)
            handlers = register_handlers(automation, uia, root, self.changed, COMObject)
            message = wintypes.MSG()
            user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            if not self._mark_started(thread_id, automation, handlers):
                return
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
        except Exception:
            self.ready.set()  # unsupported UIA event registration falls back to bounded snapshots
        finally:
            if "automation" in locals():
                try:
                    remove_handlers(automation, handlers)
                except Exception:
                    pass
            if initialized:
                comtypes.CoUninitialize()

    def close(self):
        with self.state_lock:
            self.cancelled.set()
            thread = self.thread
            thread_id = self.thread_id if self.started else None
        if thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(thread_id, 0x12, 0, 0)
        if thread:
            thread.join(timeout=3)
