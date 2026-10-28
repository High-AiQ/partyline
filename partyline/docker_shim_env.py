"""Configure the Docker CLI shim for an attachment."""
import os
import sys
from pathlib import Path

from .process_memory import parse_size

FLOOR = 6 * 1024**2  # Docker's minimum container memory limit.


def configure(env: dict[str, str], memory_limit: str) -> None:
    """Prepend the packaged shim and calculate the per-container default."""
    raw = os.environ.get("PARTYLINE_DOCKER_MEMORY_FRACTION", "0.5")
    try:
        fraction = float(raw)
    except ValueError as exc:
        raise ValueError("PARTYLINE_DOCKER_MEMORY_FRACTION must be in (0, 1]") from exc
    if not 0 < fraction <= 1:
        raise ValueError("PARTYLINE_DOCKER_MEMORY_FRACTION must be in (0, 1]")
    env["PARTYLINE_DOCKER_MEMORY_BYTES"] = str(max(FLOOR, int(parse_size(memory_limit) * fraction)))
    shim_dir = str(Path(__file__).resolve().parent / "docker_shim")
    env["PATH"] = shim_dir + os.pathsep + env.get("PATH", os.defpath)


def prepare(env: dict[str, str], memory_limit: str) -> bool:
    """Configure POSIX attachments; return whether the Windows runtime is needed."""
    if sys.platform == "win32":
        return True
    configure(env, memory_limit)
    return False
