"""Unavailable landing fields for server refusals, old helpers and transport timeouts."""


def unavailable(body, geometry, points=()):
    return {"snapshot": getattr(body, "snapshot", None),
            "points": [{"snapshot_point": list(pixel),
                        "screen_point": list(points[index]) if index < len(points) else None,
                        "hwnd": None, "class": None, "granted_window": None, "page_area_child": None,
                        "landed_in": None}
                       for index, pixel in enumerate(body.pixels())],
            "dpi": geometry["dpi"] if geometry else None,
            "dpi_scale": geometry["dpi"] / 96 if geometry else None,
            "image_scale": geometry["scale"] if geometry else None,
            "foreground_before": None, "foreground_after": None, "input_sent": None}
