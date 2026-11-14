"""bridge_send: an ambassador speaks over its bridge without using its turn's final text."""

import asyncio
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from partyline import bridge_delivery
from partyline.bridge_store import mark_closed
from partyline.capability_versions import CapabilityVersions
from partyline.mcp import catalog, tools_bridge
from partyline.mcp.client import ApiError
from partyline.mcp.server import MCPServer
from partyline.presence import Presence
from partyline.screen_capabilities import for_attachment
from tests import test_line_bridge as _bridge_tests
from tests.test_mcp import FakeClient

Base = _bridge_tests.LineBridgeTest


class BridgeSendTest(unittest.TestCase):
    setUp = Base.setUp
    machine = Base.machine
    open = Base.open
    say = Base.say
    rows = Base.rows
    opened = Base.opened

    def send(self, conv="x", att="x-amb", text="the frame was the only one", key=None, headers=None):
        body = {"text": text, **({"client_key": key} if key else {})}
        return self.client.post(f"/api/conversations/{conv}/bridge-send", json=body,
                                headers=headers or self.machine(att))

    def log(self, bridge):
        return self.client.get(f"/api/bridges/{bridge['id']}/messages", headers=self.person).json()

    def state(self, att):
        row = self.db.get_attachment(att)
        principal = SimpleNamespace(kind="machine", attachment_id=att, conv_id=row["conv_id"])
        return for_attachment(self.runtime, principal, None, {"actions": ["read", "write"]})

    def test_only_the_ambassador_of_an_open_bridge_is_offered_the_tool(self):
        self.assertFalse(self.state("x-amb")["bridge_open"])
        bridge = self.opened()
        self.assertTrue(self.state("x-amb")["bridge_open"])
        self.assertTrue(self.state("y-amb")["bridge_open"])
        for other in ("x-other", "y-other", "kid-amb"):
            self.assertFalse(self.state(other)["bridge_open"], other)
        self.assertEqual([t["name"] for t in tools_bridge.tool_list(self.state("x-amb"))], ["bridge_send"])
        self.assertEqual(tools_bridge.tool_list(self.state("x-other")), [])
        mark_closed(self.db, bridge["id"], "greg", "test")
        self.assertFalse(self.state("x-amb")["bridge_open"])

    def test_it_delivers_like_a_prefix_message_and_stays_out_of_both_chats(self):
        bridge = self.opened()
        sockets = {"x": _bridge_tests.Socket(), "y": _bridge_tests.Socket()}
        self.runtime.sockets["x"], self.runtime.sockets["y"] = {sockets["x"]}, {sockets["y"]}
        sent = self.send(text="plain words @greg #1")
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["status"], "delivered")
        self.assertEqual(sent.json()["to"], "fable")
        woken = self.adapters["y-amb"].delivered
        self.assertEqual([m["body"] for m in woken], ["plain words @greg #1"])
        self.assertEqual(woken[0]["audience_attachment_id"], "y-amb")
        self.assertEqual(woken[0]["source_conv_id"], "x")
        for other in ("x-amb", "x-other", "y-other"):
            self.assertEqual(self.adapters[other].delivered, [])
        for conv in ("x", "y"):
            page = self.client.get(f"/api/conversations/{conv}/messages", headers=self.person)
            self.assertFalse(any("plain words" in m["body"] for m in page.json()["messages"]), conv)
            self.assertEqual([p for p in sockets[conv].sent if p.get("type") == "message"], [], conv)
        self.assertEqual([m["body"] for m in self.log(bridge)], ["plain words @greg #1"])
        self.assertEqual([r["body"] for r in self.rows("x") if not r["bridge_id"]
                          and r["sender_type"] == "agent"], [])

    def test_the_peer_can_answer_with_the_tool_too(self):
        bridge = self.opened()
        self.send()
        reply = self.send("y", "y-amb", "got it")
        self.assertEqual(reply.json()["status"], "delivered")
        self.assertEqual([m["body"] for m in self.adapters["x-amb"].delivered], ["got it"])
        self.assertEqual(len(self.log(bridge)), 2)

    def test_it_shares_the_rate_limit_with_the_prefix(self):
        self.opened()
        with patch("partyline.bridge_delivery.WINDOW_LIMIT", 2):
            self.assertEqual(self.send(text="one").status_code, 200)
            self.say("x", "x-amb", "@[bridge]fable two")
            over = self.send(text="three")
            self.assertEqual(over.status_code, 429)
            self.assertIn("rate limit", over.json()["detail"])
            self.assertEqual(len(self.adapters["y-amb"].delivered), 2)
            self.say("x", "x-amb", "@[bridge]fable four")
            self.assertEqual(len(self.adapters["y-amb"].delivered), 2)
            self.assertEqual(self.send(text="five").status_code, 429)
        for conv in ("x", "y"):
            self.assertEqual(len([r for r in self.rows(conv)
                                  if r["body"] == bridge_delivery.PAUSED]), 1)

    def test_a_detached_peer_means_queued(self):
        self.opened()
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='y-amb'")
        sent = self.send()
        self.assertEqual(sent.json()["status"], "queued")
        self.assertIn("waiting for it", sent.json()["note"])
        self.assertEqual(len(self.db._exec(
            "SELECT 1 FROM messages WHERE conv_id='y' AND audience_attachment_id='y-amb'"
            " AND bridge_id IS NOT NULL").fetchall()), 1)

    def test_a_gone_peer_is_refused(self):
        self.opened()
        self.db._exec("DELETE FROM attachments WHERE id='y-amb'")
        gone = self.send()
        self.assertEqual(gone.status_code, 409)
        self.assertIn("is gone", gone.json()["detail"])

    def test_only_the_ambassador_on_its_own_line_may_send(self):
        self.opened()
        self.assertEqual(self.send(att="x-other").status_code, 409)
        self.assertEqual(self.send(headers=self.person).status_code, 403)
        self.assertEqual(self.send(conv="y", att="x-amb").status_code, 403)
        self.assertEqual(self.send(text="  ").status_code, 400)
        self.assertEqual(self.adapters["y-amb"].delivered, [])

    def test_after_the_bridge_closes_the_tool_is_gone_and_refused(self):
        bridge = self.opened()
        mark_closed(self.db, bridge["id"], "greg", "test")
        refused = self.send()
        self.assertEqual(refused.status_code, 409)
        self.assertIn("no open bridge", refused.json()["detail"])
        self.assertEqual(self.adapters["y-amb"].delivered, [])
        self.assertEqual(self.log(bridge), [])
        client = FakeClient()
        client.state.update(self.state("x-amb"), conv_id="home", dynamic_screen_tools=True)
        self.assertNotIn("bridge_send", {t["name"] for t in catalog.listed(client.state)})
        with self.assertRaisesRegex(ApiError, "no open bridge"):
            catalog.dispatch(client, "bridge_send", {"text": "hi", "client_key": "k"}, client.state)

    def test_a_retry_with_the_same_key_delivers_once(self):
        bridge = self.opened()
        first, again = self.send(key="k1"), self.send(key="k1")
        self.assertEqual(first.json()["status"], "delivered")
        self.assertTrue(again.json()["replayed"])
        self.assertEqual(len(self.adapters["y-amb"].delivered), 1)
        self.assertEqual(len(self.log(bridge)), 1)
        self.send(key="k2")
        self.assertEqual(len(self.adapters["y-amb"].delivered), 2)

    def test_the_prefix_still_works(self):
        bridge = self.opened()
        self.assertEqual(self.say("x", "x-amb", "@[bridge]fable by prefix").status_code, 200)
        self.assertEqual([m["body"] for m in self.adapters["y-amb"].delivered], ["@[bridge]fable by prefix"])
        self.assertEqual(len(self.log(bridge)), 1)

    def own_line_bodies(self, conv, body):
        return [r["body"] for r in self.rows(conv)
                if not r["bridge_id"] and r["sender_type"] == "agent" and r["body"] == body]

    def transcript_final(self, att, conv, body):
        """The turn's final text, as the transcript tail hands it to the room."""
        owner = self.db.get_attachment(att)["runtime_owner"]
        speak = Presence(self.runtime).posting(conv, att, self.runtime.post_callback(att, conv, owner))
        asyncio.run(speak("sonnet", "agent", body))

    def test_a_final_text_equal_to_a_bridge_send_still_reaches_its_own_line_once(self):
        self.opened()
        text = "The prototype is ready to review."
        self.assertEqual(self.send(text=text).json()["status"], "delivered")
        self.transcript_final("x-amb", "x", text)
        self.assertEqual(len(self.own_line_bodies("x", text)), 1)
        self.assertEqual(len(self.adapters["y-amb"].delivered), 1)

    def test_a_prefix_message_is_still_its_turns_echo_and_stays_hidden(self):
        self.opened()
        prefix = "@[bridge]fable the prototype is ready"
        self.assertEqual(self.say("x", "x-amb", prefix).status_code, 200)
        self.transcript_final("x-amb", "x", prefix)
        self.assertEqual(self.own_line_bodies("x", prefix), [])
        self.assertEqual(len(self.adapters["y-amb"].delivered), 1)

    def test_the_briefing_points_to_the_tool(self):
        self.opened()
        pack = [r["body"] for r in self.rows("x") if r["audience_attachment_id"] == "x-amb"][0]
        self.assertIn("`bridge_send`", pack)
        self.assertIn("normal final message", pack)
        self.assertIn("extras(op=", pack)


