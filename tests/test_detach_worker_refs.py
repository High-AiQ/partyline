"""detach_worker and the other captain ops resolve a task's tag, handle or line name."""

from fastapi import HTTPException

from partyline.auth_guard import Principal
from partyline.machine_scope import capability_state
from partyline.mcp import tools_captain
from partyline.mcp.client import ApiError
from partyline.orchestrator_handles import capabilities_for
from tests.orchestrator_fixture import TaskFixture


class DbClient:
    """The MCP client over the real resolver and database; DELETE only records the call."""

    def __init__(self, db, principal):
        self.db, self.principal, self.home = db, principal, principal.conv_id
        self.calls = []

    def capabilities(self, conv_id=None):
        try:
            return capabilities_for(self.db, self.principal, conv_id)
        except HTTPException as exc:
            raise ApiError(f"Partyline HTTP {exc.status_code}: {exc.detail}") from exc

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and "/staffing" not in path:
            conv = self.db.get_conversation(path.rsplit("/", 1)[1])
            return {"conversation": conv, "attachments": self.db.list_attachments(conv["id"])}
        return {"ok": True}


class DetachWorkerRefTest(TaskFixture):
    async def asyncSetUp(self):
        self.row = await self.create()
        self.state = capability_state(self.db, self.captain)
        self.client = DbClient(self.db, self.captain)
        self.line_name = self.db.get_conversation(self.conv_id)["name"]

    def detach(self, conv, ref, client=None, state=None):
        return tools_captain.call(client or self.client, "captain", {"op": "detach_worker", "args": {
            "conv_id": conv, "attachment_id": ref}}, state or self.state)

    def deletes(self):
        return [call for call in self.client.calls if call[0] == "DELETE"]

    def test_line_id_tag_handle_and_name_all_detach_the_worker(self):
        impl = self.row["implementer_id"]
        for ref in (self.conv_id, self.row["tag"],
                    self.row["implementer_handle"], self.line_name):
            self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (impl,))
            self.client.calls.clear()
            self.detach(ref, self.row["implementer_handle"])
            self.assertEqual(self.deletes(), [("DELETE", f"/api/attachments/{impl}", None)], ref)
            self.assertIn(("GET", f"/api/conversations/{self.conv_id}", None), self.client.calls)

    def test_an_unknown_ref_is_named_and_is_not_an_authorization_failure(self):
        with self.assertRaisesRegex(ApiError, "404: no line or task matches 'nope99'"):
            self.detach("nope99", self.row["implementer_handle"])
        self.assertFalse(self.deletes())

    def test_a_real_authorization_refusal_stays_not_authorized(self):
        self.db.create_conversation("elsewhere", "Elsewhere")
        self.db.add_attachment("stranger", "elsewhere", "stranger", "fake", ["fake"], self.repo, "o")
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='stranger'")
        stranger = Principal(kind="machine", name="stranger", conv_id="elsewhere",
                             attachment_id="stranger", is_lead=True)
        client, state = DbClient(self.db, stranger), capability_state(self.db, stranger)
        with self.assertRaisesRegex(ApiError, "captain is not authorized for that target line"):
            self.detach(self.conv_id, self.row["implementer_handle"], client, state)
        self.assertFalse([call for call in client.calls if call[0] == "DELETE"])

    def test_an_already_detached_worker_is_an_idempotent_success(self):
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (self.row["implementer_id"],))
        for conv in (self.row["tag"], self.conv_id):
            result = self.detach(conv, self.row["implementer_handle"])
            self.assertTrue(result["already_detached"])
            self.assertEqual(result["attachment_id"], self.row["implementer_id"])
            self.assertIn(f"{self.row['implementer_handle']} is not attached to «{self.line_name}»",
                          result["message"])
        by_id = self.detach(self.conv_id, self.row["implementer_id"])
        self.assertTrue(by_id["already_detached"])
        self.assertFalse(self.deletes())

    async def test_another_lines_handle_is_refused_naming_the_line(self):
        second = await self.create()
        with self.assertRaisesRegex(
                ApiError, f"no attachment or handle '{second['implementer_handle']}' on «{self.line_name}»"):
            self.detach(self.row["tag"], second["implementer_handle"])
        self.assertFalse(self.deletes())

    def test_other_captain_ops_take_the_same_refs(self):
        result = tools_captain.call(self.client, "captain", {"op": "staffing", "args": {
            "conv_id": self.row["tag"]}}, self.state)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.client.calls[-1][1], f"/api/conversations/{self.conv_id}/staffing")

    def test_a_line_name_up_to_120_characters_passes_the_schema(self):
        name = "n" * 120
        self.db.rename_conversation(self.conv_id, name)
        self.detach(name, self.row["implementer_handle"])
        self.assertEqual(len(self.deletes()), 1)
        with self.assertRaisesRegex(ValueError, "exceeds its allowed length"):
            self.detach("n" * 121, self.row["implementer_handle"])
