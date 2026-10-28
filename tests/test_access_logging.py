"""Uvicorn's configured output must not disclose request query strings."""

import contextlib
import io
import logging
import unittest

import uvicorn

from partyline.bind import uvicorn_config


class AccessLoggingTest(unittest.TestCase):
    def test_configured_loggers_strip_queries_and_preserve_other_messages(self):
        stderr, stdout = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                uvicorn_config(object(), "0.0.0.0", 8642, {})
                error = logging.getLogger("uvicorn.error")
                access = logging.getLogger("uvicorn.access")
                for fmt, extra in (
                    ('%s - "WebSocket %s" [accepted]', ()),
                    ('%s - "WebSocket %s" 403', ()),
                    ('%s - "WebSocket %s" %d', (401,)),
                ):
                    error.info(fmt, "client:42", "/ws/conv?token=jwt.secret&password=secret", *extra)
                error.info("unrelated %s", "message?unchanged")
                access.info('%s - "%s %s HTTP/%s" %d', "client:42", "GET",
                            "/api/items?api_key=secret", "1.1", 200)
                access.info('%s - "%s %s HTTP/%s" %d', "client:42", "GET",
                            "/health", "1.1", 200)
        finally:
            uvicorn.Config(object())  # Restore the default logging setup for other tests.
        error_output, access_output = stderr.getvalue(), stdout.getvalue()
        self.assertNotIn("secret", error_output + access_output)
        self.assertNotIn("jwt", error_output)
        self.assertEqual(error_output.count('"WebSocket /ws/conv"'), 3)
        self.assertIn("unrelated message?unchanged", error_output)
        self.assertIn('"GET /api/items HTTP/1.1" 200', access_output)
        self.assertIn('"GET /health HTTP/1.1" 200', access_output)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