class BridgeSendToolTest(unittest.TestCase):
    def client(self, *, dynamic, bridge):
        client = FakeClient(actions=("read", "write"))
        client.state.update(dynamic_screen_tools=dynamic, bridge_open=bridge, screen_read=False,
                            screen_control=False, screen_windows=False)
        return client

    def names(self, client):
        return {tool["name"] for tool in catalog.listed(client.state)}

    def test_a_relisting_client_lists_it_only_while_a_bridge_is_open(self):
        self.assertIn("bridge_send", self.names(self.client(dynamic=True, bridge=True)))
        self.assertNotIn("bridge_send", self.names(self.client(dynamic=True, bridge=False)))

    def test_other_clients_reach_it_through_extras(self):
        client = self.client(dynamic=False, bridge=True)
        self.assertNotIn("bridge_send", self.names(client))
        extras = next(t for t in catalog.listed(client.state) if t["name"] == "extras")
        self.assertIn("bridge_send", extras["description"])
        catalog.dispatch(client, "extras", {"op": "bridge_send", "args": {
            "text": "hello", "client_key": "k1"}}, client.state)
        self.assertEqual(client.requests[-1], (
            "POST", "/api/conversations/home/bridge-send", {"text": "hello", "client_key": "k1"}))

    def test_a_call_is_validated(self):
        client = self.client(dynamic=True, bridge=True)
        for bad in ({"text": "x"}, {"text": "", "client_key": "k"},
                    {"text": "x", "client_key": "k", "to": "y"}):
            with self.assertRaises(ValueError):
                catalog.dispatch(client, "bridge_send", bad, client.state)
        catalog.dispatch(client, "bridge_send", {"text": "x", "client_key": "k"}, client.state)
        self.assertEqual(client.requests[-1][1], "/api/conversations/home/bridge-send")
        with self.assertRaisesRegex(ApiError, "no open bridge"):
            tools_bridge.call(client, "bridge_send", {}, {})

    def test_the_tool_list_changes_when_a_bridge_opens_or_closes(self):
        client = self.client(dynamic=True, bridge=False)
        output = io.StringIO()
        server = MCPServer(client, output)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        client.state["bridge_open"] = True
        server._refresh_signature()
        self.assertIn("notifications/tools/list_changed", output.getvalue())
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = json.loads(output.getvalue().splitlines()[-1])
        self.assertIn("bridge_send", {t["name"] for t in listed["result"]["tools"]})

    def test_a_bridge_row_change_bumps_the_capability_version(self):
        versions = CapabilityVersions()
        for statement in ("INSERT INTO line_bridges(id,a_conv_id) VALUES(?,?)",
                          "UPDATE line_bridges SET closed_at=?, closed_by=? WHERE id=?"):
            before = versions.current("att")
            versions.changed_by_sql(statement)
            self.assertNotEqual(versions.current("att"), before, statement)
        before = versions.current("att")
        versions.changed_by_sql("UPDATE line_bridges SET opened_by=? WHERE id=?")
        self.assertEqual(versions.current("att"), before)


if __name__ == "__main__":
    unittest.main()
