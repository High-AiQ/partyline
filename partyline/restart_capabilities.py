"""Adapter capability decisions shared by restart planning and activation."""

from collections.abc import Mapping


def adapter_listens(metadata: Mapping[str, object]) -> bool:
    capabilities = metadata.get("capabilities") or {}
    return not isinstance(capabilities, dict) or capabilities.get("listens", True) is not False


def adapter_can_resume(metadata: Mapping[str, object]) -> bool:
    capabilities = metadata.get("capabilities") or {}
    return (
        bool(capabilities.get("resume", False))
        if isinstance(capabilities, dict)
        else "resume" in capabilities
    )


def adapter_can_restart(metadata: Mapping[str, object]) -> bool:
    return adapter_can_resume(metadata) or not adapter_listens(metadata)


def resume_needs_session(metadata: Mapping[str, object]) -> bool:
    capabilities = metadata.get("capabilities")
    return isinstance(capabilities, dict) and bool(capabilities.get("resume_needs_session"))
