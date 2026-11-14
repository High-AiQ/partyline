import unittest

from fastapi.testclient import TestClient

from partyline.server import app


class AccessibilityLabRouteTest(unittest.TestCase):
    def test_route_serves_the_built_page_without_browser_api_credentials(self):
        response = TestClient(app).get("/lab/a11y")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn('<div id="root"></div>', response.text)
        self.assertIn("Accessibility lab", response.text)


if __name__ == "__main__":
    unittest.main()
