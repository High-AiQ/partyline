"""Browser fixtures that need a real idle PTY, without a nested write fence.

These fixtures run known idle commands against throwaway databases. They test
chat and process controls; backend fence tests own sandbox enforcement.
"""

import os
from unittest.mock import patch

from scripts.uishot import ui_session


def process_ui_session(*args, **kwargs):
    """Bootstrap test doubles inside the throwaway server subprocess only."""
    return ui_session(*args, server_module="scripts.ui_process", **kwargs)


def attach_idle_process(ui, conversation_id):
    """Keep a real raw PTY alive so human sends meet the live-process rule."""
    response = ui.page.request.post(
        f"{ui.base_url}/api/conversations/{conversation_id}/attachments",
        data={"name": "worker", "adapter": "raw", "command": "/bin/sleep 60", "cwd": "/tmp"},
        headers=ui.auth_headers,
    )
    if not response.ok:
        raise AssertionError(response.text())
    return response.json()


if __name__ == "__main__":
    # UI protocols do not test host namespaces or the server's service unit.
    # Keep real PTYs and process memory scopes, with no production changes.
    with patch.dict(os.environ, {"PARTYLINE_FEATURE_WRITE_FENCE": "0"}), \
            patch("partyline.fence_probe.probe", return_value=(True, "", "")):
        from partyline.server import main

        main()
