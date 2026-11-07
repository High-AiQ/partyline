"""pynput input injection and the kill-switch key listener, loaded only once control is granted."""
import ctypes
import sys

PERMISSION = ("macOS: open System Settings > Privacy & Security, enable your terminal or Python under "
              "both Accessibility and Input Monitoring, then quit and reopen it.")


def trusted():
    if sys.platform != "darwin":
        return True
    services = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    services.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(services.AXIsProcessTrusted())


# X11 keysyms pynput reports as unnamed KeyCodes: the standard keymap turns Shift+Tab into
# ISO_Left_Tab (/usr/share/X11/xkb/symbols/pc: <TAB> [Tab, ISO_Left_Tab]).
UNNAMED_VK = {0xFE20: "tab"}


def key_name(key):
    """Normalize a pynput key to the names in keys.py (ctrl_l -> ctrl, cmd -> meta)."""
    name = getattr(key, "name", None)
    if name is None:
        char = getattr(key, "char", None)
        if char:
            return char.lower()
        return UNNAMED_VK.get(getattr(key, "vk", None), "unknown")
    name = name.removesuffix("_l").removesuffix("_r").removesuffix("_gr")
    return "meta" if name == "cmd" else name


class Inputs:
    """Desktop pixels in; native pynput coordinates out."""

    def __init__(self, scale=1.0):
        if not trusted():
            raise RuntimeError("Agent control needs permission. " + PERMISSION)
        from pynput import keyboard, mouse
        self.keyboard_module, self.mouse_module = keyboard, mouse
        self.mouse, self.keyboard = mouse.Controller(), keyboard.Controller()
        self.scale = scale or 1.0
        self.listener = None

    def move(self, x, y):
        # pynput 1.8's darwin getter flips Y with CGDisplayPixelsHigh(0) (retina.pointer_y_offset
        # undoes that), but its setter posts CG top-left points as given: so no offset here.
        self.mouse.position = (x / self.scale, y / self.scale)

    def _button(self, name):
        return getattr(self.mouse_module.Button, name)

    def press(self, button):
        self.mouse.press(self._button(button))

    def release(self, button):
        self.mouse.release(self._button(button))

    def click(self, button, count):
        self.mouse.click(self._button(button), count)

    def scroll(self, dx, dy):
        self.mouse.scroll(dx, dy)

    def type(self, text):
        self.keyboard.type(text)

    def key(self, names):
        key = self.keyboard_module.Key
        try:
            keys = [key.cmd if name == "meta" else name if len(name) == 1 else getattr(key, name)
                    for name in names]
        except AttributeError:
            raise ValueError(f"{'+'.join(names)} is not available on this computer") from None
        pressed = []
        try:
            for item in keys:
                self.keyboard.press(item)
                pressed.append(item)
        finally:
            for item in reversed(pressed):
                self.keyboard.release(item)

    def listen(self, on_key):
        """Start the listener; on_key(name, injected, down) runs on pynput's thread."""
        listener = self.keyboard_module.Listener(
            on_press=lambda key, injected: on_key(key_name(key), bool(injected), True),
            on_release=lambda key, injected: on_key(key_name(key), bool(injected), False))
        listener.start()
        self.listener = listener
        listener.wait()
        if not getattr(listener, "IS_TRUSTED", True) or not listener.is_alive():
            raise RuntimeError("The kill-switch key listener could not start. " + PERMISSION)

    def stop(self):
        listener, self.listener = self.listener, None
        if listener:
            listener.stop()
