import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


def purge_modules():
    for name in ("config", "core.database", "core.master_db"):
        sys.modules.pop(name, None)


class DetailDownloadStateTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.analytics_db = Path(self.tmpdir.name) / "analytics.db"
        self.master_db = Path(self.tmpdir.name) / "master.db"
        os.environ["DB_PATH"] = str(self.analytics_db)
        os.environ["MASTER_DB_PATH"] = str(self.master_db)
        purge_modules()

        importlib.import_module("config")
        self.db = importlib.import_module("core.database")
        self.master = importlib.import_module("core.master_db")
        self.db.init_db()
        self.master.init_master_db()

    def tearDown(self):
        purge_modules()
        os.environ.pop("DB_PATH", None)
        os.environ.pop("MASTER_DB_PATH", None)
        self.tmpdir.cleanup()

    def test_pending_requires_real_detail_snapshot(self):
        self.db.upsert_article_msgids(
            [{"msgid": "10001", "title": "测试文章", "publish_date": "2026-04-01"}]
        )
        self.db.mark_detail_downloaded("10001")

        pending = self.db.query_article_msgids(only_pending=True)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["msgid"], "10001")

        rows = self.db.query_article_msgids()
        self.assertEqual(rows[0]["has_detail_snapshot"], 0)
        self.assertEqual(rows[0]["detail_ready"], 0)

    def test_fresh_detail_snapshot_removes_article_from_pending(self):
        self.db.upsert_article_msgids(
            [{"msgid": "10001", "title": "测试文章", "publish_date": "2026-04-01"}]
        )
        self.master.sync_master_from_import(
            "article_detail",
            {"detail": {"title": "测试文章", "read_user": 123}, "trend": []},
            "detail.xls",
        )

        pending = self.db.query_article_msgids(only_pending=True)

        self.assertEqual(pending, [])

    def test_refetching_article_list_makes_old_snapshot_pending_again(self):
        self.db.upsert_article_msgids(
            [{"msgid": "10001", "title": "测试文章", "publish_date": "2026-04-01"}]
        )
        self.master.sync_master_from_import(
            "article_detail",
            {"detail": {"title": "测试文章", "read_user": 123}, "trend": []},
            "detail.xls",
        )

        conn = self.master.get_master_conn()
        conn.execute(
            """UPDATE article_msgids
               SET fetched_at=(
                   SELECT datetime(d.latest_snapshot_at, '+1 minute')
                   FROM article_master m
                   JOIN article_diagnostics d ON d.article_id = m.id
                   WHERE m.normalized_title = article_msgids.normalized_title
                   LIMIT 1
               )
               WHERE msgid='10001'"""
        )
        conn.commit()
        conn.close()

        pending = self.db.query_article_msgids(only_pending=True)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["msgid"], "10001")

    def test_upsert_article_msgids_refreshes_fetched_at_on_conflict(self):
        self.db.upsert_article_msgids(
            [{"msgid": "10001", "title": "测试文章", "publish_date": "2026-04-01"}]
        )

        conn = self.master.get_master_conn()
        first = conn.execute(
            "SELECT fetched_at FROM article_msgids WHERE msgid='10001'"
        ).fetchone()["fetched_at"]
        conn.execute(
            "UPDATE article_msgids SET fetched_at='2000-01-01 00:00:00' WHERE msgid='10001'"
        )
        conn.commit()
        conn.close()

        self.db.upsert_article_msgids(
            [{"msgid": "10001", "title": "测试文章", "publish_date": "2026-04-01"}]
        )

        conn = self.master.get_master_conn()
        updated = conn.execute(
            "SELECT fetched_at FROM article_msgids WHERE msgid='10001'"
        ).fetchone()["fetched_at"]
        conn.close()

        self.assertNotEqual(updated, "2000-01-01 00:00:00")
        self.assertEqual(updated, first)

    def test_source_only_article_keeps_detail_metrics_empty_in_master_view(self):
        self.master.sync_master_from_import(
            "tendency",
            {
                "daily_reads": [],
                "daily_stats": [],
                "article_sources": [
                    {
                        "title": "只有趋势没有详情",
                        "publish_date": "2026-04-01",
                        "channel": "全部",
                        "read_user": 591,
                        "read_ratio": 1.0,
                    },
                    {
                        "title": "只有趋势没有详情",
                        "publish_date": "2026-04-01",
                        "channel": "推荐",
                        "read_user": 13,
                        "read_ratio": 0.022,
                    },
                ],
            },
            "tendency.xls",
        )

        article = self.master.query_master_articles(limit=1)[0]
        self.assertEqual(article["total_reads"], 591)
        self.assertEqual(article["rec_pct"], 2.2)
        self.assertIsNone(article["share_user"])
        self.assertIsNone(article["thumbup_user"])
        self.assertIsNone(article["like_user"])
        self.assertIsNone(article["fav_user"])
        self.assertIsNone(article["avg_read_time"])
        self.assertIsNone(article["complete_rate_pct"])


if __name__ == "__main__":
    unittest.main()
