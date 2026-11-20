"""Suite browser spec: grouped field filling and dependent rerender recovery."""
import re
import unittest
from pathlib import Path
from urllib.parse import urlencode

from scripts.uishot import ui_session

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/screen-workflows"


def start_lab(ui, line):
    api = ui.page.request
    code = api.post(f"{ui.base_url}/api/screen/pair?conv_id={line}", headers=ui.auth_headers).json()["code"]
    pair = api.post(ui.base_url + "/api/screen/pair/claim", data={
        "code": code, "device_name": "Lab window", "os": "test",
    })
    lab = ui.page.context.new_page()
    lab.goto(ui.base_url + "/lab/window-bench/workflow.html?scenario=publication-lock")
    lab.evaluate((FIXTURE / "document-helper.js").read_text(), {"token": pair.json()["token"], "line": line})
    return lab


def read(ui, line, **options):
    query = urlencode({"window": "document-window", **options})
    response = ui.page.request.post(
        f"{ui.base_url}/api/conversations/{line}/screen-elements?{query}", headers=ui.auth_headers)
    assert response.ok, response.text()
    return response.json()


def controls(result):
    found = {}
    for line in result.get("lines", "").splitlines():
        match = re.match(r"\s*(\S+)\s+\S+\s+\"([^\"]+)\"", line)
        if match:
            found[match.group(2)] = match.group(1)
    return found


def fill(ui, line, assignments, section):
    response = ui.page.request.post(
        f"{ui.base_url}/api/conversations/{line}/screen-control/element-action",
        headers=ui.auth_headers,
        data={"action": "set_values", "window": "document-window", "assignments": assignments,
              "then": {"root": section, "depth": 1}},
    )
    assert response.ok, response.text()
    return response.json()


class CompactFormBrowserTest(unittest.TestCase):
    def test_fill_and_recover_current_controls_without_submitting(self):
        with ui_session(["Compact forms"]) as ui:
            app = ui.page
            lines = app.request.get(ui.base_url + "/api/conversations", headers=ui.auth_headers).json()
            line = lines[0]["id"]
            lab = start_lab(ui, line)
            lab.locator("#add-text").click()
            section = controls(read(ui, line, query="=Module editor"))["Module editor"]
            fields = controls(read(ui, line, root=section, depth=1))

            result = fill(ui, line, [
                {"element_id": fields["Headline"], "value": "Fresh field input"},
                {"element_id": fields["Body text"], "value": "One grouped decision"},
            ], section)
            self.assertEqual(("completed", 2, 0),
                             (result["status"], result["completed"], result["remaining"]))
            self.assertIn("Fresh field input", result["after"]["lines"])
            self.assertIn("set_value", result["after"]["lines"])
            self.assertEqual("Fresh field input", lab.locator("#module-headline").input_value())
            self.assertEqual("One grouped decision", lab.locator("#module-body").input_value())
            self.assertEqual(0, lab.locator("#saved-modules li").count())

            lab.evaluate("""() => {
              const form = document.querySelector('#module-fields');
              const label = document.createElement('label');
              label.htmlFor = 'module-note';
              label.textContent = 'Note';
              const input = document.createElement('input');
              input.id = 'module-note';
              input.setAttribute('aria-label', 'Note');
              const wrap = document.createElement('p');
              wrap.append(label, input);
              form.append(wrap);
              document.querySelector('#module-headline').addEventListener('input', () => {
                const old = document.querySelector('#module-body');
                const replacement = document.createElement('textarea');
                replacement.id = 'module-body-current';
                replacement.setAttribute('aria-label', 'Body text current');
                old.replaceWith(replacement);
              }, { once: true });
            }""")
            fields = controls(read(ui, line, root=section, depth=1, refresh=True))
            result = fill(ui, line, [
                {"element_id": fields["Headline"], "value": "Rerender trigger"},
                {"element_id": fields["Body text"], "value": "Must not dispatch"},
                {"element_id": fields["Note"], "value": "Not attempted"},
            ], section)
            self.assertEqual(("partial", 1, 1),
                             (result["status"], result["completed"], result["remaining"]))
            self.assertEqual("target_changed", result["results"][1]["reason"])
            current = controls(result["after"])
            self.assertIn("Body text current", current)
            self.assertIn("set_value", next(line for line in result["after"]["lines"].splitlines()
                                            if "Body text current" in line))
            self.assertEqual("", lab.locator("#module-note").input_value())

            recovered = fill(ui, line, [
                {"element_id": current["Body text current"], "value": "Replacement only"},
                {"element_id": current["Note"], "value": "Remaining field"},
            ], section)
            self.assertEqual("completed", recovered["status"])
            self.assertEqual("Replacement only", lab.locator("#module-body-current").input_value())
            self.assertEqual("Remaining field", lab.locator("#module-note").input_value())
            self.assertEqual("Rerender trigger", lab.locator("#module-headline").input_value())
            self.assertEqual(0, lab.locator("#saved-modules li").count())


if __name__ == "__main__":
    unittest.main()
