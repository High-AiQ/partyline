"""Read delivered image geometry locally without decoding pixels or extra HTTP."""

from PIL import Image


def image_dimensions(path):
    try:
        with Image.open(path) as image:
            return {"width": image.width, "height": image.height}
    except Exception:
        return {}  # best-effort metadata must never turn a successful download into a tool error
