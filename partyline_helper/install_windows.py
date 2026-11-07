"""Per-user Windows registration: HKCU protocol handler and Run key. No admin rights, no console."""
import subprocess

PROTOCOL = r"Software\Classes\partyline"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "PartylineHelper"


class Registry:  # pragma: no cover - the real HKCU; tests inject a fake with the same three methods
    def set(self, path, name, value):
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete_value(self, path, name):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    def delete_tree(self, path):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                while True:
                    try:
                        child = winreg.EnumKey(key, 0)
                    except OSError:
                        break
                    self.delete_tree(path + "\\" + child)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def install(registry, launch, log):
    """`open -- "%1"` keeps a hostile link from being parsed as an option."""
    opener = subprocess.list2cmdline(launch) + ' open -- "%1"'
    runner = subprocess.list2cmdline(launch + ["run", "--log", str(log)])
    registry.set(PROTOCOL, "", "URL:Partyline Helper")
    registry.set(PROTOCOL, "URL Protocol", "")
    registry.set(PROTOCOL + r"\shell\open\command", "", opener)
    registry.set(RUN_KEY, RUN_NAME, runner)
    return [f"URL handler: HKCU\\{PROTOCOL}\\shell\\open\\command = {opener}",
            f"start at login: HKCU\\{RUN_KEY}\\{RUN_NAME} = {runner}",
            f"log file: {log}"]


def uninstall(registry):
    registry.delete_tree(PROTOCOL)
    registry.delete_value(RUN_KEY, RUN_NAME)
    return [f"removed HKCU\\{PROTOCOL}", f"removed HKCU\\{RUN_KEY}\\{RUN_NAME}"]
