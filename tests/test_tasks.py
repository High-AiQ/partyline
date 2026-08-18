"""The shared task board: store, routes, and the wake-digest rider."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.db import Db
from partyline.runtime import ChatRuntime
from partyline.task_routes import task_router
from partyline.tasks import TaskError, TaskStore, task_rider


class TaskStoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.store = TaskStore(self.db)
        self.addCleanup(self.db.close)
        self.addCleanup(self.directory.cleanup)

    def test_add_stamps_and_defaults_a_task(self):
        task = self.store.add("line", "  ship the feature  ")
        self.assertEqual(task["body"], "ship the feature")
        self.assertEqual(task["status"], "open")
        self.assertIsNone(task["owner"])
        self.assertGreater(task["created_at"], 0)

    def test_a_blank_or_oversized_body_is_refused(self):
        with self.assertRaises(TaskError):
            self.store.add("line", "   ")
        with self.assertRaises(TaskError):
            self.store.add("line", "x" * 501)

    def test_an_owner_is_normalised(self):
        task = self.store.add("line", "review", owner=" @glm ")
        self.assertEqual(task["owner"], "glm")
        self.assertIsNone(self.store.add("line", "other", owner="  ")["owner"])

    def test_an_oversized_owner_is_refused(self):
        with self.assertRaises(TaskError):
            self.store.add("line", "ok body", owner="x" * 101)

    def test_update_can_rewrite_the_body(self):
        task = self.store.add("line", "vague")
        self.assertEqual(
            self.store.update(task["id"], body="  precise  ")["body"], "precise")

    def test_the_store_rider_summarises_open_tasks_only(self):
        self.assertEqual(self.store.rider("line"), "")
        task = self.store.add("line", "review backend", owner="grok")
        done = self.store.add("line", "already finished")
        self.store.update(done["id"], status="done")
        self.assertEqual(
            self.store.rider("line"),
            f"(open tasks: #{task['id']} review backend (@grok))")

    def test_get_of_an_unknown_task_is_a_loud_404(self):
        with self.assertRaises(TaskError) as raised:
            self.store.get(999)
        self.assertEqual(raised.exception.status_code, 404)

    def test_update_changes_only_the_given_fields(self):
        task = self.store.add("line", "first", owner="a")
        updated = self.store.update(task["id"], status="done")
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["body"], "first")
        self.assertEqual(updated["owner"], "a")
        self.assertGreaterEqual(updated["updated_at"], task["created_at"])

    def test_update_can_clear_an_owner_with_explicit_none(self):
        task = self.store.add("line", "first", owner="a")
        self.assertIsNone(self.store.update(task["id"], owner=None)["owner"])

    def test_update_rejects_a_bad_status(self):
        task = self.store.add("line", "first")
        with self.assertRaises(TaskError):
            self.store.update(task["id"], status="doing")

    def test_list_filters_by_status(self):
        self.store.add("line", "one")
        two = self.store.add("line", "two")
        self.store.update(two["id"], status="done")
        self.assertEqual(
            [t["body"] for t in self.store.list("line", status="open")], ["one"])
        self.assertEqual(len(self.store.list("line")), 2)
        with self.assertRaises(TaskError):
            self.store.list("line", status="doing")

    def test_delete_removes_the_task(self):
        task = self.store.add("line", "gone")
        self.store.delete(task["id"])
        with self.assertRaises(TaskError):
            self.store.get(task["id"])


class TaskRiderTest(unittest.TestCase):
    def test_no_open_tasks_means_no_rider_line(self):
        self.assertEqual(task_rider([]), "")

    def test_open_tasks_are_listed_with_their_owners(self):
        rider = task_rider([
            {"id": 1, "body": "review backend", "owner": "grok"},
            {"id": 2, "body": "write docs", "owner": None},
        ])
        self.assertEqual(
            rider, "(open tasks: #1 review backend (@grok); #2 write docs)")


class TaskApiTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.store = TaskStore(self.db)
        app = FastAPI()
        app.include_router(task_router(self.runtime, self.store))
        self.client = TestClient(app)
        self.db.create_conversation("line", "Line")
        self.addCleanup(self.db.close)
        self.addCleanup(self.directory.cleanup)

    def test_the_full_lifecycle_over_rest(self):
        created = self.client.post(
            "/api/conversations/line/tasks",
            json={"body": "land the PR", "owner": "opus"})
        self.assertEqual(created.status_code, 201)
        task = created.json()
        self.assertEqual(task["status"], "open")

        done = self.client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["status"], "done")

        listed = self.client.get("/api/conversations/line/tasks").json()
        self.assertEqual([t["id"] for t in listed], [task["id"]])
        open_only = self.client.get(
            "/api/conversations/line/tasks", params={"status": "open"}).json()
        self.assertEqual(open_only, [])

        self.assertEqual(self.client.delete(f"/api/tasks/{task['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/conversations/line/tasks").json(), [])

    def test_a_patch_with_no_fields_changes_nothing_but_the_timestamp(self):
        task = self.client.post(
            "/api/conversations/line/tasks", json={"body": "stay"}).json()
        patched = self.client.patch(f"/api/tasks/{task['id']}", json={}).json()
        self.assertEqual(patched["body"], "stay")

    def test_an_explicit_null_owner_clears_an_omitted_one_does_not(self):
        task = self.client.post(
            "/api/conversations/line/tasks",
            json={"body": "keep owner", "owner": "sol"}).json()
        patched = self.client.patch(f"/api/tasks/{task['id']}", json={}).json()
        self.assertEqual(patched["owner"], "sol")
        cleared = self.client.patch(
            f"/api/tasks/{task['id']}", json={"owner": None}).json()
        self.assertIsNone(cleared["owner"])

    def test_validation_is_loud_not_silent(self):
        empty = self.client.post("/api/conversations/line/tasks", json={"body": ""})
        self.assertEqual(empty.status_code, 422)
        missing = self.client.patch("/api/tasks/4242", json={"status": "done"})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self.client.delete("/api/tasks/4242").status_code, 404)
        bad_filter = self.client.get(
            "/api/conversations/line/tasks", params={"status": "doing"})
        self.assertEqual(bad_filter.status_code, 400)
        no_line = self.client.get("/api/conversations/nope/tasks")
        self.assertEqual(no_line.status_code, 404)

    def test_an_archived_line_refuses_writes_but_still_reads(self):
        self.client.post("/api/conversations/line/tasks", json={"body": "frozen"})
        self.db.archive_conversation("line")
        write = self.client.post(
            "/api/conversations/line/tasks", json={"body": "nope"})
        self.assertEqual(write.status_code, 409)
        task = self.client.get("/api/conversations/line/tasks").json()[0]
        patch = self.client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
        self.assertEqual(patch.status_code, 409)
        self.assertEqual(len(self.client.get("/api/conversations/line/tasks").json()), 1)


if __name__ == "__main__":
    unittest.main()
