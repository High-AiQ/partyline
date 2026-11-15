"""Repair the per-user Start-menu link and uninstall icon when a rollback restores registration."""
from pathlib import Path

UNINSTALL = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall" "\\"
             r"{B6F1D2A4-5C1E-4E0B-9C57-3A7E2D0F4A61}_is1")


def shell():  # pragma: no cover - Windows automation; tests supply the same COM boundary
    from comtypes.client import CreateObject
    return CreateObject("WScript.Shell", dynamic=True)


def repair(executable, registry, programs=None, create=shell):
    automation = create()
    programs = programs or Path(automation.SpecialFolders("Programs"))
    programs.mkdir(parents=True, exist_ok=True)
    shortcut = automation.CreateShortcut(str(programs / "Partyline Helper.lnk"))
    shortcut.TargetPath = executable
    shortcut.Arguments = "start"
    shortcut.WorkingDirectory = str(Path(executable).parent)
    shortcut.IconLocation = executable + ",0"
    shortcut.Save()
    registry.set(UNINSTALL, "DisplayIcon", executable)
