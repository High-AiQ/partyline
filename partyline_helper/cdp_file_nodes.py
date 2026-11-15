"""Bounded file-input discovery from one pierced DOM snapshot, independent of AX exposure."""

MAX_NODES = 10000
MAX_FILES = 100
MAX_NAME = 240


def attributes(node):
    pairs = node.get("attributes", [])[:256]
    return dict(zip(pairs[::2], pairs[1::2], strict=False))


def text(node):
    """Read a small serialized label/button subtree, never live container innerText."""
    stack, parts = [node], []
    for _ in range(32):
        if not stack or sum(map(len, parts)) >= MAX_NAME:
            break
        current = stack.pop()
        if current.get("nodeName") == "#text":
            parts.append(current.get("nodeValue", "")[:MAX_NAME])
        stack.extend(reversed(current.get("children", [])[:32]))
    return " ".join(" ".join(parts).split())[:MAX_NAME]


def file_nodes(root):
    stack = [(root, None, None, None)]
    labels, files = {}, []
    visits = 0
    while stack and visits < MAX_NODES:
        node, scope, label, button = stack.pop()
        visits += 1
        tag = node.get("nodeName", "").upper()
        if tag in ("#DOCUMENT", "#DOCUMENT-FRAGMENT"):
            scope, label, button = node.get("backendNodeId"), None, None
        attrs = attributes(node)
        if tag == "LABEL":
            label = node
            if attrs.get("for"):
                labels.setdefault((scope, attrs["for"]), node)
        if tag == "BUTTON" or attrs.get("role") == "button":
            button = node
        if tag == "INPUT" and attrs.get("type", "").lower() == "file" and len(files) < MAX_FILES:
            files.append((node, attrs, scope, label, button))
        children = node.get("children", [])[:MAX_NODES - visits]
        children = [*children, *node.get("shadowRoots", [])[:32]]
        if node.get("contentDocument"):
            children.append(node["contentDocument"])
        remaining = max(0, MAX_NODES - len(stack))
        stack.extend((child, scope, label, button) for child in reversed(children[:remaining]))
    result = []
    for node, attrs, scope, label, button in files:
        label = labels.get((scope, attrs.get("id")), label)
        name = (attrs.get("aria-label") or (text(label) if label else "") or attrs.get("accept")
                or (text(button) if button else "") or attrs.get("id") or attrs.get("name") or "File upload")
        backend = node["backendNodeId"]
        result.append({"nodeId": f"file:{backend}", "backendDOMNodeId": backend,
                       "role": {"value": "fileInput"}, "name": {"value": name[:MAX_NAME]},
                       "file_input_discovered": True})
    return result
