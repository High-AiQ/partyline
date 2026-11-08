"""Pointer state and additive stationary hints shared by walkthroughs and screen frames."""

from dataclasses import replace
import io

from PIL import Image, ImageChops, ImageStat

from .screen_frames import BufferedFrame


def captured_pointer(frame: BufferedFrame) -> bool:
    return bool(frame.pointer and frame.pointer.get("captured"))


def visually_identical(first: BufferedFrame, second: BufferedFrame) -> bool:
    if (first.region != second.region or
            (first.out_width, first.out_height) != (second.out_width, second.out_height)):
        return False
    if first.data == second.data:
        return True
    try:
        with Image.open(io.BytesIO(first.data)) as left, Image.open(io.BytesIO(second.data)) as right:
            left = left.convert("RGB").resize((128, 128))
            right = right.convert("RGB").resize((128, 128))
            diff = ImageStat.Stat(ImageChops.difference(left, right))
            return max(diff.mean) <= 1.0 and max(high for _, high in diff.extrema) <= 12
    except (OSError, ValueError):
        return False


def annotate_stationary_pointers(frames: list[BufferedFrame]) -> list[BufferedFrame]:
    """Annotate visible runs of >=3 samples within 3 pixels while the image changes.

    Use the full take before selection/deduplication, preserving the evidence even
    when only two distinct images survive. Copies keep inference out of raw buffers.
    Stationarity never implies capture or changes marker coordinates. A region or
    output-size change starts a new run; slow drift cannot accumulate.
    """
    result = list(frames)
    start = 0
    while start < len(frames):
        first = frames[start]
        pointer = first.pointer
        if not pointer or not pointer.get("visible") or captured_pointer(first):
            start += 1
            continue
        low_x = high_x = pointer["x"]
        low_y = high_y = pointer["y"]
        end = start + 1
        changed = False
        while end < len(frames):
            frame = frames[end]
            p = frame.pointer
            if (not p or not p.get("visible") or captured_pointer(frame) or frame.region != first.region or
                    (frame.out_width, frame.out_height) != (first.out_width, first.out_height)):
                break
            low_x, high_x = min(low_x, p["x"]), max(high_x, p["x"])
            low_y, high_y = min(low_y, p["y"]), max(high_y, p["y"])
            if high_x - low_x > 3 or high_y - low_y > 3:
                break
            changed = changed or not visually_identical(first, frame)
            end += 1
        if end - start >= 3 and changed:
            for i in range(start, end):
                result[i] = replace(frames[i], pointer={**frames[i].pointer, "stationary": True})
        start = end
    return result
