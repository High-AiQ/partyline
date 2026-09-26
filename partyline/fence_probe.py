"""Boot and doctor checks for the real write-fence backend."""

from __future__ import annotations

import subprocess
import sys
import tempfile


DOCS = "https://github.com/containers/bubblewrap"
_probe_result: tuple[bool, str, str] | None = None


def set_result(result: tuple[bool, str, str]) -> None:
    global _probe_result
    _probe_result = result


def cached_result() -> tuple[bool, str, str] | None:
    return _probe_result


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _distribution() -> tuple[str, str]:
    values: dict[str, str] = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as source:
            for line in source:
                key, separator, value = line.partition("=")
                if separator:
                    values[key] = value.strip().strip('"').lower()
    except OSError:
        pass
    return values.get("ID", ""), values.get("ID_LIKE", "")


def remedy(sys_platform: str | None = None) -> str:
    """Return the direct, person-side installation instruction for a host."""
    target = sys.platform if sys_platform is None else sys_platform
    if target == "darwin":
        return "sandbox-exec ships with macOS; no install is needed"
    if target == "win32":
        return ("Use Windows 10 build 17763 or newer and local drives with filesystem ACLs; "
                "run uv sync --locked and check the reported path permissions")
    if not target.startswith("linux"):
        return f"Install a write-fence backend for {target}; see {DOCS}"
    distro, like = _distribution()
    family = f"{distro} {like}"
    if any(name in family for name in ("debian", "ubuntu")):
        line = "apt-get install -y bubblewrap"
    elif any(name in family for name in ("fedora", "rhel", "centos")):
        line = "dnf install bubblewrap"
    elif any(name in family for name in ("arch", "manjaro")):
        line = "pacman -S bubblewrap"
    elif any(name in family for name in ("suse", "opensuse")):
        line = "zypper install bubblewrap"
    else:
        return f"Install the bubblewrap package for your distribution; see {DOCS}"
    if distro == "ubuntu":
        try:
            version = tuple(int(part) for part in values_release().split(".")[:2])
        except ValueError:
            version = ()
        if version >= (24, 4):
            return line
    return line


def values_release() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as source:
            for line in source:
                if line.startswith("VERSION_ID="):
                    return line.partition("=")[2].strip().strip('"')
    except OSError:
        pass
    return ""


def _probe_note() -> str:
    distro, _ = _distribution()
    try:
        version = tuple(int(part) for part in values_release().split(".")[:2])
    except ValueError:
        version = ()
    if distro == "ubuntu" and version >= (24, 4):
        return "Ubuntu's bubblewrap package carries the AppArmor profile; a pip-bundled binary is not offered"
    return ""


def probe(*, check_fence: bool = True,
          service_unit: str | None = None,
          discover_service_unit: bool = True) -> tuple[bool, str, str]:
    """Check the filesystem fence, per-process cap, and service OOM guard."""
    from . import fence, fence_darwin

    failures, remedies = [], []
    note = _probe_note() if sys.platform.startswith('linux') else ''
    if check_fence:
        selected = fence.backend()
        available, reason = fence.backend_available()
        if not available:
            failures.append(reason)
            remedies.append(remedy())
        else:
            try:
                with tempfile.TemporaryDirectory(prefix="partyline-fence-") as cwd:
                    if selected == "bubblewrap":
                        argv = fence._bwrap_argv({"cwd": cwd}, ["/usr/bin/true"])
                    elif selected == "sandbox-exec":
                        argv = [fence_darwin.SANDBOX_EXEC, "-p",
                                "(version 1)(allow default)", "/usr/bin/true"]
                    elif selected == "restricted-token":
                        argv = [sys.executable, '-m', 'partyline.windows_probe']
                    else:
                        raise OSError(f"no write-fence backend for platform '{sys.platform}'")
                    timeout = 120 if selected == 'restricted-token' else 10
                    completed = subprocess.run(argv, cwd=cwd, capture_output=True,
                                               text=True, timeout=timeout)
            except (OSError, subprocess.SubprocessError) as exc:
                failures.append(f"write-fence probe could not run: {_one_line(str(exc))}")
                remedies.append(remedy())
            else:
                if completed.returncode:
                    detail = _one_line(completed.stderr or completed.stdout) or "command failed"
                    failures.append(f"write-fence probe exited {completed.returncode}: {detail}")
                    remedies.append(remedy())
    from . import process_memory, service_guard

    scope_ok, scope_reason = process_memory.probe_scope()
    if not scope_ok:
        failures.append(scope_reason)
        remedies.append("Run partyline under a systemd user manager with transient scopes enabled")
    guard_ok, guard_reason, guard_remedy = service_guard.probe(
        service_unit, discover=discover_service_unit,
    )
    if not guard_ok:
        failures.append(guard_reason)
        remedies.append(guard_remedy)
    if note and failures:
        failures.append(note)
    return not failures, "; ".join(failures), "\n\n".join(remedies)


def status(result: tuple[bool, str, str] | None = None) -> dict[str, str | bool]:
    from . import fence

    ok, reason, install = result or (True, "", "")
    return {"ok": ok, "backend": fence.backend(), "platform": sys.platform,
            "reason": reason, "remedy": install}
