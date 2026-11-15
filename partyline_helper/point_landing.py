"""Text-free evidence for point input, including refusals before dispatch."""
from contextlib import contextmanager

from partyline.point_geometry import GeometryError, locate


def evidence(entry, message):
    record = entry.get("snapshots", {}).get(message.get("snapshot"))
    geometry = record["geometry"] if record else None
    points = []
    for x, y in (("x", "y"), ("x2", "y2"))[:2 if message.get("op") == "drag" else 1]:
        if x not in message:
            continue
        screen = None
        if geometry:
            try:
                screen = list(locate(geometry, message.get(x), message.get(y)))
            except GeometryError:
                pass
        points.append({"snapshot_point": [message.get(x), message.get(y)], "screen_point": screen,
                       "hwnd": None, "class": None, "granted_window": None, "page_area_child": None,
                       "landed_in": None})
    return {"snapshot": message.get("snapshot"), "points": points,
            "dpi": geometry["dpi"] if geometry else None,
            "dpi_scale": geometry["dpi"] / 96 if geometry else None,
            "image_scale": geometry["scale"] if geometry else None,
            "foreground_before": None, "foreground_after": None, "input_sent": False}


def describe_hit(api, hwnd, granted):
    details = api.describe(hwnd, granted)
    root = api.root(hwnd)
    verdict = ("granted_window" if hwnd == granted else
               "granted_page" if root == granted else "other_window")
    details["landed_in"] = verdict
    if verdict == "other_window":
        details["warning"] = "hit another window: " + str(details.get("class") or "unknown class")
    return details


def observe(api, grant, landing):
    for point in landing["points"]:
        if point["screen_point"] is not None:
            hwnd = api.window_at(*point["screen_point"])
            point.update(describe_hit(api, hwnd, grant["hwnd"]))


def before(api, grant, landing):
    landing["foreground_before"] = api.owns(api.foreground())
    observe(api, grant, landing)


def after(api, landing):
    landing["foreground_after"] = api.owns(api.foreground())


@contextmanager
def landing_session(api, grant, landing, page):
    """Evidence around one page click: before it goes out, and on every path out of it.

    Whatever the click did, `input_sent` is recorded and the foreground is read again; if that read fails the
    failure is noted in the evidence and never replaces the click's own error."""
    with api.session():
        before(api, grant, landing)
    try:
        yield
    finally:
        landing["input_sent"] = page.dispatched
        try:
            with api.session():
                after(api, landing)
        except Exception:  # noqa: BLE001 - the foreground is evidence only
            landing["after_error"] = "foreground not read"
