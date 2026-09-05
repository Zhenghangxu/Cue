import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.frontend import FrontendFiles


class FrontendRoutingTests(unittest.TestCase):
    def test_deep_links_and_static_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path, content in {
                "index.html": "English library",
                "zh/index.html": "Chinese library",
                "en/index.html": "English library",
                "settings/index.html": "Settings",
                "404.html": "Not found",
            }.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            app = FastAPI()
            app.mount("/", FrontendFiles(directory=root, html=True))
            client = TestClient(app)
            for path, content in {
                "/Movies/Season%201/": "English library",
                "/zh/Movies/": "Chinese library",
                "/en/Movies/": "English library",
                "/browse/settings/": "English library",
                "/settings/": "Settings",
            }.items():
                response = client.get(path, headers={"Accept": "text/html"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, content)
            for path in ["/api/missing", "/_next/missing.js"]:
                self.assertEqual(client.get(path, headers={"Accept": "text/html"}).status_code, 404)
            self.assertEqual(client.get("/missing.js").status_code, 404)
