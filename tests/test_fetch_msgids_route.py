import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from datetime import datetime
from zoneinfo import ZoneInfo


def purge_modules():
    for name in (
        "config",
        "app",
        "core.database",
        "core.master_db",
        "routes",
        "routes.api_common",
    ):
        sys.modules.pop(name, None)
    for name in list(sys.modules):
        if name.startswith("routes."):
            sys.modules.pop(name, None)


class FetchMsgidsRouteTests(unittest.TestCase):
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

    def test_fetch_msgids_returns_count_and_msgid_rows(self):
        fake_article = {
            "msg_id": 2247487510,
            "title": "测试文章",
            "ref_date": "2026/03/29",
        }

        with patch("routes.api_common.load_setting", side_effect=lambda key, default="": {
            "wx_token": "token",
            "wx_cookies": "cookie=1",
            "wx_fingerprint": "fp",
        }.get(key, default)):
            with patch("routes.api_common.wx_get", return_value={
                "base_resp": {"ret": 0, "err_msg": ""},
                "article_list": [fake_article],
            }):
                resp = self.client.post("/fetch-msgids")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["fetched"], 1)
        self.assertEqual(len(data["msgids"]), 1)
        self.assertEqual(data["missing_titles"], [])
        self.assertEqual(data["msgids"][0]["msgid"], "2247487510")
        self.assertEqual(data["msgids"][0]["publish_date"], "2026-03-29")

    def test_fetch_msgids_surfaces_wechat_ret_code(self):
        with patch("routes.api_common.load_setting", side_effect=lambda key, default="": {
            "wx_token": "token",
            "wx_cookies": "cookie=1",
            "wx_fingerprint": "fp",
        }.get(key, default)):
            with patch("routes.api_common.wx_get", return_value={
                "base_resp": {"ret": -2, "err_msg": ""},
                "article_list": [],
            }):
                resp = self.client.post("/fetch-msgids")

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("ret=-2", data["error"])

    def test_fetch_msgids_paginates_past_fifty_articles(self):
        articles = [
            {"msg_id": 2247488000 + index, "title": f"文章{index}", "ref_date": "2026/10/01"}
            for index in range(51)
        ]
        credentials = {"wx_token": "token", "wx_cookies": "cookie=1", "wx_fingerprint": "fp"}
        with patch("routes.api_common.load_setting", side_effect=lambda key, default="": credentials.get(key, default)):
            with patch("routes.api_common.wx_get", side_effect=[
                {"base_resp": {"ret": 0}, "article_list": articles[:50]},
                {"base_resp": {"ret": 0}, "article_list": articles[50:]},
            ]) as wx_get:
                resp = self.client.post("/fetch-msgids")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["count"], 51)
        self.assertEqual(len(resp.get_json()["msgids"]), 51)
        queries = [parse_qs(urlparse(call.args[0]).query) for call in wx_get.call_args_list]
        self.assertEqual([query["offset"] for query in queries], [["0"], ["50"]])

    def test_fetch_msgids_reports_master_titles_missing_from_wechat_list(self):
        from core.master_db import sync_master_from_import

        sync_master_from_import(
            "tendency",
            {
                "daily_reads": [],
                "daily_stats": [],
                "article_sources": [
                    {
                        "title": "主档里有但微信没返回",
                        "publish_date": "2026-03-28",
                        "channel": "全部",
                        "read_user": 100,
                        "read_ratio": 1.0,
                    }
                ],
            },
            "tendency.xls",
        )

        fake_article = {
            "msg_id": 2247487510,
            "title": "微信返回文章",
            "ref_date": "2026/03/29",
        }

        with patch("routes.api_common.load_setting", side_effect=lambda key, default="": {
            "wx_token": "token",
            "wx_cookies": "cookie=1",
            "wx_fingerprint": "fp",
        }.get(key, default)):
            with patch("routes.api_common.wx_get", return_value={
                "base_resp": {"ret": 0, "err_msg": ""},
                "article_list": [fake_article],
            }):
                resp = self.client.post("/fetch-msgids")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["missing_titles"]), 1)
        self.assertEqual(data["missing_titles"][0]["title"], "主档里有但微信没返回")

    def test_selected_dates_include_both_days_and_do_not_refresh_older_records(self):
        from core.database import upsert_article_msgids
        from core.master_db import get_master_conn
        upsert_article_msgids([{"msgid": "old", "title": "历史文章", "publish_date": "2025-01-01"}])
        conn = get_master_conn()
        conn.execute("UPDATE article_msgids SET fetched_at='2025-01-02 00:00:00'")
        conn.commit()
        conn.close()
        articles = [
            {"msg_id": "old", "title": "历史文章", "ref_date": "20250101"},
            {"msg_id": "start", "title": "开始日", "ref_date": "20260901"},
            {"msg_id": "end", "title": "结束日", "ref_date": "2026/09/30"},
            {"msg_id": "after", "title": "范围外", "ref_date": "20261001"},
        ]
        selected = {"start_date": "2026-09-01", "end_date": "2026-09-30"}
        with patch("routes.api_common.load_setting", return_value="configured"):
            with patch("routes.api_common.wx_get", return_value={"base_resp": {"ret": 0}, "article_list": articles}) as wx_get:
                response = self.client.post("/fetch-msgids", json=selected)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["date_range"], selected)
        self.assertEqual(data["count"], 2)
        self.assertEqual({row["msgid"] for row in data["msgids"]}, {"start", "end"})
        query = parse_qs(urlparse(wx_get.call_args.args[0]).query)
        tz = ZoneInfo("Asia/Shanghai")
        self.assertEqual(datetime.fromtimestamp(int(query["begin_timestamp"][0]), tz).isoformat(), "2026-09-01T00:00:00+08:00")
        self.assertEqual(datetime.fromtimestamp(int(query["end_timestamp"][0]), tz).isoformat(), "2026-09-30T23:59:59+08:00")
        conn = get_master_conn()
        self.assertEqual(conn.execute("SELECT fetched_at FROM article_msgids WHERE msgid='old'").fetchone()[0], "2025-01-02 00:00:00")
        self.assertIsNone(conn.execute("SELECT id FROM article_msgids WHERE msgid='after'").fetchone())
        conn.close()

    def test_an_empty_selected_range_is_a_valid_result(self):
        selected = {"start_date": "2025-01-01", "end_date": "2025-01-31"}
        with patch("routes.api_common.load_setting", return_value="configured"):
            with patch("routes.api_common.wx_get", return_value={"base_resp": {"ret": 0}, "article_list": []}):
                response = self.client.post("/fetch-msgids", json=selected)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 0)
        self.assertEqual(response.get_json()["date_range"], selected)

    def test_invalid_ranges_fail_before_contacting_wechat(self):
        for body in [
            {"start_date": "2026-02-30", "end_date": "2026-03-01"},
            {"start_date": "2026-10-02", "end_date": "2026-10-01"},
            {"start_date": "2026-10-01"},
            {"start_date": "2026-1-1", "end_date": "2026-10-01"},
        ]:
            with self.subTest(body=body), patch("routes.api_common.load_setting", return_value="configured"), patch("routes.api_common.wx_get") as wx_get:
                self.assertEqual(self.client.post("/fetch-msgids", json=body).status_code, 400)
                wx_get.assert_not_called()

    def test_date_filtered_download_modes_distinguish_existing_snapshots(self):
        from core.database import upsert_article_msgids
        from core.master_db import sync_master_from_import, get_master_conn
        upsert_article_msgids([
            {"msgid": "old", "title": "范围外", "publish_date": "2026-08-31"},
            {"msgid": "saved", "title": "已有详情", "publish_date": "2026-09-01"},
            {"msgid": "new", "title": "没有详情", "publish_date": "2026-09-30"},
            {"msgid": "after", "title": "范围后", "publish_date": "2026-10-01"},
            {"msgid": "unknown", "title": "日期未知", "publish_date": None},
        ])
        sync_master_from_import("article_detail", {"detail": {"title": "已有详情", "read_user": 123}, "trend": []}, "detail.xls")
        conn = get_master_conn()
        conn.execute("UPDATE article_diagnostics SET detail_snapshot_at='2026-09-01 00:00:00'")
        conn.execute("UPDATE article_msgids SET fetched_at='2026-10-13 00:00:00'")
        conn.commit()
        conn.close()
        selected = {"start_date": "2026-09-01", "end_date": "2026-09-30"}
        with patch("routes.api_common.load_setting", return_value="configured"):
            missing = self.client.get("/api/pending-details", query_string={**selected, "download_mode": "missing"}).get_json()
            refresh = self.client.get("/api/pending-details", query_string={**selected, "download_mode": "refresh"}).get_json()
        self.assertEqual([row["msgid"] for row in missing["urls"]], ["new"])
        self.assertEqual({row["msgid"] for row in refresh["urls"]}, {"saved", "new"})
        self.assertEqual(missing["selection"], {**selected, "download_mode": "missing"})
        self.assertEqual(missing["urls"][0]["publish_date"], "2026-09-30")

    def test_pending_details_rejects_invalid_or_unbounded_new_modes(self):
        for query in [
            {"download_mode": "refresh"},
            {"start_date": "2026-09-01"},
            {"start_date": "2026-09-01", "end_date": "2026-09-30", "download_mode": "bad"},
        ]:
            with self.subTest(query=query), patch("routes.api_common.load_setting", return_value="configured"):
                self.assertEqual(self.client.get("/api/pending-details", query_string=query).status_code, 400)


if __name__ == "__main__":
    unittest.main()
