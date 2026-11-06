"""Map macOS desktop points to uniform-density backing pixels."""


def scale_factor():
    import Quartz

    error, displays, count = Quartz.CGGetActiveDisplayList(128, None, None)
    if error or not count:
        raise RuntimeError("Unable to enumerate macOS displays")
    scales = set()
    for display in displays[:count]:
        bounds = Quartz.CGDisplayBounds(display)
        scales.add(round(Quartz.CGDisplayPixelsWide(display) / bounds.size.width, 4))
    if len(scales) != 1:
        raise RuntimeError("Mixed Retina display scales are not supported yet; "
                           "use displays with the same scale")
    return scales.pop()


def pointer_y_offset():
    """pynput 1.8 flips AppKit Y using CGDisplayPixelsHigh(0), not point height."""
    import Quartz

    height = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size.height
    return height - Quartz.CGDisplayPixelsHigh(0)
