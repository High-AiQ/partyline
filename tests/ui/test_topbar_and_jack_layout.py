"""Browser regressions for top-bar state contrast and process-card wrapping.

Run explicitly: ``uv run --locked python -m unittest tests/ui/test_topbar_and_jack_layout.py``.
These are rendered-CSS and geometry assertions, so they belong in the browser
suite rather than duplicating the component markup in a unit test.
"""

import re
import unittest

from scripts.uishot import seed_room, ui_session


def _rgb(value):
    return tuple(int(channel) / 255 for channel in re.findall(r"[\d.]+", value)[:3])


def _luminance(value):
    channels = [channel / 12.92 if channel <= 0.04045 else
                ((channel + 0.055) / 1.055) ** 2.4 for channel in _rgb(value)]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(foreground, background):
    bright, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def _style(locator):
    return locator.evaluate("""el => {
      const style = getComputedStyle(el);
      return {
        color: style.color,
        background: style.backgroundColor,
        border: style.borderColor,
        outlineWidth: style.outlineWidth,
      };
    }""")


def _open_seeded_line(ui):
    page = ui.page
    with page.expect_response(lambda response: (
            "/api/conversations/" in response.url and response.request.method == "GET")):
        page.locator(".conv-row .conv").first.click()
    page.wait_for_selector("#composer")
    seed_room(page)


class TopBarAndJackLayoutTest(unittest.TestCase):
    def assert_contrast(self, locator, minimum=4.5):
        style = _style(locator)
        self.assertGreaterEqual(_contrast(style["color"], style["background"]), minimum)

    def test_topbar_actions_remain_legible_through_interaction_states(self):
        with ui_session(["alpha line"], handle="greg") as ui:
            page = ui.page
            _open_seeded_line(ui)
            selectors = [
                '.column-toggle[aria-controls="rail"]',
                '.column-toggle[aria-controls="board"]',
                ".task-toggle",
                ".account .handle",
                ".account .logout",
            ]
            for selector in selectors:
                action = page.locator(selector)
                self.assert_contrast(action)

                action.hover()
                page.wait_for_timeout(200)
                self.assert_contrast(action)

                page.mouse.down()
                page.wait_for_timeout(200)
                self.assert_contrast(action)
                page.mouse.move(640, 400)
                page.mouse.up()

                action.focus()
                page.keyboard.press("Tab")
                page.keyboard.press("Shift+Tab")
                self.assertTrue(action.evaluate("el => el.matches(':focus-visible')"))
                self.assertGreaterEqual(float(_style(action)["outlineWidth"][:-2]), 2)
                self.assert_contrast(action)

            for side in ("rail", "board"):
                toggle = page.locator(f'.column-toggle[aria-controls="{side}"]')
                toggle.click()
                page.locator("#feed").hover()
                page.wait_for_timeout(200)
                self.assertEqual(toggle.get_attribute("aria-expanded"), "false")
                self.assert_contrast(toggle)

            disabled = page.locator(".task-toggle")
            disabled.evaluate("el => { el.disabled = true; }")
            disabled.hover()
            page.wait_for_timeout(200)
            self.assert_contrast(disabled)

            board = page.locator('.column-toggle[aria-controls="board"]')
            board.evaluate("el => { el.disabled = false; }")
            board.hover()
            page.wait_for_timeout(200)
            led = board.locator(".led")
            self.assertGreaterEqual(
                _contrast(_style(led)["background"], _style(board)["background"]), 3)

    def test_process_header_wraps_between_complete_items_without_collisions(self):
        with ui_session(["alpha line"], viewport={"width": 900, "height": 800}) as ui:
            page = ui.page
            _open_seeded_line(ui)
            page.evaluate("""() => {
              const partyline = window.partyline;
              const conversationId = partyline.room.conversation.id;
              partyline.room.attachments = [];
              partyline.room.upsertAttachment({
                id: 'att-sol-2', conv_id: conversationId, name: 'sol-2', adapter: 'codex',
                command: ['codex'], cwd: '/tmp/project', status: 'running',
                last_seen: 1, created_at: 1, cli_session: null,
                cwd_git: {sha: '2090a87', dirty: false},
              });
              partyline.room.setCaptain(conversationId, 'att-sol-2');
              partyline.presence.apply({
                type: 'working', attachment_id: 'att-sol-2', working: true,
                phase: 'working', completion: 'receipt', since: Date.now() / 1000,
                turn: 1, revision: 1,
              });
            }""")
            page.wait_for_selector(".jack .captain-badge")
            page.wait_for_selector(".jack .working")

            geometry = page.locator(".jack").evaluate("""card => {
              const row = card.querySelector('.row');
              const name = card.querySelector('.name');
              const close = card.querySelector('.x');
              const range = document.createRange();
              range.selectNodeContents(name);
              const rect = element => element.getBoundingClientRect();
              const overlap = (a, b) =>
                a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
              const closeRect = rect(close);
              const items = [...row.children].filter(item => item !== close);
              return {
                nameLines: range.getClientRects().length,
                inside: items.every(item => {
                  const itemRect = rect(item);
                  const rowRect = rect(row);
                  return itemRect.left >= rowRect.left && itemRect.right <= rowRect.right;
                }),
                clearsClose: items.every(item => !overlap(rect(item), closeRect)),
                badgesOverlap: overlap(
                  rect(card.querySelector('.captain-badge')),
                  rect(card.querySelector('.working')),
                ),
              };
            }""")
            self.assertEqual(geometry["nameLines"], 1)
            self.assertTrue(geometry["inside"])
            self.assertTrue(geometry["clearsClose"])
            self.assertFalse(geometry["badgesOverlap"])


if __name__ == "__main__":
    unittest.main()
