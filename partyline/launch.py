"""Start the foreground server inside an automatically created memory scope."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if sys.platform.startswith("linux") and not any(arg in ("-h", "--help") for arg in arguments):
        from . import server_memory
        from .bind import load_dotenv
        from .service_guard import unit_from_cgroup

        load_dotenv()
        inside = arguments[:1] == ["--within-memory-scope"]
        if inside:
            arguments.pop(0)
            ok, reason = server_memory.verify()
            if not ok:
                raise SystemExit(f"Partyline cannot verify its server memory cap: {reason}")
        else:
            unit = unit_from_cgroup()
            installed = unit and (unit.startswith("partyline") or
                                  unit == os.environ.get("PARTYLINE_SYSTEMD_UNIT"))
            if not installed:
                executable = shutil.which("systemd-run")
                if not executable:
                    raise SystemExit("Partyline needs systemd-run and a systemd user manager on Linux")
                limit = server_memory.limit_bytes()
                command = [
                    executable, "--user", "--scope", "--quiet", "--collect",
                    "--expand-environment=no", f"--unit=partyline-server-{uuid.uuid4().hex}.scope",
                    "-p", f"MemoryMax={limit}", "-p", "MemorySwapMax=0",
                    "-p", "OOMPolicy=continue", "--", sys.executable, "-m", "partyline.launch",
                    "--within-memory-scope", *arguments,
                ]
                # A scope inherits cwd, environment, standard streams and terminal
                # signals. No service installation or detached daemon is needed.
                os.execv(executable, command)
                return  # pragma: no cover - execv replaces this process

    from .server import main as serve

    if sys.platform == 'win32' and not any(arg in ('-h', '--help') for arg in arguments):
        from .windows_server import serve as windows_serve
        return windows_serve(arguments, serve)
    return serve(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
