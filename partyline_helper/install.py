"""One-time `partyline-helper install` / `uninstall`: URL handler and start-at-login for this user."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import install_windows
from .instance import lock_dir
from .launch import record_path, resolve_launch, save_record

DESKTOP_NAME = "partyline-helper.desktop"
MIME = "x-scheme-handler/partyline"
LABEL = "io.partyline.helper"


def desktop_quote(arg):
    """Desktop Entry `Exec` quoting: no shell is involved, but spaces and specials must be escaped."""
    arg = arg.replace("%", "%%")
    if any(char in arg for char in ' \t\n"\'\\><~|&;$*?#()`'):
        arg = '"' + "".join("\\" + char if char in '"`$\\' else char for char in arg) + '"'
    return arg


def desktop_entry(name, exec_args, extra):
    return "\n".join(["[Desktop Entry]", "Type=Application", f"Name={name}",
                      "Exec=" + " ".join(desktop_quote(a) if a != "%u" else a for a in exec_args),
                      "Terminal=false", *extra, ""])


class Installer:
    def __init__(self, system=None, home=None, env=None, run=subprocess.run, registry=None):
        self.system = system or {"win32": "Windows", "darwin": "Darwin"}.get(sys.platform, "Linux")
        self.home = Path(home) if home else Path.home()
        self.env = os.environ if env is None else env
        self.run, self.registry = run, registry
        self.log = lock_dir() / "helper.log"

    def _tool(self, *command):
        try:
            done = self.run(list(command), capture_output=True, text=True, check=False)
        except OSError as exc:
            return f"{command[0]} unavailable ({exc.__class__.__name__})"
        return None if done.returncode == 0 else f"{command[0]} exited {done.returncode}"

    def _xdg(self, name, default):
        return Path(self.env.get(name) or self.home / default)

    def linux_paths(self):
        return (self._xdg("XDG_DATA_HOME", ".local/share") / "applications" / DESKTOP_NAME,
                self._xdg("XDG_CONFIG_HOME", ".config") / "autostart" / DESKTOP_NAME)

    def mac_plist(self):
        return self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"

    def install(self, launch):
        if self.system == "Windows":
            return install_windows.install(self.registry or install_windows.Registry(), launch, self.log)
        if self.system == "Darwin":
            return self._install_mac(launch)
        handler, autostart = self.linux_paths()
        for path, args, extra in (
                (handler, launch + ["open", "--", "%u"],
                 ["NoDisplay=true", f"MimeType={MIME};", "Categories=Utility;"]),
                (autostart, launch + ["run", "--log", str(self.log)],
                 ["X-GNOME-Autostart-enabled=true", "Hidden=false"])):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(desktop_entry("Partyline Helper", args, extra))
        lines = [f"URL handler: {handler} (MimeType={MIME})", f"start at login: {autostart}",
                 f"log file: {self.log}"]
        if problem := self._tool("xdg-mime", "default", DESKTOP_NAME, MIME):
            lines.append(f"warning: xdg-mime: {problem}; select Partyline Helper for partyline links by hand")
        else:
            lines.append(f"ran: xdg-mime default {DESKTOP_NAME} {MIME}")
        self._tool("update-desktop-database", str(handler.parent))  # best effort cache refresh
        return lines

    def _install_mac(self, launch):
        plist = self.mac_plist()
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps({
            "Label": LABEL, "ProgramArguments": launch + ["run", "--log", str(self.log)],
            "RunAtLoad": True, "KeepAlive": False, "ProcessType": "Interactive"}))
        domain = f"gui/{os.getuid()}"
        self._tool("launchctl", "bootout", f"{domain}/{LABEL}")  # idempotent: reload a changed plist
        lines = [f"start at login: {plist} (LaunchAgent)", f"log file: {self.log}",
                 "URL handler: not available on macOS in phase 1 (partyline:// links need a signed .app "
                 "bundle); use the copyable commands instead"]
        if problem := self._tool("launchctl", "bootstrap", domain, str(plist)):
            lines.append(f"warning: launchctl bootstrap: {problem}; it will start at next login")
        return lines

    def uninstall(self):
        if self.system == "Windows":
            return install_windows.uninstall(self.registry or install_windows.Registry())
        paths = [self.mac_plist()] if self.system == "Darwin" else list(self.linux_paths())
        if self.system == "Darwin":
            self._tool("launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}")
        lines = []
        for path in paths:
            existed = path.exists()
            path.unlink(missing_ok=True)
            lines.append(f"{'removed' if existed else 'not present'}: {path}")
        if self.system == "Linux":
            self._tool("update-desktop-database", str(paths[0].parent))
        return lines


def install_command(installer=None, **kwargs):
    installer = installer or Installer()
    launch, notes = resolve_launch(**kwargs)
    save_record(launch)
    lines = [*notes, f"launch command: {' '.join(launch)}", *installer.install(launch),
             "Done. Paired links (partyline://) now open this helper; it also starts at login."]
    return "\n".join(lines)


def uninstall_command(installer=None):
    lines = (installer or Installer()).uninstall()
    existed = record_path().exists()
    record_path().unlink(missing_ok=True)
    lines.append(f"{'removed' if existed else 'not present'}: {record_path()}")
    lines.append("Pairing credentials were left in place; run `partyline-helper unpair` to delete them. "
                 "A tool installed by `uv tool install` can be removed with `uv tool uninstall partyline`.")
    return "\n".join(lines)
