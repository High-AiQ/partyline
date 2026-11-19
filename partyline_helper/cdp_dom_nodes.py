"""Supplement AX with bounded, pierced DOM candidates for standard interactive elements."""
from .cdp_file_nodes import MAX_NODES, attributes, file_nodes
from .cdp_control_details import may_need_details
from .cdp_recipes import WIDGET_ROLES, value

DETAIL = r"""function() {
 const e=this, r=e.getBoundingClientRect(), view=e.ownerDocument.defaultView;
 const hidden=!r.width||!r.height||['hidden','collapse'].includes(view.getComputedStyle(e).visibility);
 if(hidden)return {hidden:true};
 const parts=[], stack=[e];
 for(let i=0;stack.length&&i<32&&parts.join(' ').length<240;i++){
   const n=stack.pop();
   if(n.nodeType===3){parts.push((n.nodeValue||'').slice(0,240));continue;}
   if(n.nodeType!==1||['SCRIPT','STYLE','TEMPLATE'].includes(n.tagName)||n.hidden)continue;
   const s=view.getComputedStyle(n);
   if(s.display==='none'||['hidden','collapse'].includes(s.visibility))continue;
   const assigned=n.tagName==='SLOT'?n.assignedNodes():[];
   const children=assigned.length?assigned:(n.shadowRoot?n.shadowRoot.childNodes:n.childNodes);
   for(let j=Math.min(children.length,32)-1;j>=0;j--)stack.push(children[j]);
 }
 return {hidden:false, short_text:parts.join(' ').replace(/\s+/g,' ').trim().slice(0,240)};
}"""


def candidate(tag, attrs):
    try:
        if int(attrs.get("tabindex", "-1")) >= 0:
            return True
    except ValueError:
        pass
    return (any(key in attrs for key in ("aria-haspopup", "aria-expanded", "aria-controls", "aria-owns"))
            or attrs.get("role", "").split(" ")[0] in WIDGET_ROLES | {"gridcell"}
            or tag in ("BUTTON", "SELECT", "TEXTAREA", "SUMMARY", "IFRAME")
            or tag == "INPUT" and attrs.get("type", "").lower() != "hidden"
            or tag in ("A", "AREA") and "href" in attrs
            or tag in ("AUDIO", "VIDEO") and "controls" in attrs
            or attrs.get("contenteditable", "false").lower() in ("", "true", "plaintext-only"))


def interactive_nodes(root, nodes, controls=None):
    known = {n["backendDOMNodeId"]: n for n in nodes if n.get("backendDOMNodeId")}
    stack, result, visits = [(root, None)], [], 0
    while stack and visits < MAX_NODES:
        node, parent = stack.pop()
        visits += 1
        backend = node.get("backendNodeId")
        existing = known.get(backend)
        if existing and not existing.get("ignored"):
            parent = existing["nodeId"]
            if controls is not None and may_need_details(existing):
                attrs = attributes(node)
                if not attrs.get("role") and candidate(node.get("nodeName", "").upper(), attrs):
                    controls.add(backend)
        elif backend and candidate(node.get("nodeName", "").upper(), attrs := attributes(node)):
            role = attrs.get("role", "generic").split(" ")[0]
            item = {**(existing or {}), "nodeId": f"dom:{backend}", "parentId": parent,
                    "backendDOMNodeId": backend, "dom_discovered": True, "ignored": False}
            if not value(item.get("role")) or value(item.get("role")) in ("none", "generic"):
                item["role"] = {"value": role}
            result.append(item)
            parent = item["nodeId"]
        children = [*node.get("children", [])[:MAX_NODES], *node.get("shadowRoots", [])[:32]]
        if node.get("contentDocument"):
            children.append(node["contentDocument"])
        stack.extend((child, parent) for child in reversed(children[:max(0, MAX_NODES - len(stack))]))
    return result


async def discover(page, nodes, exposed=()):
    document = await page.call("DOM.getDocument", {"depth": -1, "pierce": True})
    root = document.get("root", {})
    known = {n.get("backendDOMNodeId") for n in nodes if not n.get("ignored")}
    files = [n for n in file_nodes(root) if n["backendDOMNodeId"] not in known]
    uploads = {n["backendDOMNodeId"] for n in files}
    controls = set()
    found = interactive_nodes(root, nodes, controls)
    for node in exposed:
        if node.get("backendDOMNodeId") in controls:
            node["dom_interactive"] = True
    return files + [n for n in found if n["backendDOMNodeId"] not in uploads]
