"""Visual states for the desktop side-column controls, and the states the
healthy parity set never reaches."""


def capture_line_details(ui) -> None:
    """Capture the detailed line elements before the responsive states."""
    ui.element_shot("10-message-process", ".msg:nth-of-type(2)")
    ui.element_shot("11-message-human", ".msg:nth-of-type(1)")
    ui.element_shot("12-board-jacks", "#jacks")


def capture_desktop_columns(ui, viewport) -> None:
    """Capture every collapse combination and the compact desktop breakpoint."""
    page = ui.page
    page.set_viewport_size(viewport)
    page.wait_for_timeout(250)
    lines_toggle = page.locator('.column-toggle[aria-controls="rail"]')
    jacks_toggle = page.locator('.column-toggle[aria-controls="board"]')
    lines_toggle.click()
    page.wait_for_timeout(250)
    ui.shot("12a-desktop-rail-collapsed")
    lines_toggle.click()
    jacks_toggle.click()
    page.wait_for_timeout(250)
    ui.shot("12b-desktop-board-collapsed")
    lines_toggle.click()
    page.wait_for_timeout(250)
    ui.shot("12c-desktop-both-collapsed")
    lines_toggle.click()
    jacks_toggle.click()
    page.wait_for_timeout(250)
    page.set_viewport_size({"width": 900, "height": 800})
    page.wait_for_timeout(250)
    ui.shot("12d-desktop-compact-controls")


def capture_extra_states(ui) -> None:
    """Capture the states the healthy parity set never reaches.

    The gate needs an unauthenticated context and the wire banners need a
    notice or a dead server — none of which the signed-in, healthy captures
    exercise, so a styling conversion moved them unwatched once. The outage is
    captured last of all because it kills the server.
    """
    capture_gate(ui)
    capture_wire_states(ui)


def capture_gate(ui) -> None:
    """The pre-auth gate, rendered by a second context with no tokens."""
    from scripts import uishot

    page = ui.page
    context = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        gate_page = context.new_page()
        gate_page.goto(ui.base_url)
        gate_page.wait_for_selector("#authForm", timeout=15000)
        if ui.still_frames:
            gate_page.evaluate(uishot.SETTLE_ANIMATIONS)
        path = ui.out_dir / "18-gate.png"
        gate_page.screenshot(path=str(path))
        ui.shots.append(path)
    finally:
        context.close()


def capture_wire_states(ui) -> None:
    """The notice toast and the outage banner, then kill the server."""
    page = ui.page
    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_timeout(250)
    page.evaluate("() => window.partyline.room.showNotice('we dropped a beat', 'error')")
    page.wait_for_selector("#wireNotice")
    ui.settle_animations()
    ui.shot("19-wire-notice")
    ui.stop_server()
    page.wait_for_selector("#wireDown")
    ui.settle_animations()
    ui.shot("20-wire-down")
