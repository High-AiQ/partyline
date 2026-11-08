"""Images from local tools: read the binary message after a media result and keep it as line media.

The helper sends `tool_result{media: true}` followed by one binary message, as it does for screen frames. The
image is stored with `store_frame` and the agent gets the same reference shape as `screen_frame` (`file`), so
it fetches the pixels with `get_media`; nothing is posted to the chat. A render is also remembered on the
session, with whether it was `checkable` (rendered while the person had allowed render checks).
"""
import asyncio
from io import BytesIO

from PIL import Image

from .media import MediaError
from .screen_frame_store import store_frame
from .screen_protocol import HEARTBEAT_TIMEOUT, MAX_FRAME_BYTES

MIMES = ("image/webp", "image/jpeg", "image/png")
SESSION_BYTES = 256 * 1024 * 1024  # media one session may store; a loop of renders cannot fill the disk
KEEP_RENDERS = 200                 # renders a session remembers for render checks; older ones are forgotten


async def read(device, message):
    """The bytes after a tool_result announcing media, or None. Read even for a call nobody awaits."""
    if message.get("media") is not True:
        return None
    return await asyncio.wait_for(device["socket"].receive_bytes(), HEARTBEAT_TIMEOUT)


def decodes(data):
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
        return True
    except Exception:  # noqa: BLE001 - anything Pillow cannot read is not an image
        return False


async def attach(store, item, op, result, answer):
    """`result` plus `file` (the screen_frame reference shape) when the helper sent an image with it."""
    if answer.get("media") is not True:
        return result
    data, mime = answer.get("data"), answer.get("mime")
    usable = data and len(data) <= MAX_FRAME_BYTES and mime in MIMES
    if not usable or store is None or not await asyncio.to_thread(decodes, data):
        raise ValueError("the computer sent an image that cannot be used")
    if item.media_bytes + len(data) > SESSION_BYTES:
        raise ValueError(f"session media cap: at most {SESSION_BYTES // 1048576} MiB of images per session; "
                         "ask the person to grant a new session")
    try:
        ref = await store_frame(store, item.conv_id, data, mime, f"local-tool-{op}",
                                f"Local tool {op}")
    except MediaError as exc:
        raise ValueError(f"the image was rejected: {exc.detail}") from exc
    item.media_bytes += len(data)
    file = ref.model_dump(mode="json")
    if op != "render":
        return {**result, "file": file}
    # The helper marks a render checkable from its grant at that moment; the server only ever trusts "yes"
    # together with the session's own current scope (render_check_routes).
    checkable = answer.get("checkable") is True
    item.renders[file["id"]] = checkable
    while len(item.renders) > KEEP_RENDERS:
        del item.renders[next(iter(item.renders))]
    return {**result, "file": file, "checkable": checkable}


def note(result):
    return f", media {result['file']['id']}" if "file" in result else ""
