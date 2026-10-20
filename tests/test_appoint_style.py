"""Appointing a captain applies the style chosen in the same dialog, before the brief."""

from tests.test_hierarchy import HierarchyApiTest, setUpModule, tearDownModule  # noqa: F401


class AppointStyleTest(HierarchyApiTest):
    def appoint(self, **body):
        return self.client.post("/api/conversations/parent/lead",
                                json={"attachment_id": "lead-att", **body})

    def clear(self):
        self.client.post("/api/conversations/parent/lead", json={"attachment_id": None})

    def test_the_first_pack_is_the_orchestrator_pack(self):
        self.clear()
        response = self.appoint(captain_mode="orchestrator", default_review_policy="none")
        self.assertEqual(response.status_code, 200, response.text)
        conv = self.db.get_conversation("parent")
        self.assertEqual((conv["captain_mode"], conv["default_review_policy"]), ("orchestrator", "none"))
        briefing = self.client.get("/api/conversations/parent/briefing", headers=self.lead)
        self.assertIn("## Orchestrator captain pack", briefing.json()["briefing"])

    def test_a_restyle_rings_a_captain_who_was_already_appointed(self):
        response = self.appoint(captain_mode="orchestrator")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.get_conversation("parent")["captain_mode"], "orchestrator")

    def test_an_invalid_style_is_rejected_without_appointing(self):
        self.clear()
        self.assertEqual(self.appoint(captain_mode="pirate").status_code, 422)
        self.assertEqual(self.appoint(captain_mode="orchestrator",
                                      default_review_policy="no-such-preset").status_code, 400)
        self.assertEqual(self.client.get("/api/conversations/parent/lead").json()["attachment_id"], None)
        self.assertEqual(self.db.get_conversation("parent")["captain_mode"], "manager_tree")

    def test_a_machine_cannot_pass_a_style(self):
        response = self.client.post("/api/conversations/parent/lead", headers=self.lead,
                                    json={"attachment_id": "impl-att", "captain_mode": "orchestrator"})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.db.get_conversation("parent")["captain_mode"], "manager_tree")

    def test_a_failed_appointment_restores_the_previous_style(self):
        self.clear()
        response = self.client.post("/api/conversations/parent/lead",
                                    json={"attachment_id": "missing", "captain_mode": "orchestrator"})
        self.assertGreaterEqual(response.status_code, 400)
        self.assertEqual(self.db.get_conversation("parent")["captain_mode"], "manager_tree")
