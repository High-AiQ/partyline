"""Resolve an overlay reference from this line and bound it before sending it to the local relay."""
import base64
import io
import json
import math

from PIL import Image

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_REFERENCE_BYTES = 700 * 1024  # fits installed helpers with a 1,000,000-byte receive limit
MAX_HELPER_MESSAGE_BYTES = 1_000_000
MIN_SIDE, MAX_SIDE = 16, 2048


def prepare(store, conv_id, args):
    """Copy render args, replacing a line media id with capped PNG bytes; never forward paths or URLs."""
    value = args.get("overlay_opacity", 0.5)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) \
            or not 0 <= value <= 1:
        raise ValueError("overlay_opacity must be a finite number in 0..1")
    reference = args.get("reference")
    if reference is None:
        return args
    if not isinstance(reference, str) or not 0 < len(reference) <= 80:
        raise ValueError("reference must be a line media id")
    if store is None or not store._query("SELECT id FROM images WHERE id=? AND conv_id=?",
                                       (reference, conv_id)):
        raise ValueError("reference is not media on this line")
    found = store.file_for(reference, "readable")
    if found is None or not found[1].startswith("image/"):
        raise ValueError("reference image can no longer be read")
    try:
        with found[0].open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError("reference source exceeds 20 MiB; upload a smaller image")
        with Image.open(io.BytesIO(data)) as image:
            if not (MIN_SIDE <= image.width <= MAX_SIDE and MIN_SIDE <= image.height <= MAX_SIDE):
                raise ValueError("reference dimensions must be 16..2048; resize it before uploading")
            output = io.BytesIO()
            alpha = "A" in image.getbands() or "transparency" in image.info
            image.convert("RGBA" if alpha else "RGB").save(output, "PNG")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("reference is not a readable image") from exc
    binary = output.getvalue()
    if len(binary) > MAX_REFERENCE_BYTES:
        raise ValueError("reference PNG exceeds 700 KiB; upload a smaller image")
    return {**args, "reference": {"id": reference, "png_base64": base64.b64encode(binary).decode("ascii")}}


def validate_message(message):
    """Bound the whole envelope too, including escaping and any extra REST arguments."""
    if len(json.dumps(message).encode("utf-8")) > MAX_HELPER_MESSAGE_BYTES:
        raise ValueError("reference call exceeds the helper's 1 MB message limit; send fewer arguments")
