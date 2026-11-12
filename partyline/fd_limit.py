"""Raise this process's open-file limit at startup.

macOS gives a process 256 descriptors by default, and its file notifications hold
one descriptor for every watched file (kqueue vnode events need one). One Claude
process looking for its transcript watches every existing Claude transcript, so a
handful of attachments exhausted the limit. The next ``open`` anywhere then failed:
an OpenCode watcher treated "[Errno 24] Too many open files" as fatal and stopped
its process, and a captain detached. Nothing in partyline had ever raised the limit.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

WANTED = 65536
# macOS refuses a soft limit above kern.maxfilesperproc (10240 by default) even when
# the hard limit reads as unlimited, so lower targets are tried in turn.
FALLBACKS = (10240, 4096)
ENOUGH = 4096


def raise_open_file_limit(resource=None) -> int | None:
    """Raise the soft limit as far as the host allows; return it, or None where there is none."""
    if resource is None:
        try:
            import resource
        except ImportError:  # Windows has no descriptor limit of this kind
            return None
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    ceiling = WANTED if hard == resource.RLIM_INFINITY else min(hard, WANTED)
    for target in dict.fromkeys((ceiling, *(value for value in FALLBACKS if value < ceiling))):
        if target <= soft:
            break
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            return target
        except (ValueError, OSError):
            continue
    if soft < ENOUGH:
        logger.warning(
            "the open-file limit stays at %d; with several attached processes partyline can "
            "run out of descriptors. Raise it before starting partyline: ulimit -n 10240", soft)
    return soft
