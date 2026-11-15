"""Deliver a window look as one image and a compact, complete numbered text list."""
import base64
import json
from urllib.parse import quote

from .client import MAX_DOWNLOAD
from .render import safe_links


def content(client, value):
    ident = value["file"]["id"]
    data = client._send("GET", f"/api/media/{quote(ident, safe='')}/original", None, {}, MAX_DOWNLOAD)
    # Keep the list complete even at the box cap; ordinary JSON rendering has a 20k character cap.
    meta = {key: value[key] for key in ("window", "snapshot", "generation", "coordinates", "width", "height",
                                      "image_tokens", "marks_note", "note", "changing") if key in value}
    text = json.dumps(safe_links(meta, client.connection["api"].rstrip("/")), ensure_ascii=False)
    text += "\n" + "\n".join(value["lines"])
    return [{"type": "text", "text": text},
            {"type": "image", "mimeType": value["image_mime"],
             "data": base64.b64encode(data).decode("ascii")}]
