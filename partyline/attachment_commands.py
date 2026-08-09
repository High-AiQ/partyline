"""Pure validation for commands stored on process attachments."""

from collections.abc import Callable, Collection, Mapping
import shlex
import shutil


ExecutableLookup = Callable[[str], str | None]
AdapterMetadata = Mapping[str, Mapping[str, object]]


def validated_attachment_command(
    adapter_id: str,
    raw_command: str,
    available_adapters: Collection[str],
    metadata: AdapterMetadata,
    executable_lookup: ExecutableLookup = shutil.which,
) -> list[str]:
    """Resolve one shell-style command exactly as the attach form does."""
    if adapter_id not in available_adapters:
        raise ValueError(f"adapter must be one of {sorted(available_adapters)}")
    try:
        command = shlex.split(raw_command) if raw_command.strip() else []
    except ValueError as exc:
        raise ValueError(f"invalid command: {exc}") from exc

    adapter_metadata = metadata[adapter_id]
    if not command:
        command = list(adapter_metadata.get("command") or [])
        if not command:
            raise ValueError(f"the {adapter_id} adapter needs an explicit command")

    for executable in adapter_metadata.get("requires") or []:
        if executable_lookup(str(executable)) is None:
            raise ValueError(
                f"{executable!r} is not on PATH — install it, or attach with a full path"
            )
    return command
