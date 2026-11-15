"""Keep only exposed AX nodes, reconnecting children across ignored intermediate nodes."""


def exposed(nodes):
    by_id = {node["nodeId"]: node for node in nodes}
    result = []
    for node in nodes:
        if node.get("ignored"):
            continue
        parent, seen = node.get("parentId"), {node["nodeId"]}
        while parent in by_id and by_id[parent].get("ignored"):
            if parent in seen:
                parent = None
                break
            seen.add(parent)
            parent = by_id[parent].get("parentId")
        result.append({**node, "parentId": parent})
    return result
