"""Tools can authenticate with an empty environment without exposing the token."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from partyline.agent_client import NoRedirect, api_request, load_connection, main
from partyline.agent_connection import (
    provision_connection, remove_connection, connection_hint, bind_connection_hint,
)


class AgentConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / "test.db")
        self.att = {"id": "agent-one", "conv_id": "line-one", "name": "lead",
                    "api_token": "private-test-token", "hook_url": "http://0.0.0.0:8643/api/hooks/a"}
        provision_connection(self.db, self.att)
        self.path = Path(self.db + ".agent-connections/agent-one.json")

    def test_private_atomic_file_and_safe_command(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(self.att["api_token"], self.att["agent_command"])
        with patch.dict(os.environ, {}, clear=True):
            data = load_connection(str(self.path))
        self.assertEqual(data["api"], "http://127.0.0.1:8643")
        self.assertEqual(data["token"], self.att["api_token"])
        provision_connection(self.db, self.att)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()),
                         ["agent-one.json", "agent-one.mcp.json"])
        remove_connection(self.db, self.att["id"])
        remove_connection(self.db, self.att["id"])
        self.assertFalse(self.path.exists())

    def test_context_does_not_print_credential(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--connection", str(self.path), "context"]), 0)
        self.assertNotIn(self.att["api_token"], output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["attachment_id"], "agent-one")

    def test_reject_unsafe_files_and_missing_tokens(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            load_connection(str(self.path))
        self.path.chmod(0o600)
        link = self.path.with_name("symlink.json")
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            load_connection(str(link))
        with self.assertRaises(ValueError):
            provision_connection(self.db, dict(self.att, api_token=""))
        self.path.parent.chmod(0o755)
        with self.assertRaises(ValueError):
            provision_connection(self.db, self.att)

    def test_reject_traversal_and_external_requests(self):
        with self.assertRaises(ValueError):
            provision_connection(self.db, dict(self.att, id="../outside"))
        with self.assertRaises(ValueError):
            remove_connection(self.db, "../outside")
        connection = load_connection(str(self.path))
        for path in ("https://elsewhere/api/tasks", "//elsewhere/api/tasks", "/api/tasks#x", "/other"):
            with self.assertRaises(ValueError):
                api_request(connection, "GET", path)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "http://elsewhere"))

    def test_json_request_and_sanitized_failure(self):
        body = self.path.with_name("body.json")
        body.write_text('{"body":"hello"}')
        output = io.StringIO()
        reply = (b'{"ok":true}', "application/json")
        with patch("partyline.agent_client.api_request", return_value=reply) as call:
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--connection", str(self.path), "request", "POST",
                                       "/api/tasks", "--json-file", str(body)]), 0)
            self.assertEqual(json.loads(call.call_args.args[3]), {"body": "hello"})
        error = io.StringIO()
        refused = HTTPError("", 403, "secret", {},
                            io.BytesIO(b'{"detail":"this credential cannot act on that line"}'))
        with patch("partyline.agent_client.api_request", side_effect=refused):
            with contextlib.redirect_stderr(error):
                self.assertEqual(main(["--connection", str(self.path), "request", "GET", "/api/tasks"]), 1)
        self.assertEqual(error.getvalue(),
                         "Partyline request failed: HTTP 403: this credential cannot act on that line\n")

    def test_request_uses_header(self):
        connection = load_connection(str(self.path))
        with patch("partyline.agent_client.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b"{}"
            response.headers.get.return_value = None
            self.assertEqual(api_request(connection, "GET", "/api/tasks"), (b"{}", ""))
            response.headers.get.return_value = "image/png"
            response.headers.get_content_type.return_value = "image/png"
            self.assertEqual(api_request(connection, "GET", "/api/tasks"), (b"{}", "image/png"))
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer private-test-token")
            self.assertNotIn("private-test-token", request.full_url)

    def test_bad_connection_and_binary_download(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(["--connection", str(self.path) + ".missing", "context"]), 1)
        self.assertNotIn(self.att["api_token"], error.getvalue())
        output = self.path.with_name("image.png")
        with patch("partyline.agent_client.api_request", return_value=(b"\x89PNG", "image/png")):
            self.assertEqual(main(["--connection", str(self.path), "request", "GET",
                                   "/api/media/image/original", "--output", str(output)]), 0)
        self.assertEqual(output.read_bytes(), b"\x89PNG")
        for replacement in ({"token": ""}, {"api": "file:///tmp/x"},
                            {"api": "http://example.test/path"}):
            data = dict(load_connection(str(self.path)), **replacement)
            self.path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_connection(str(self.path))
            provision_connection(self.db, self.att)

    def test_binary_without_output_is_saved_under_a_media_name(self):
        saved = os.getcwd()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        os.chdir(directory.name)
        self.addCleanup(os.chdir, saved)
        out = io.StringIO()
        with patch("partyline.agent_client.api_request", return_value=(b"\x89PNG", "image/png")):
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["--connection", str(self.path), "request", "GET",
                                       "/api/media/abc123/thumb"]), 0)
        self.assertEqual(out.getvalue().strip(), "media-abc123-thumb.png")
        self.assertEqual(Path("media-abc123-thumb.png").read_bytes(), b"\x89PNG")
        out = io.StringIO()
        with patch("partyline.agent_client.api_request", return_value=(b"\xff\xfe", "")):
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["--connection", str(self.path), "request", "GET",
                                       "/api/other/file?x=1"]), 0)
        self.assertEqual(out.getvalue().strip(), "other-file.bin")
        with patch("partyline.agent_client.api_request", return_value=(b"x", "application/pdf")):
            with contextlib.redirect_stdout(io.StringIO()):
                main(["--connection", str(self.path), "request", "GET", "/api/"])
        self.assertTrue(Path("response.pdf").exists())

    def test_text_responses_still_print(self):
        for kind in ("text/plain", "application/json", ""):
            out = io.StringIO()
            with patch("partyline.agent_client.api_request", return_value=(b"hi", kind)):
                with contextlib.redirect_stdout(out):
                    main(["--connection", str(self.path), "request", "GET", "/api/x"])
            self.assertEqual(out.getvalue(), "hi\n")

    def test_resume_hint_and_failed_publish_cleanup(self):
        self.assertIn(self.att["agent_command"], connection_hint(self.att))
        self.assertNotIn(self.att["api_token"], connection_hint(self.att))
        with patch("partyline.agent_connection.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                provision_connection(self.db, self.att)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()),
                         ["agent-one.json", "agent-one.mcp.json"])

    def test_stdin_and_invalid_json_shape(self):
        with patch("sys.stdin", io.StringIO('{"body":"from stdin"}')):
            reply = (b"{}", "application/json")
            with patch("partyline.agent_client.api_request", return_value=reply) as call:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--connection", str(self.path), "request", "POST",
                                           "/api/tasks", "--json-file", "-"]), 0)
                self.assertEqual(json.loads(call.call_args.args[3]), {"body": "from stdin"})
        self.path.write_text("[]")
        with self.assertRaises(ValueError):
            load_connection(str(self.path))


class ConnectionHintDeliveryTests(unittest.TestCase):
    def test_resume_helper_appears_only_on_first_digest(self):
        att = {"agent_command": "safe-helper", "digest_rider": lambda: "current tasks"}
        bind_connection_hint(att)
        self.assertIn("safe-helper", att["digest_rider"]())
        self.assertEqual(att["digest_rider"](), "current tasks")
