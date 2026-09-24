"""Human-readable host checks for Partyline's fence and adapter CLIs."""

from __future__ import annotations

import shutil
from collections.abc import Mapping

from . import fence_probe


def check_adapters(metadata: Mapping[str, Mapping[str, object]]) -> list[tuple[str, str, bool]]:
    checks = []
    for adapter, manifest in sorted(metadata.items()):
        for executable in manifest.get("requires") or []:
            name = str(executable)
            checks.append((adapter, name, shutil.which(name) is not None))
    return checks


def run(metadata: Mapping[str, Mapping[str, object]], *, probe=None) -> int:
    """Print host readiness and return nonzero if any required check fails."""
    probe = probe or fence_probe.probe
    result = probe()
    info = fence_probe.status(result)
    print(f"Platform: {info['platform']}")
    print(f"Backend: {info['backend']}")
    print(f"Probe: {'PASS' if result[0] else 'FAIL'}"
          + (f" — {result[1]}" if result[1] else ""))
    print(f"Remedy: {result[2] or 'none needed'}")
    checks = check_adapters(metadata)
    print("Adapter CLI requirements:")
    for adapter, executable, available in checks:
        print(f"  {'PASS' if available else 'FAIL'} {adapter}: {executable}")
    return 0 if result[0] and all(check[2] for check in checks) else 1
