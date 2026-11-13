import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


def purge_modules():
    for name in ("config", "app", "core.database", "core.master_db", "routes", "routes.settings"):
        sys.modules.pop(name, None)
    for name in list(sys.modules):
        if name.startswith("routes."):
            sys.modules.pop(name, None)


class SettingsPageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.analytics_db = Path(self.tmpdir.name) / "analytics.db"
        self.master_db = Path(self.tmpdir.name) / "master.db"
        os.environ["DB_PATH"] = str(self.analytics_db)
        os.environ["MASTER_DB_PATH"] = str(self.master_db)
        purge_modules()

        self.app_mod = importlib.import_module("app")
        self.client = self.app_mod.app.test_client()

    def tearDown(self):
        purge_modules()
        os.environ.pop("DB_PATH", None)
        os.environ.pop("MASTER_DB_PATH", None)
        self.tmpdir.cleanup()

    def test_settings_post_renders_single_success_alert(self):
        html = self.client.post(
            "/settings",
            data={"token": "a", "fingerprint": "b", "cookies": "c"},
            follow_redirects=True,
        ).get_data(as_text=True)

        self.assertEqual(html.count("alert alert-success"), 1)
        self.assertIn("✅ 凭证已保存", html)
        self.assertNotIn("{&#39;text&#39;:", html)

    def test_settings_page_uses_request_error_normalizer(self):
        html = self.client.get("/settings").get_data(as_text=True)

        self.assertIn("function formatRequestError(err)", html)
        self.assertNotIn("请求失败: ' + err.message", html)


if __name__ == "__main__":
    unittest.main()
