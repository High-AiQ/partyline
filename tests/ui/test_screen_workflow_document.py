"""Browser spec for a composed workflow against the live document lab."""

import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import expect

from scripts.uishot import ui_session

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/screen-workflows"


def place_checkout(ui, line, directory):
    with open(f"/proc/{ui.server.pid}/environ", "rb") as environ:
        path = next(entry.removeprefix(b"PARTYLINE_DB=") for entry in environ.read().split(b"\0")
                    if entry.startswith(b"PARTYLINE_DB="))
    with sqlite3.connect(os.fsdecode(path)) as db:
        db.execute("UPDATE conversations SET cwd=? WHERE id=?", (str(directory), line))


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


def start_run(ui, line):
    api = ui.page.request
    image = io.BytesIO()
    Image.new("RGB", (16, 16), "#badc9e").save(image, format="PNG")
    response = api.post(f"{ui.base_url}/api/conversations/{line}/files", headers=ui.auth_headers,
                        multipart={"file": {"name": "meadow.png", "mimeType": "image/png",
                                            "buffer": image.getvalue()}})
    if not response.ok:
        raise AssertionError(response.text())
    parameters = json.loads((FIXTURE / "publish-document/parameters.json").read_text())
    parameters["modules"][0]["images"] = [response.json()["files"][0]["id"]]
    path = f"{ui.base_url}/api/conversations/{line}/screen-workflows/runs"
    response = api.post(path, headers=ui.auth_headers, data={
        "workflow": "publish-document", "window": "document-window",
        "parameters": parameters, "client_key": "document-lab",
    })
    if not response.ok:
        raise AssertionError(response.text())
    return f"{path}/{response.json()['run_id']}"


class DocumentWorkflowBrowserTest(unittest.TestCase):
    def test_approve_confirm_stop_and_resume_from_the_publish_step(self):
        rate = {"PARTYLINE_CONTROL_RATE": "120"}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, rate):
            workspace = Path(temporary)
            shutil.copytree(FIXTURE / "publish-document", workspace / ".partyline/workflows")
            with ui_session(["Document work"]) as ui:
                app = ui.page
                lines = app.request.get(ui.base_url + "/api/conversations", headers=ui.auth_headers)
                line = lines.json()[0]["id"]
                place_checkout(ui, line, workspace)
                lab = start_lab(ui, line)
                app.locator(".conv-row").first.click()
                ui.open_row_menu().get_by_role("menuitem", name="workflows").click()
                panel = app.get_by_role("dialog", name="Screen workflows")
                panel.get_by_role("button", name="Review publish-document").click()
                effect = panel.get_by_text("Confirmation required · Publish the document", exact=False)
                expect(effect).to_be_visible()
                expect(panel.get_by_text("cdp.set_files", exact=False).first).to_be_visible()
                panel.get_by_role("button", name="Approve", exact=True).click()
                expect(panel.get_by_role("button", name="Revoke")).to_be_visible()
                panel.get_by_role("button", name="close").click()

                audit = start_run(ui, line) + "/audit"
                card = app.get_by_role("article", name="publish-document")
                expect(card.get_by_role("button", name="Confirm")).to_be_visible()
                expect(lab.locator("#saved-modules li")).to_have_count(3)
                expect(lab.locator("#saved-modules")).to_contain_text("A trail through a meadow")
                expect(lab.locator("#saved-modules")).to_contain_text("Field observations")
                expect(lab.locator("#saved-modules")).to_contain_text("Seasonal")
                expect(lab.locator("#saved-modules")).to_contain_text("Open all year")
                card.get_by_role("button", name="Cancel").click()
                expect(card).to_contain_text("confirmation denied")
                expect(lab.locator("#publish-status")).to_have_attribute("data-publishes", "0")

                lab.locator("#block-publishing").check()
                card.get_by_role("button", name="Resume").click()
                expect(card).to_contain_text("precondition failed")
                expect(lab.locator("#saved-modules li")).to_have_count(3)
                lab.locator("#block-publishing").uncheck()
                card.get_by_role("button", name="Resume").click()
                card.get_by_role("button", name="Confirm").click()
                expect(card).to_contain_text("Completed")
                expect(lab.locator("#publish-status")).to_have_attribute("data-publishes", "1")
                expect(lab.locator("#saved-modules li")).to_have_count(3)
                report = app.request.get(audit, headers=ui.auth_headers).json()
                committed = [e["step_index"] for e in report["events"] if e["event"] == "verified"]
                self.assertEqual(committed, list(range(1, report["total_steps"] + 1)))
