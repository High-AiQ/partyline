import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from partyline.static_cache import IMMUTABLE_ASSET_CACHE, install_static_cache


class StaticCacheTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        assets = Path(self.directory.name)
        (assets / "index-hash.js").write_text("export {};", encoding="utf-8")
        app = FastAPI()
        install_static_cache(app)

        @app.get("/")
        async def index():
            return PlainTextResponse("document")

        app.mount("/assets", StaticFiles(directory=assets), name="assets")
        self.client = TestClient(app)
        self.addCleanup(self.directory.cleanup)

    def test_successful_assets_are_cached_immutably(self):
        response = self.client.get("/assets/index-hash.js")
        self.assertEqual(response.headers["cache-control"], IMMUTABLE_ASSET_CACHE)

    def test_document_and_missing_assets_are_not_cached_immutably(self):
        self.assertNotIn("cache-control", self.client.get("/").headers)
        self.assertNotIn("cache-control", self.client.get("/assets/missing.js").headers)


if __name__ == "__main__":
    unittest.main()
