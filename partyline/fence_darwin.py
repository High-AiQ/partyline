"""The Darwin write-fence backend: ``/usr/bin/sandbox-exec`` with a
generated profile.

macOS has no bubblewrap and no mount namespace a process may create, so
the seam's second backend cannot bind — it profiles. The generated text
is Apple's documented sandbox profile language: everything is allowed
(``(allow default)``), writes are denied, and the line's write set — plus
the temp directories and tty devices a CLI cannot live without — is
allowed back in after the deny. The scope that feeds the profile is
``fence.darwin_write_set``; the weaker Darwin git guarantee it carries is
documented in ``docs/write-fence.md``.

The profile rides the argv with ``-p`` so spawn stays stateless — no
temp file to clean up between a reservation and a start. Like the
bubblewrap plan, it is visible in ``ps``; this is a fence against
accidents, not a jail against malice, and nothing here pretends
otherwise.
"""

from __future__ import annotations

import os

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

# Devices a CLI legitimately opens for writing: the null sink, its
# controlling terminal (some tools reopen it by path), the console, and
# the pty slave devices macOS names /dev/ttysNNN. The regex is SBPL's;
# Apple's own system profiles use it the same way.
_DEVICE_ALLOWS = (
    '(literal "/dev/null")',
    '(literal "/dev/tty")',
    '(literal "/dev/console")',
    '(regex #"^/dev/ttys[0-9]+$")',
)


def sandbox_exec_available() -> bool:
    return os.path.isfile(SANDBOX_EXEC) and os.access(SANDBOX_EXEC, os.X_OK)


def quote(path: str) -> str:
    """One SBPL string literal: the two escapes its lexer knows, backslash first."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def temp_subpaths() -> list[str]:
    """The temp directories a CLI expects to write: the shared /private/tmp
    (macOS has no private tmpfs here — a documented gap, not a hidden one)
    and the process's own TMPDIR in both spellings, because /var is a
    symlink to /private/var and profiles match canonical paths.
    """
    paths = ["/private/tmp"]
    tmpdir = os.environ.get("TMPDIR") or ""
    for candidate in (tmpdir, os.path.realpath(tmpdir) if tmpdir else ""):
        if candidate and candidate not in paths:
            paths.append(candidate)
    return paths


def profile(write_paths: list[str]) -> str:
    """The SBPL text for one attachment: default-allow, ``file-write*``
    denied, then the write set, temp directories, and tty devices allowed
    back in. The deny-then-allow shape is the standard SBPL idiom — later,
    more specific rules narrow the earlier global deny.
    """
    filters = [f"(subpath {quote(path)})" for path in [*write_paths, *temp_subpaths()]]
    filters += _DEVICE_ALLOWS
    body = "\n".join(f"    {line}" for line in filters)
    return ("(version 1)\n(allow default)\n(deny file-write*)\n"
            f"(allow file-write*\n{body})\n")


def argv(write_paths: list[str], command: list[str], fence_args: list[str]) -> list[str]:
    """The sandbox-exec plan for one attachment: the profile, then the
    command. ``fence_args`` follow with the same dedupe as bubblewrap — an
    adapter's declared flags are appended only when the command does not
    already carry them, because CLIs reject a repeated flag.
    """
    tail = list(command) + [flag for flag in fence_args if flag not in command]
    return [SANDBOX_EXEC, "-p", profile(write_paths)] + tail
