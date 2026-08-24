"""Visual states for the desktop side-column controls."""


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
