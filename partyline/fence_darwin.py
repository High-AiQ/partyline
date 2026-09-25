"""The Darwin write-fence backend: ``/usr/bin/sandbox-exec`` with a
generated profile.

macOS has no bubblewrap and no mount namespace a process may create, so
the seam's second backend cannot bind — it profiles. The generated text
is Apple's documented sandbox profile language: everything is allowed
(``(allow default)``), then every protected repository root and the
database are denied, then the line's own carve-outs and grants — plus
the temp directories and tty devices a CLI cannot live without — are
allowed back in after that deny. A child worktree allows its common Git
root for transient writes, then denies stable shared metadata and
re-allows its own worktree metadata. ``fence._darwin_scope`` computes
the path lists this module turns into SBPL; the weaker Darwin Git
guarantee is documented in ``docs/write-fence.md``.

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
    """The host temp directories a CLI expects to write: /private/tmp and
    the process's own TMPDIR in both spellings, because /var is a
    symlink to /private/var and profiles match canonical paths.
    """
    paths = ["/private/tmp"]
    tmpdir = os.environ.get("TMPDIR") or ""
    for candidate in (tmpdir, os.path.realpath(tmpdir) if tmpdir else ""):
        if candidate and candidate not in paths:
            paths.append(candidate)
    return paths


def profile(deny_paths: list[str], allow_paths: list[str],
            deny_after_paths: list[str] | None = None,
            allow_after_paths: list[str] | None = None) -> str:
    """The SBPL text for one attachment: default-allow, then every
    protected root and the database denied, then the carve-outs, temp
    directories, and tty devices allowed back in. The deny-then-allow
    shape is the standard SBPL idiom — later, more specific rules narrow
    the earlier rule for the same path. An empty ``deny_paths`` (nothing
    protected reaches this process) omits the deny clause entirely, since
    ``(allow default)`` already covers everything.
    """
    deny_after_paths = deny_after_paths or []
    allow_after_paths = allow_after_paths or []
    allow_filters = [f"(subpath {quote(path)})" for path in [*allow_paths, *temp_subpaths()]]
    allow_filters += list(_DEVICE_ALLOWS)
    parts = ["(version 1)", "(allow default)"]
    if deny_paths:
        deny_filters = [f"(subpath {quote(path)})" for path in deny_paths]
        deny_body = "\n".join(f"    {line}" for line in deny_filters)
        parts.append(f"(deny file-write*\n{deny_body})")
    allow_body = "\n".join(f"    {line}" for line in allow_filters)
    parts.append(f"(allow file-write*\n{allow_body})")
    if deny_after_paths:
        deny_body = "\n".join(
            f"    (subpath {quote(path)})" for path in deny_after_paths)
        parts.append(f"(deny file-write*\n{deny_body})")
    if allow_after_paths:
        allow_body = "\n".join(
            f"    (subpath {quote(path)})" for path in allow_after_paths)
        parts.append(f"(allow file-write*\n{allow_body})")
    return "\n".join(parts) + "\n"


def argv(deny_paths: list[str], allow_paths: list[str],
         deny_after_paths: list[str], allow_after_paths: list[str],
         command: list[str], fence_args: list[str]) -> list[str]:
    """The sandbox-exec plan for one attachment: the profile, then the
    command. ``fence_args`` follow with the same dedupe as bubblewrap — an
    adapter's declared flags are appended only when the command does not
    already carry them, because CLIs reject a repeated flag.
    """
    tail = list(command) + [flag for flag in fence_args if flag not in command]
    return [SANDBOX_EXEC, "-p", profile(deny_paths, allow_paths,
                                        deny_after_paths, allow_after_paths)] + tail
