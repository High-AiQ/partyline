"""Nodes CDP cannot drive are marked at read time and refuse with their own named cause."""
import json
import unittest
from unittest.mock import patch

from partyline.screen_element_actions import ElementAction, element_action
from partyline.screen_failure_snapshot import failed
from partyline_helper.cdp_identity import NotActionable, TargetChanged, prove
from types import SimpleNamespace

from tests import test_cdp_identity as identity


class ActionableTests(unittest.IsolatedAsyncioTestCase):
    exchange = identity.IdentityTests.exchange
    read = identity.IdentityTests.read
    invoke = identity.IdentityTests.invoke

    async def asyncSetUp(self):
        await identity.IdentityTests.asyncSetUp(self)
        socket = self.f.socket
        # <div><div>Dialog text <button>Save</button> [accessibility-only] [frame text]</div></div>
        socket.nodes += [
            dict(nodeId="5", parentId="1", backendDOMNodeId=5, role={"value": "generic"}),
            dict(nodeId="6", parentId="5", backendDOMNodeId=6, role={"value": "StaticText"},
                 name={"value": "Dialog text"}),
            dict(nodeId="7", parentId="5", backendDOMNodeId=7, role={"value": "button"},
                 name={"value": "Save"}),
            dict(nodeId="8", parentId="5", role={"value": "StaticText"}, name={"value": "Virtual"}),
            dict(nodeId="9", parentId="5", backendDOMNodeId=9, role={"value": "StaticText"},
                 name={"value": "Inside frame"}),
        ]
        socket.states.update({5: dict(tag="DIV"), 6: dict(non_element=3), 7: dict(tag="BUTTON", hit=True),
                              9: dict(tag="SPAN")})
        send = socket.send

        async def reject(raw):
            message = json.loads(raw)
            if message["method"] == "DOM.resolveNode" and message["params"]["backendNodeId"] == 9:
                socket.calls.append(message)
                socket.queue.put_nowait({"id": message["id"], "error": {
                    "code": -32000, "message": "No node with given id found"}})
                return
            await send(raw)
        patcher = patch.object(socket, "send", side_effect=reject)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def items(self):
        reply = await self.f.read()
        return {e["name"] or e["control_type"]: e for e in reply["elements"]}

    async def server_node(self, name):
        await self.elements.read(self.principal, window="g")
        tree = self.elements.snapshots["g"]
        return tree, next(n for n in tree.nodes.values() if n.name == name)

    async def test_read_marks_only_unactionable_nodes_and_names_the_ancestor(self):
        items = await self.items()
        wrapper = next(e for e in items.values() if e["dom"].get("tag") == "DIV")
        for name in ("Save", "Manage listing content"):
            self.assertNotIn("actionable", items[name])
            self.assertNotIn("act_on", items[name])
        self.assertNotIn("actionable", wrapper)
        text = items["Dialog text"]
        self.assertEqual((False, "text node", wrapper["id"]),
                         (text["actionable"], text["why"], text["act_on"]))
        virtual = items["Virtual"]
        self.assertEqual(("accessibility-only node", wrapper["id"]), (virtual["why"], virtual["act_on"]))
        frame = items["Inside frame"]
        self.assertEqual(False, frame["actionable"])
        self.assertIn("child frame", frame["why"])
        self.assertEqual(wrapper["id"], frame["act_on"])
        self.assertTrue(all("token" not in e or e["action_token"] for e in items.values()))

    async def test_no_ancestor_means_no_act_on_field(self):
        self.f.socket.states[1] = self.f.socket.states[5] = dict(non_element=3)
        text = (await self.items())["Dialog text"]
        self.assertEqual(False, text["actionable"])
        self.assertNotIn("act_on", text)

    async def test_text_node_refuses_with_its_own_reason_and_never_dispatches(self):
        await self.f.read()
        page = self.f.chrome.pages[self.f.access]["a"]
        text = next(i for i, n in page.nodes.items() if n.get("not_actionable") == "text node")
        result = await self.f.chrome.action(self.f.access, dict(action="invoke", element_id=text))
        self.assertEqual(("failed", "not_actionable"), (result["status"], result["reason"]))
        self.assertEqual(f"target has no DOM element (text node); act on its parent {result['act_on']}",
                         result["error"])
        self.assertNotIn("screen_window_click", result["error"])
        self.assertFalse(any(m["method"].startswith("Input.") for m in self.f.socket.calls))
        self.assertFalse(failed(result))  # a picture cannot explain it; no marks walk, no capture

    async def test_server_names_the_ancestor_by_the_id_the_read_listed(self):
        tree, node = await self.server_node("Dialog text")
        wrapper = tree.nodes[node.cached["act_on"]]
        self.assertEqual("Group", wrapper.type)
        self.assertIn(f"no-dom(text node;act_on={wrapper.id})", tree.line(node))
        self.assertNotIn("no-dom", tree.line(tree.nodes[wrapper.id]))
        result = await element_action(SimpleNamespace(db=None), self.outer, "line",
                                      ElementAction(element_id=node.id, action="invoke"), None)
        self.assertEqual(("failed", "not_actionable", wrapper.id),
                         (result["status"], result["reason"], result["act_on"]))
        self.assertEqual(f"target has no DOM element (text node); act on its parent {wrapper.id}",
                         result["error"])

    async def test_unreachable_frame_refusal_names_the_cause(self):
        await self.f.read()
        page = self.f.chrome.pages[self.f.access]["a"]
        frame = next(i for i, n in page.nodes.items() if "child frame" in n.get("not_actionable", ""))
        result = await self.f.chrome.action(self.f.access, dict(action="invoke", element_id=frame))
        self.assertEqual("not_actionable", result["reason"])
        self.assertIn("child frame not reachable from this page session", result["error"])

    async def test_element_targets_keep_the_identity_proof_and_target_changed(self):
        await self.read()
        self.f.socket.states[2]["document_identity"] = "other"
        result = await self.invoke()
        self.assertEqual("target_changed", result["reason"])
        page = self.f.chrome.pages[self.f.access]["a"]
        with self.assertRaises(TargetChanged):
            prove(page, {"action_identity": (page.epoch, None, ())}, {})
        self.assertNotIsInstance(NotActionable("text node"), TargetChanged)
