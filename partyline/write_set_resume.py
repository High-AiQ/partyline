"""Resume the union of lines affected by a batch of write grants."""

from . import docker_relay


def _grant_scope(runtime, conv_id: str, path: str) -> list[str]:
    if not docker_relay.is_docker_socket(path):
        return [conv_id]
    return [conv_id, *(row["id"] for row in runtime.db.list_conversations()
                       if row["id"] != conv_id)]


async def resume_granted_scopes(runtime, conv_id: str, paths: list[str], resume,
                                resumer=None) -> tuple[list[str], list[str]]:
    """Resume each affected line once after every grant has been recorded."""
    if resumer is None:
        from .write_set_requests import resume_line_attachments
        resumer = resume_line_attachments
    lines = dict.fromkeys(line for path in paths for line in _grant_scope(runtime, conv_id, path))
    resumed: list[str] = []
    failed: list[str] = []
    for line in lines:
        done, broke = await resumer(runtime, line, resume)
        resumed.extend(name for name in done if name not in resumed)
        failed.extend(name for name in broke if name not in failed)
    return resumed, failed
