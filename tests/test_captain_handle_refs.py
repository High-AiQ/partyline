"""Captain worker ops accept a process handle on the target line as well as an attachment id."""

import unittest

from partyline.mcp import tools_captain
from partyline.mcp.client import ApiError

LEAD = {"kind": "machine", "role": "lead", "is_lead": True, "conv_id": "home",
        "attachment_id": "lead", "actions": ["read", "assign", "close", "attach", "appoint_lead"]}


class Client:
    def __init__(self, rows):
        self.home = "home"
        self.rows = rows
        self.calls = []

    def capabilities(self, conv_id=None):
        return {**LEAD, "conv_id": conv_id}

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/api/conversations/child":
            return {"attachments": self.rows}
        return {"ok": True}


ROWS = [
    {"id": "att-1111", "name": "impl-48da9d", "status": "running"},
    {"id": "att-2222", "name": "review-48da9d", "status": "running"},
    {"id": "att-3333", "name": "impl-old000", "status": "exited"},
]


class HandleRefTests(unittest.TestCase):
    def detach(self, client, ref):
        return tools_captain.call(client, "captain", {"op": "detach_worker", "args": {
            "conv_id": "child", "attachment_id": ref}}, LEAD)

    def test_detach_by_attachment_id_is_unchanged(self):
        client = Client(ROWS)
        self.detach(client, "att-2222")
        self.assertEqual(client.calls[-1], ("DELETE", "/api/attachments/att-2222", None))

    def test_detach_by_live_handle_resolves_to_its_attachment(self):
        client = Client(ROWS)
        self.detach(client, "impl-48da9d")
        self.assertEqual(client.calls[-1], ("DELETE", "/api/attachments/att-1111", None))

    def test_detach_by_handle_ignores_a_stopped_row_with_the_same_name(self):
        rows = [*ROWS, {"id": "att-4444", "name": "impl-48da9d", "status": "exited"}]
        client = Client(rows)
        self.detach(client, "impl-48da9d")
        self.assertEqual(client.calls[-1], ("DELETE", "/api/attachments/att-1111", None))

    def test_detach_by_a_handle_naming_two_live_rows_is_refused(self):
        rows = [*ROWS, {"id": "att-5555", "name": "impl-48da9d", "status": "idle"}]
        client = Client(rows)
        with self.assertRaisesRegex(ApiError, "names 2 live attachments"):
            self.detach(client, "impl-48da9d")
        self.assertFalse([call for call in client.calls if call[0] == "DELETE"])

    def test_detach_by_unknown_handle_or_foreign_id_is_refused_without_delete(self):
        client = Client(ROWS)
        with self.assertRaisesRegex(ApiError, "not on the authorized target line"):
            self.detach(client, "impl-zzzzzz")
        with self.assertRaisesRegex(ApiError, "not on the authorized target line"):
            self.detach(client, "att-9999")
        self.assertFalse([call for call in client.calls if call[0] == "DELETE"])

    def test_appoint_lead_resolves_a_handle_and_clears_on_empty(self):
        client = Client(ROWS)
        tools_captain.call(client, "captain", {"op": "appoint_lead", "args": {
            "conv_id": "child", "attachment_id": "impl-48da9d"}}, LEAD)
        self.assertEqual(client.calls[-1], ("POST", "/api/conversations/child/lead",
                                            {"attachment_id": "att-1111"}))
        tools_captain.call(client, "captain", {"op": "appoint_lead", "args": {
            "conv_id": "child", "attachment_id": ""}}, LEAD)
        self.assertEqual(client.calls[-1][2], {"attachment_id": None})

    def test_appoint_lead_passes_an_unknown_id_to_the_server_unchanged(self):
        client = Client(ROWS)
        tools_captain.call(client, "captain", {"op": "appoint_lead", "args": {
            "conv_id": "child", "attachment_id": "att-7777"}}, LEAD)
        self.assertEqual(client.calls[-1][2], {"attachment_id": "att-7777"})


if __name__ == "__main__":
    unittest.main()
