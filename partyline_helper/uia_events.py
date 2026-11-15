"""UI Automation change subscriptions scoped to one explicitly granted window."""
import sys
import threading


PROPERTIES = (30010, 30045, 30086, 30079, 30070, 30005, 30101, 30102, 30096)


RUNTIME_ID = 30000


def event_cache(automation):
    """Cache the sender's runtime id, so a handler names its source without a COM call."""
    try:
        request = automation.CreateCacheRequest()
        request.AddProperty(RUNTIME_ID)
        return request  # the default scope is the element itself; UIA forbids a parent scope here
    except Exception:
        return None  # events stay valid; their sources are then unplaced


def source_of(sender):
    """The sender's runtime id from the event's cache; None when it holds none."""
    try:
        return tuple(sender.GetCachedPropertyValue(RUNTIME_ID))
    except Exception:
        return None


def register_handlers(automation, uia, root, changed, com_object, accepts=lambda sender: True,
                      structure_only=False, cache=None):
    """Bind the exact UIA sink methods while keeping handler objects strongly referenced."""
    def notify(sender):
        source = source_of(sender) if cache is not None else None
        if source is None:
            changed()
        else:
            changed(source)

    class PropertyHandler(com_object):
        _com_interfaces_ = [uia.IUIAutomationPropertyChangedEventHandler]

        def HandlePropertyChangedEvent(self, sender, property_id, new_value):
            if accepts(sender):
                notify(sender)

    class StructureHandler(com_object):
        _com_interfaces_ = [uia.IUIAutomationStructureChangedEventHandler]

        def HandleStructureChangedEvent(self, sender, change_type, runtime_id):
            if accepts(sender):
                notify(sender)

    def add(request):
        handlers = []
        properties, structure = PropertyHandler(), StructureHandler()
        try:
            if not structure_only:
                automation.AddPropertyChangedEventHandler(root, 7, request, properties, list(PROPERTIES))
                handlers.append(("property", root, properties))
            automation.AddStructureChangedEventHandler(root, 7, request, structure)
            handlers.append(("structure", root, structure))
        except Exception:
            remove_handlers(automation, handlers)
            raise
        return handlers

    try:
        return add(cache)
    except Exception:
        if cache is None:
            raise
        cache = None  # a provider that refuses cached events still reports them, unplaced
        return add(None)


def remove_handlers(automation, handlers):
    for kind, root, handler in reversed(handlers):
        if kind == "property":
            automation.RemovePropertyChangedEventHandler(root, handler)
        else:
            automation.RemoveStructureChangedEventHandler(root, handler)


class UIAEventSubscription:
    """Keep the UIA COM handlers alive on a message-pumping apartment thread."""

    def __init__(self, hwnd, changed, structure_only=False):
        self.hwnd, self.changed = hwnd, changed
        self.structure_only = structure_only
        self.thread = None
        self.ready = threading.Event()
        self.cancelled = threading.Event()
        self.state_lock = threading.Lock()
        self.started = False

    @property
    def live(self):
        return bool(self.started and self.thread and self.thread.is_alive()
                    and not self.cancelled.is_set())

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

        handlers, popup_hook, roots = [], None, None
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
            from .uia_windows import WindowsProvider
            from .uia_popups import hook_popups, sender_in_scope
            from .uia_event_roots import POPUP_REFRESH, WindowHandlers
            provider = WindowsProvider(self.hwnd)
            message = wintypes.MSG()
            user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            def refresh():
                user.PostThreadMessageW(thread_id, POPUP_REFRESH, 0, 0)
            popup_hook, popup_callback = hook_popups(user, provider.scope, self.changed, refresh)
            if self.structure_only:  # only the short Expand deadline may use desktop scope
                root = automation.GetRootElement()
                handlers = register_handlers(automation, uia, root, self.changed, COMObject,
                                             lambda sender: sender_in_scope(provider, sender), True)
            else:
                roots = WindowHandlers(automation, uia, self.hwnd, provider.scope, self.changed, COMObject,
                                       event_cache(automation))
                roots.start()  # no COM calls or sender walks inside persistent UIA handlers
            if not self._mark_started(thread_id, automation, handlers):
                return
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == POPUP_REFRESH and roots is not None:
                    roots.refresh()
                    continue
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
        except Exception:
            self.ready.set()  # unsupported UIA event registration falls back to bounded snapshots
        finally:
            self.started = False
            if popup_hook:
                user.UnhookWinEvent(popup_hook)
            if "automation" in locals():
                try:
                    if roots is not None:
                        roots.close()
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
