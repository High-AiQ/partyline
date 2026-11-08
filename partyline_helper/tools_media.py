"""Images from a local tool: fetch the add-on's artifact, re-encode it and send it as one binary message.

The add-on's file is never forwarded as it is: it is decoded and written again (WebP, JPEG as the fallback),
which drops any metadata and proves the bytes are an image. The server accepts 4 MiB per binary message and
closes the connection on more, so a result that cannot fit is refused here with a plain error, not sent.
"""
import asyncio
from io import BytesIO

from PIL import Image

from .tools_addon import AddonError

MAX_MEDIA = 4 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024   # the add-on clamps far below this; a bigger image is not what was asked
MEDIA_OPS = ("render", "screenshot")
QUALITIES = (85, 70, 50)


class MediaError(Exception):
    """The image cannot be delivered; the message is for the agent."""


def has_image(op, result):
    return (op in MEDIA_OPS and isinstance(result, dict) and result.get("ok") is True
            and isinstance(result.get("artifact"), dict))


def encode(image, quality):
    out = BytesIO()
    try:
        image.save(out, "WEBP", quality=quality, method=4)
        return out.getvalue(), "image/webp"
    except (OSError, ValueError, KeyError):  # a Pillow build without WebP
        out = BytesIO()
        image.save(out, "JPEG", quality=quality)
        return out.getvalue(), "image/jpeg"


def reencode(data):
    """(bytes, mime, width, height) at the original size, or MediaError when it cannot fit under MAX_MEDIA."""
    try:
        image = Image.open(BytesIO(data))
        if image.width * image.height > MAX_PIXELS:
            raise MediaError(f"the image is {image.width}x{image.height}, larger than expected")
        image = image.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        raise MediaError("the add-on's image could not be read") from None
    for quality in QUALITIES:
        binary, mime = encode(image, quality)
        if len(binary) <= MAX_MEDIA:
            return binary, mime, image.width, image.height
    raise MediaError(f"the image is {len(binary) / 1048576:.1f} MiB at {image.width}x{image.height} even "
                     "after compression, over the 4 MiB limit; ask for a smaller size")


async def deliver(tools, grant, call_id, op, result):
    """Send the call's result with its image; every failure becomes an error result the agent can read."""
    try:
        data = await grant["addon"].artifact(grant["id"], str(result["artifact"].get("id")))
        binary, mime, width, height = await asyncio.to_thread(reencode, data)
    except (AddonError, MediaError) as exc:
        tools.log("result", op, f"failed: {exc}")
        return await tools.send("tool_result", call_id=call_id, ok=False, error=str(exc))
    if tools.grant is not grant:  # the session ended while the image was being prepared
        return
    shown = {key: value for key, value in result.items() if key != "artifact"}
    shown["media"] = {"mime": mime, "bytes": len(binary), "width": width, "height": height}
    tools.log("result", op, f"ok ({mime}, {len(binary)} bytes, {width}x{height})")
    await tools.send("tool_result", binary=binary, call_id=call_id, ok=True, result=shown, media=True,
                     mime=mime)
