import importlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
import json
from datetime import datetime, timedelta


def purge_modules():
    for name in ("config", "core.database", "core.master_db"):
        sys.modules.pop(name, None)


def purge_app_modules():
    purge_modules()
    sys.modules.pop("app", None)
    sys.modules.pop("routes", None)
    for name in list(sys.modules):
        if name.startswith("routes."):
            sys.modules.pop(name, None)


class MasterDbTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.analytics_db = Path(self.tmpdir.name) / "analytics.db"
        self.master_db = Path(self.tmpdir.name) / "master.db"
        os.environ["DB_PATH"] = str(self.analytics_db)
        os.environ["MASTER_DB_PATH"] = str(self.master_db)
        purge_modules()

        self.config = importlib.import_module("config")
        self.legacy_db = importlib.import_module("core.database")
        self.legacy_db.init_db()
        self.master_db_mod = importlib.import_module("core.master_db")
        self.master_db_mod.init_master_db()

    def tearDown(self):
        purge_modules()
        os.environ.pop("DB_PATH", None)
        os.environ.pop("MASTER_DB_PATH", None)
        self.tmpdir.cleanup()

    def test_init_master_db_creates_v1_tables(self):
        conn = sqlite3.connect(str(self.master_db))
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        tables = {name for (name,) in rows}
        expected = {
            "article_master",
            "article_diagnostics",
            "account_daily_metrics",
            "traffic_source_stats",
            "account_user_daily",
            "account_menu_stats",
            "account_message_stats",
            "import_history",
            "settings",
            "article_msgids",
            "article_trend",
            "article_tags",
            "planned_articles",
            "anomaly_log",
            "article_predictions",
            "competitor_accounts",
            "competitor_articles",
            "article_overrides",
            "sync_runs",
            "pending_records",
        }
        self.assertTrue(expected.issubset(tables))

    def test_init_master_db_normalizes_existing_slash_publish_dates(self):
        conn = sqlite3.connect(str(self.master_db))
        conn.execute(
            """INSERT INTO article_master (canonical_title, normalized_title, publish_date)
               VALUES (?, ?, ?)""",
            ("斜杠日期文章", "斜杠日期文章", "2026/03/29"),
        )
        conn.execute(
            """INSERT INTO traffic_source_stats
               (article_id, publish_date, title, normalized_title, channel, read_user)
               VALUES (1, ?, ?, ?, '全部', 123)""",
            ("2026/03/29", "斜杠日期文章", "斜杠日期文章"),
        )
        conn.execute(
            """INSERT INTO article_msgids (msgid, title, normalized_title, publish_date)
               VALUES (?, ?, ?, ?)""",
            ("msg-1", "斜杠日期文章", "斜杠日期文章", "2026/03/29"),
        )
        conn.commit()
        conn.close()

        self.master_db_mod.init_master_db()

        conn = sqlite3.connect(str(self.master_db))
        article_date = conn.execute("SELECT publish_date FROM article_master WHERE id=1").fetchone()[0]
        source_date = conn.execute("SELECT publish_date FROM traffic_source_stats WHERE article_id=1").fetchone()[0]
        msgid_date = conn.execute("SELECT publish_date FROM article_msgids WHERE msgid='msg-1'").fetchone()[0]
        conn.close()

        self.assertEqual(article_date, "2026-03-29")
        self.assertEqual(source_date, "2026-03-29")
        self.assertEqual(msgid_date, "2026-03-29")

    def test_sync_master_from_import_merges_article_and_account_metrics(self):
        tendency_data = {
            "date_range": "2026.03.01-2026.03.02",
            "daily_reads": [
                {"stat_date": "2026-03-01", "channel": "全部", "read_user": 800},
                {"stat_date": "2026-03-01", "channel": "推荐", "read_user": 300},
            ],
            "daily_stats": [
                {
                    "stat_date": "2026-03-01",
                    "share_user": 20,
                    "original_read_user": 5,
                    "fav_user": 10,
                    "article_count": 1,
                }
            ],
            "article_sources": [
                {
                    "channel": "全部",
                    "publish_date": "2026-03-01",
                    "title": "示例文章",
                    "read_user": 800,
                    "read_ratio": 1.0,
                },
                {
                    "channel": "推荐",
                    "publish_date": "2026-03-01",
                    "title": "示例文章",
                    "read_user": 300,
                    "read_ratio": 0.375,
                },
            ],
        }
        detail_data = {
            "detail": {
                "title": "示例文章",
                "read_user": 1200,
                "avg_read_time": 32,
                "complete_rate": 0.61,
                "follow_after_read": 18,
                "share_user": 35,
                "like_user": 16,
                "thumbup_user": 9,
                "fav_user": 27,
                "comment_count": 6,
                "deliver_user": 1000,
                "msg_read_user": 600,
                "first_share_user": 22,
                "total_share_user": 41,
                "share_read_user": 55,
            },
            "trend": [],
        }
        user_data = {
            "date_range": "2026-03-01~2026-03-02",
            "records": [
                {
                    "stat_date": "2026-03-01",
                    "new_user": 12,
                    "cancel_user": 3,
                    "net_user": 9,
                    "total_user": 1200,
                }
            ],
        }
        menu_data = {
            "date_range": "2026-03-01~2026-03-02",
            "records": [
                {
                    "menu_version": "2026030101",
                    "menu_level1": "资料",
                    "menu_level2": "题库",
                    "click_count": 88,
                    "click_user": 56,
                    "avg_click": 1.57,
                }
            ],
        }
        msg_data = {
            "date_range": "2026-03-01~2026-03-02",
            "records": [
                {
                    "stat_date": "2026-03-01",
                    "msg_user": 7,
                    "msg_count": 21,
                    "avg_msg": 3.0,
                }
            ],
        }

        self.master_db_mod.sync_master_from_import("tendency", tendency_data, "tendency.xls")
        self.master_db_mod.sync_master_from_import("article_detail", detail_data, "detail.xls")
        self.master_db_mod.sync_master_from_import("user", user_data, "user.xls")
        self.master_db_mod.sync_master_from_import("menu", menu_data, "menu.xls")
        self.master_db_mod.sync_master_from_import("msg", msg_data, "msg.xls")

        conn = sqlite3.connect(str(self.master_db))
        conn.row_factory = sqlite3.Row

        article = conn.execute(
            "SELECT * FROM article_master WHERE canonical_title='示例文章'"
        ).fetchone()
        diagnostics = conn.execute(
            """SELECT d.* FROM article_diagnostics d
               JOIN article_master m ON m.id = d.article_id
               WHERE m.canonical_title='示例文章'"""
        ).fetchone()
        daily = conn.execute(
            "SELECT * FROM account_daily_metrics WHERE stat_date='2026-03-01'"
        ).fetchone()
        user_row = conn.execute(
            "SELECT * FROM account_user_daily WHERE stat_date='2026-03-01'"
        ).fetchone()
        menu_row = conn.execute(
            "SELECT * FROM account_menu_stats WHERE menu_version='2026030101'"
        ).fetchone()
        msg_row = conn.execute(
            "SELECT * FROM account_message_stats WHERE stat_date='2026-03-01'"
        ).fetchone()
        conn.close()

        self.assertIsNotNone(article)
        self.assertEqual(article["publish_date"], "2026-03-01")
        self.assertEqual(article["total_reads"], 1200)
        self.assertEqual(article["share_user"], 35)
        self.assertEqual(article["comment_count"], 6)
        self.assertEqual(article["source_count"], 2)

        self.assertIsNotNone(diagnostics)
        self.assertEqual(diagnostics["avg_read_time"], 32)
        self.assertAlmostEqual(diagnostics["complete_rate"], 0.61)
        self.assertEqual(diagnostics["rec_reads"], 300)
        self.assertAlmostEqual(diagnostics["rec_ratio"], 0.25)
        self.assertAlmostEqual(diagnostics["open_rate"], 0.6)

        self.assertIsNotNone(daily)
        self.assertEqual(daily["total_read_user"], 800)
        self.assertEqual(daily["article_count"], 1)
        self.assertEqual(user_row["total_user"], 1200)
        self.assertEqual(menu_row["click_count"], 88)
        self.assertEqual(msg_row["msg_count"], 21)

    def test_bootstrap_master_from_analytics_imports_existing_records(self):
        conn = sqlite3.connect(str(self.analytics_db))
        conn.execute(
            """INSERT INTO article_source_stats
               (publish_date, title, channel, read_user, read_ratio, import_file)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("2026-03-02", "旧库文章", "全部", 900, 1.0, "old_tendency.xls"),
        )
        conn.execute(
            """INSERT INTO article_source_stats
               (publish_date, title, channel, read_user, read_ratio, import_file)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("2026-03-02", "旧库文章", "推荐", 360, 0.4, "old_tendency.xls"),
        )
        conn.execute(
            """INSERT INTO article_detail
               (title, read_user, avg_read_time, complete_rate, share_user, like_user,
                thumbup_user, fav_user, comment_count, deliver_user, msg_read_user, import_file)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("旧库文章", 950, 45, 0.71, 44, 12, 8, 30, 5, 1100, 770, "old_detail.xls"),
        )
        conn.execute(
            """INSERT INTO daily_reads (stat_date, channel, read_user)
               VALUES (?, ?, ?)""",
            ("2026-03-02", "全部", 1400),
        )
        conn.execute(
            """INSERT INTO daily_stats
               (stat_date, share_user, original_read_user, fav_user, article_count)
               VALUES (?, ?, ?, ?, ?)""",
            ("2026-03-02", 33, 8, 12, 1),
        )
        conn.execute(
            """INSERT INTO daily_user_stats
               (stat_date, new_user, cancel_user, net_user, total_user)
               VALUES (?, ?, ?, ?, ?)""",
            ("2026-03-02", 13, 4, 9, 1400),
        )
        conn.execute(
            """INSERT INTO daily_msg_stats
               (stat_date, msg_user, msg_count, avg_msg)
               VALUES (?, ?, ?, ?)""",
            ("2026-03-02", 9, 18, 2.0),
        )
        conn.execute(
            """INSERT INTO menu_stats
               (menu_version, menu_level1, menu_level2, click_count, click_user, avg_click, import_date)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("2026030201", "帮助", "客服", 50, 40, 1.25, "2026-03-02"),
        )
        conn.commit()
        conn.close()

        stats = self.master_db_mod.bootstrap_master_from_analytics()

        self.assertGreaterEqual(stats["articles"], 1)
        self.assertGreaterEqual(stats["daily_metrics"], 1)

        conn = sqlite3.connect(str(self.master_db))
        conn.row_factory = sqlite3.Row
        article = conn.execute(
            "SELECT * FROM article_master WHERE canonical_title='旧库文章'"
        ).fetchone()
        diagnostics = conn.execute(
            """SELECT d.* FROM article_diagnostics d
               JOIN article_master m ON m.id = d.article_id
               WHERE m.canonical_title='旧库文章'"""
        ).fetchone()
        daily = conn.execute(
            "SELECT * FROM account_daily_metrics WHERE stat_date='2026-03-02'"
        ).fetchone()
        user_row = conn.execute(
            "SELECT * FROM account_user_daily WHERE stat_date='2026-03-02'"
        ).fetchone()
        msg_row = conn.execute(
            "SELECT * FROM account_message_stats WHERE stat_date='2026-03-02'"
        ).fetchone()
        menu_row = conn.execute(
            "SELECT * FROM account_menu_stats WHERE menu_version='2026030201'"
        ).fetchone()
        conn.close()

        self.assertEqual(article["total_reads"], 950)
        self.assertEqual(diagnostics["rec_reads"], 360)
        self.assertEqual(daily["total_read_user"], 1400)
        self.assertEqual(user_row["total_user"], 1400)
        self.assertEqual(msg_row["msg_count"], 18)
        self.assertEqual(menu_row["click_user"], 40)

    def test_master_page_route_renders(self):
        sys.modules.pop("app", None)
        sys.modules.pop("routes.master", None)
        sys.modules.pop("routes", None)
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        response = client.get("/master")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("标准主档", body)

    def test_sidebar_no_longer_shows_articles_entry(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        body = client.get("/master").get_data(as_text=True)

        self.assertNotIn('href="/articles">文章排行</a>', body)
        self.assertNotIn('href="/baseline">账号基准</a>', body)
        self.assertNotIn('href="/summary">月度汇总</a>', body)
        self.assertNotIn('href="/users">用户分析</a>', body)
        self.assertNotIn('href="/data">数据管理</a>', body)

    def test_settings_page_prunes_schedule_bark_email_anomaly_and_ai_sections(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        body = client.get("/settings").get_data(as_text=True)

        self.assertNotIn("定时配置", body)
        self.assertNotIn("Bark 推送", body)
        self.assertNotIn("邮件通知", body)
        self.assertNotIn("异常检测", body)
        self.assertNotIn("AI 报告", body)
        self.assertNotIn("/api/get-schedule", body)
        self.assertNotIn("/api/set-schedule", body)
        self.assertNotIn("/api/get-bark-key", body)
        self.assertNotIn("/api/save-bark-key", body)
        self.assertNotIn("/api/test-bark", body)
        self.assertNotIn("/api/get-email", body)
        self.assertNotIn("/api/save-email", body)
        self.assertNotIn("/api/test-email", body)
        self.assertNotIn("/api/anomaly-threshold", body)
        self.assertNotIn("/api/set-api-key", body)

    def test_baseline_route_redirects_to_competitor(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        response = client.get("/baseline", follow_redirects=False)

        self.assertIn(response.status_code, (301, 302, 303, 307, 308))
        self.assertEqual(response.headers["Location"], "/competitor")

    def test_insights_page_prunes_lifecycle_and_follower_sections(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        body = client.get("/insights").get_data(as_text=True)

        self.assertNotIn("文章生命周期", body)
        self.assertNotIn("涨粉归因", body)
        self.assertNotIn("/api/lifecycle", body)
        self.assertNotIn("/api/follower-attribution", body)

    def test_legacy_article_detail_upsert_accepts_missing_optional_fields(self):
        self.legacy_db.upsert_article_detail(
            {
                "title": "缺字段文章",
                "read_user": 123,
                "avg_read_time": 18,
                "share_user": 9,
                "import_file": "detail.xls",
            }
        )
        conn = sqlite3.connect(str(self.analytics_db))
        row = conn.execute(
            "SELECT title, read_user, avg_read_time, complete_rate, share_user FROM article_detail WHERE title=?",
            ("缺字段文章",),
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "缺字段文章")
        self.assertEqual(row[1], 123)
        self.assertEqual(row[2], 18)
        self.assertEqual(row[3], 0)
        self.assertEqual(row[4], 9)

    def test_pending_ignore_marks_record_ignored(self):
        conn = self.master_db_mod.get_master_conn()
        conn.execute(
            """INSERT INTO pending_records
               (source_file, record_type, article_hint, issue_type, issue_message, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("bad.xls", "article_source", "待确认文章", "missing_identity", "缺少识别信息", "{}"),
        )
        pending_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        sys.modules.pop("app", None)
        sys.modules.pop("routes.master", None)
        sys.modules.pop("routes", None)
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        response = client.post(f"/master/pending/{pending_id}", data={"action": "ignore"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        conn = self.master_db_mod.get_master_conn()
        status = conn.execute("SELECT status FROM pending_records WHERE id=?", (pending_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(status, "ignored")

    def test_pending_associate_writes_source_into_existing_article(self):
        self.master_db_mod.sync_master_from_import(
            "article_detail",
            {"detail": {"title": "已有文章", "read_user": 100, "import_file": "detail.xls"}, "trend": []},
            "detail.xls",
        )
        conn = self.master_db_mod.get_master_conn()
        article_id = conn.execute(
            "SELECT id FROM article_master WHERE canonical_title='已有文章'"
        ).fetchone()[0]
        payload = [
            {
                "channel": "全部",
                "publish_date": "2026-03-03",
                "title": "待关联文章",
                "read_user": 222,
                "read_ratio": 1.0,
            }
        ]
        conn.execute(
            """INSERT INTO pending_records
               (source_file, record_type, article_hint, issue_type, issue_message, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("pending.xls", "article_source", "待关联文章", "match_failed", "无法自动匹配", json.dumps(payload, ensure_ascii=False)),
        )
        pending_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        sys.modules.pop("app", None)
        sys.modules.pop("routes.master", None)
        sys.modules.pop("routes", None)
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        response = client.post(
            f"/master/pending/{pending_id}",
            data={"action": "associate", "article_id": str(article_id)},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        conn = self.master_db_mod.get_master_conn()
        source = conn.execute(
            """SELECT article_id, read_user FROM traffic_source_stats
               WHERE publish_date='2026-03-03' AND channel='全部'"""
        ).fetchone()
        status = conn.execute("SELECT status FROM pending_records WHERE id=?", (pending_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(source[0], article_id)
        self.assertEqual(source[1], 222)
        self.assertEqual(status, "resolved")

    def test_pending_create_builds_new_article_and_resolves(self):
        conn = self.master_db_mod.get_master_conn()
        payload = {
            "title": "",
            "read_user": 345,
            "share_user": 11,
            "comment_count": 2,
        }
        conn.execute(
            """INSERT INTO pending_records
               (source_file, record_type, article_hint, issue_type, issue_message, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("detail.xls", "article_detail", "新建文章", "missing_title", "标题缺失", json.dumps(payload, ensure_ascii=False)),
        )
        pending_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        sys.modules.pop("app", None)
        sys.modules.pop("routes.master", None)
        sys.modules.pop("routes", None)
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        response = client.post(
            f"/master/pending/{pending_id}",
            data={
                "action": "create",
                "title": "人工新建文章",
                "publish_date": "2026-03-05",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        conn = self.master_db_mod.get_master_conn()
        article = conn.execute(
            "SELECT canonical_title, publish_date, total_reads FROM article_master WHERE canonical_title='人工新建文章'"
        ).fetchone()
        status = conn.execute("SELECT status FROM pending_records WHERE id=?", (pending_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(article[0], "人工新建文章")
        self.assertEqual(article[1], "2026-03-05")
        self.assertEqual(article[2], 345)
        self.assertEqual(status, "resolved")

    def test_dashboard_and_user_queries_prefer_master_db(self):
        previous_day = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        recent_day = datetime.now().strftime("%Y-%m-%d")
        self.master_db_mod.sync_master_from_import(
            "tendency",
            {
                "daily_reads": [
                    {"stat_date": previous_day, "channel": "全部", "read_user": 2000},
                    {"stat_date": previous_day, "channel": "推荐", "read_user": 600},
                    {"stat_date": recent_day, "channel": "全部", "read_user": 1500},
                    {"stat_date": recent_day, "channel": "推荐", "read_user": 450},
                ],
                "daily_stats": [
                    {
                        "stat_date": previous_day,
                        "share_user": 50,
                        "original_read_user": 11,
                        "fav_user": 20,
                        "article_count": 1,
                    },
                    {
                        "stat_date": recent_day,
                        "share_user": 30,
                        "original_read_user": 8,
                        "fav_user": 16,
                        "article_count": 1,
                    },
                ],
                "article_sources": [
                    {
                        "channel": "全部",
                        "publish_date": previous_day,
                        "title": "文章A",
                        "read_user": 2000,
                        "read_ratio": 1.0,
                    },
                    {
                        "channel": "推荐",
                        "publish_date": previous_day,
                        "title": "文章A",
                        "read_user": 600,
                        "read_ratio": 0.3,
                    },
                    {
                        "channel": "全部",
                        "publish_date": recent_day,
                        "title": "文章B",
                        "read_user": 1500,
                        "read_ratio": 1.0,
                    },
                    {
                        "channel": "推荐",
                        "publish_date": recent_day,
                        "title": "文章B",
                        "read_user": 450,
                        "read_ratio": 0.3,
                    },
                ],
            },
            "tendency.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "article_detail",
            {
                "detail": {
                    "title": "文章A",
                    "read_user": 2100,
                    "avg_read_time": 40,
                    "complete_rate": 0.68,
                    "follow_after_read": 25,
                    "share_user": 55,
                    "like_user": 18,
                    "thumbup_user": 7,
                    "fav_user": 28,
                    "comment_count": 9,
                    "deliver_user": 2200,
                    "msg_read_user": 1320,
                },
                "trend": [],
            },
            "detail_a.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "article_detail",
            {
                "detail": {
                    "title": "文章B",
                    "read_user": 1600,
                    "avg_read_time": 35,
                    "complete_rate": 0.52,
                    "follow_after_read": 14,
                    "share_user": 31,
                    "like_user": 10,
                    "thumbup_user": 5,
                    "fav_user": 19,
                    "comment_count": 4,
                    "deliver_user": 1700,
                    "msg_read_user": 850,
                },
                "trend": [],
            },
            "detail_b.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "user",
            {
                "records": [
                    {
                        "stat_date": previous_day,
                        "new_user": 20,
                        "cancel_user": 4,
                        "net_user": 16,
                        "total_user": 1000,
                    },
                    {
                        "stat_date": recent_day,
                        "new_user": 18,
                        "cancel_user": 3,
                        "net_user": 15,
                        "total_user": 1015,
                    },
                ]
            },
            "user.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "msg",
            {
                "records": [
                    {"stat_date": previous_day, "msg_user": 8, "msg_count": 22, "avg_msg": 2.75},
                    {"stat_date": recent_day, "msg_user": 5, "msg_count": 10, "avg_msg": 2.0},
                ]
            },
            "msg.xls",
        )
        self.legacy_db.record_import("dummy.xls", "2026-03", 10)

        ranking = self.legacy_db.query_article_ranking()
        summary = self.legacy_db.query_summary()
        users = self.legacy_db.query_user_stats(days=60)
        total_user_trend = self.legacy_db.query_total_user_trend(days=60)
        freshness = self.legacy_db.query_data_freshness()
        funnel = self.legacy_db.query_funnel()
        best_time = self.legacy_db.query_best_publish_time()

        self.assertEqual(ranking[0]["title"], "文章A")
        self.assertEqual(ranking[0]["total_reads"], 2100)
        self.assertEqual(ranking[0]["rec_pct"], 28.6)
        self.assertEqual(summary["total_reads_30d"], 3500)
        self.assertEqual(summary["total_articles_30d"], 2)
        self.assertEqual(summary["avg_share_30d"], 40.0)
        self.assertEqual(summary["net_user_30d"], 31)
        self.assertEqual(summary["total_user"], 1015)
        self.assertEqual(summary["import_count"], 1)
        self.assertEqual(len(users), 2)
        self.assertEqual(users[-1]["total_user"], 1015)
        self.assertEqual(total_user_trend[-1]["total_user"], 1015)
        freshness_map = {item["source"]: item["last_update"] for item in freshness}
        self.assertEqual(freshness_map["趋势数据"], recent_day)
        self.assertEqual(freshness_map["用户数据"], recent_day)
        self.assertEqual(freshness_map["消息数据"], recent_day)
        self.assertEqual(funnel["reads"], 3700)
        self.assertAlmostEqual(funnel["share_rate"], round((86 / 3700) * 100, 2))
        self.assertEqual(best_time["by_dow"][0]["avg_reads"], 2100.0)

    def test_dashboard_and_user_api_shapes_match_templates(self):
        recent_day = datetime.now().strftime("%Y-%m-%d")
        self.master_db_mod.sync_master_from_import(
            "tendency",
            {
                "daily_reads": [
                    {"stat_date": recent_day, "channel": "全部", "read_user": 1000},
                    {"stat_date": recent_day, "channel": "推荐", "read_user": 400},
                ],
                "daily_stats": [
                    {
                        "stat_date": recent_day,
                        "share_user": 22,
                        "original_read_user": 5,
                        "fav_user": 9,
                        "article_count": 1,
                    }
                ],
                "article_sources": [
                    {
                        "channel": "全部",
                        "publish_date": recent_day,
                        "title": "页面文章",
                        "read_user": 1000,
                        "read_ratio": 1.0,
                    },
                    {
                        "channel": "推荐",
                        "publish_date": recent_day,
                        "title": "页面文章",
                        "read_user": 400,
                        "read_ratio": 0.4,
                    },
                ],
            },
            "page.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "article_detail",
            {
                "detail": {
                    "title": "页面文章",
                    "read_user": 1000,
                    "share_user": 22,
                    "like_user": 8,
                    "fav_user": 9,
                    "follow_after_read": 6,
                    "comment_count": 2,
                },
                "trend": [],
            },
            "page_detail.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "user",
            {
                "records": [
                    {
                        "stat_date": recent_day,
                        "new_user": 10,
                        "cancel_user": 2,
                        "net_user": 8,
                        "total_user": 888,
                    }
                ]
            },
            "page_user.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "msg",
            {"records": [{"stat_date": recent_day, "msg_user": 3, "msg_count": 7, "avg_msg": 2.33}]},
            "page_msg.xls",
        )

        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        freshness = client.get("/api/freshness").get_json()
        daily = client.get("/api/daily").get_json()
        msg_stats = client.get("/api/msg-stats").get_json()
        funnel = client.get("/api/funnel").get_json()

        self.assertIsInstance(freshness, list)
        self.assertTrue(any(item["source"] == "趋势数据" for item in freshness))
        self.assertIn("dates", daily)
        self.assertIn("series", daily)
        self.assertEqual(msg_stats[0]["msg_count"], 7)
        self.assertIsInstance(funnel, list)
        self.assertEqual(funnel[0]["stage"], "阅读")

    def test_pruned_modules_are_absent_from_dashboard(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        dashboard_html = client.get("/").get_data(as_text=True)

        self.assertNotIn("文章排行 Top 10", dashboard_html)
        self.assertNotIn("每日阅读趋势", dashboard_html)
        self.assertNotIn("推荐命中率趋势", dashboard_html)
        self.assertNotIn("月度目标进度", dashboard_html)
        self.assertNotIn("异常事件", dashboard_html)
        self.assertNotIn("/api/daily", dashboard_html)
        self.assertNotIn("/api/recommend-trend", dashboard_html)
        self.assertNotIn("/api/goal-prediction", dashboard_html)
        self.assertNotIn("/api/anomaly-log", dashboard_html)

    def test_dashboard_absorbs_data_management_actions(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        dashboard_html = client.get("/").get_data(as_text=True)

        self.assertNotIn("数据库概览", dashboard_html)
        self.assertIn("同步文章阅读数", dashboard_html)
        self.assertIn("/export/db", dashboard_html)
        self.assertIn("/export/daily.csv", dashboard_html)
        self.assertIn("导入历史", dashboard_html)

    def test_data_route_redirects_to_dashboard(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        response = client.get("/data", follow_redirects=False)

        self.assertIn(response.status_code, (301, 302, 303, 307, 308))
        self.assertEqual(response.headers["Location"], "/")

    def test_users_route_redirects_to_master(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        response = client.get("/users", follow_redirects=False)

        self.assertIn(response.status_code, (301, 302, 303, 307, 308))
        self.assertTrue(response.headers["Location"].endswith("/master"))

    def test_summary_route_redirects_to_dashboard(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        response = client.get("/summary", follow_redirects=False)

        self.assertIn(response.status_code, (301, 302, 303, 307, 308))
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(client.get("/api/period-summary").status_code, 404)
        self.assertEqual(client.get("/api/month-comparison").status_code, 404)
        self.assertEqual(client.get("/api/yoy").status_code, 404)
        self.assertEqual(client.get("/api/weekly-report").status_code, 404)
        self.assertEqual(client.get("/api/goal-prediction").status_code, 404)
        self.assertEqual(client.get("/api/goals").status_code, 404)
        self.assertEqual(client.get("/api/tag-analysis").status_code, 404)
        self.assertEqual(client.get("/api/keywords").status_code, 404)
        self.assertEqual(client.post("/api/ai-report").status_code, 404)

    def test_pruned_modules_are_absent_from_master_articles_and_insights_pages(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        articles_html = client.get("/master?tab=articles").get_data(as_text=True)
        insights_html = client.get("/insights").get_data(as_text=True)

        self.assertNotIn("渠道分布 Top 15", articles_html)
        self.assertNotIn("推荐入选规律", articles_html)
        self.assertNotIn("/api/recommend-analysis", articles_html)

        self.assertNotIn("推荐入选规律 - 星期分布", insights_html)
        self.assertNotIn("推荐入选规律 - 占比分布", insights_html)
        self.assertNotIn("/api/recommend-analysis", insights_html)

    def test_articles_route_redirects_to_master_articles_tab(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        response = client.get("/articles", follow_redirects=False)

        self.assertIn(response.status_code, (301, 302, 303, 307, 308))
        self.assertEqual(response.headers["Location"], "/master?tab=articles&order=reads")

    def test_master_articles_tab_includes_legacy_article_ranking_features(self):
        today = datetime.now().date()
        self.master_db_mod.sync_master_from_import(
            "tendency",
            {
                "daily_reads": [
                    {"stat_date": str(today), "channel": "全部", "read_user": 1600},
                    {"stat_date": str(today), "channel": "推荐", "read_user": 640},
                ],
                "daily_stats": [
                    {"stat_date": str(today), "share_user": 18, "original_read_user": 2, "fav_user": 5, "article_count": 1},
                ],
                "article_sources": [
                    {"channel": "全部", "publish_date": str(today), "title": "主档并页文章", "read_user": 1600, "read_ratio": 1.0},
                    {"channel": "推荐", "publish_date": str(today), "title": "主档并页文章", "read_user": 640, "read_ratio": 0.4},
                ],
            },
            "master_articles_merge_tendency.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "article_detail",
            {
                "detail": {
                    "title": "主档并页文章",
                    "read_user": 1600,
                    "avg_read_time": 45,
                    "complete_rate": 0.68,
                    "share_user": 18,
                    "like_user": 9,
                    "fav_user": 7,
                    "comment_count": 3,
                },
                "trend": [],
            },
            "master_articles_merge_detail.xls",
        )

        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        html = client.get("/master?tab=articles").get_data(as_text=True)

        self.assertIn("导出 CSV", html)
        self.assertIn("推荐占比", html)
        self.assertIn("完读率", html)
        self.assertIn("均读时长", html)
        self.assertIn("阅读后关注", html)
        self.assertIn("editable-cell", html)
        self.assertIn("/api/article-field/", html)
        self.assertIn("/master/article/", html)

    def test_master_metadata_and_competitor_features_persist_to_master_db(self):
        today = datetime.now().date()
        self.master_db_mod.sync_master_from_import(
            "article_detail",
            {
                "detail": {
                    "title": "主库文章",
                    "read_user": 1234,
                    "avg_read_time": 42,
                    "complete_rate": 0.66,
                },
                "trend": [],
            },
            "seed_detail.xls",
        )

        self.legacy_db.save_setting("wx_token", "abc123")
        self.assertEqual(self.legacy_db.load_setting("wx_token"), "abc123")

        self.legacy_db.record_import("seed_detail.xls", "主库文章", 1)
        history = self.legacy_db.query_import_history()
        self.assertEqual(history[0]["filename"], "seed_detail.xls")
        self.assertEqual(self.legacy_db.get_import_record("seed_detail.xls")["rows_imported"], 1)

        self.legacy_db.upsert_article_msgids([
            {"msgid": "10001", "title": "主库文章", "publish_date": str(today)},
        ])
        self.legacy_db.mark_detail_downloaded("10001")
        msgids = self.legacy_db.query_article_msgids()
        self.assertEqual(msgids[0]["msgid"], "10001")
        self.assertEqual(msgids[0]["detail_downloaded"], 1)

        self.legacy_db.upsert_article_tag("主库文章", "爆文")
        self.assertEqual(self.legacy_db.query_article_tags("主库文章")[0]["tag"], "爆文")
        self.legacy_db.delete_article_tag("主库文章", "爆文")
        self.assertEqual(self.legacy_db.query_article_tags("主库文章"), [])

        self.legacy_db.upsert_planned_article(str(today), "新选题", "备注", "planned")
        plans = self.legacy_db.query_planned_articles()
        self.assertEqual(plans[0]["topic"], "新选题")
        self.legacy_db.delete_planned_article(plans[0]["id"])
        self.assertEqual(self.legacy_db.query_planned_articles(), [])

        pred_id = self.legacy_db.save_prediction({
            "title": "主库文章",
            "a_score": 1,
            "b_score": 2,
            "c_score": 3,
            "d_score": 4,
            "e_score": 5,
            "f_score": 6,
            "g_score": 4,
            "total_score": 21,
            "path_type": "A",
            "pred_reads": "1000-2000",
            "pred_rec_pct": "20-30%",
            "pred_read_rate": "10-20%",
            "pred_comments": "5-10",
            "notes": "备注",
        })
        self.assertGreater(pred_id, 0)
        self.assertEqual(self.legacy_db.get_predictions(1)[0]["title"], "主库文章")
        self.assertEqual(self.legacy_db.get_predictions(1)[0]["g_score"], 4)
        self.assertTrue(self.legacy_db.update_prediction_actuals(pred_id, {
            "actual_reads": 1888,
            "actual_rec_pct": 26.5,
            "actual_read_rate": 17.2,
            "actual_comments": 8,
        }))

        account_id = self.legacy_db.get_or_create_competitor("对标号")
        import_result = self.legacy_db.import_competitor_articles(account_id, [{
            "title": "对标爆文",
            "url": "https://example.com/a",
            "publish_time": "2026-03-01 08:00",
            "like_num": 11,
            "read_num": 2222,
            "share_num": 33,
            "comment_count": 4,
        }])
        self.assertEqual(import_result["inserted"], 1)
        accounts = self.legacy_db.get_competitor_accounts()
        self.assertEqual(accounts[0]["nickname"], "对标号")
        articles = self.legacy_db.get_competitor_articles(account_id)
        self.assertEqual(articles[0]["title"], "对标爆文")
        self.legacy_db.save_viral_analysis(articles[0]["id"], json.dumps({"score": 88}, ensure_ascii=False))
        self.legacy_db.save_article_content(articles[0]["id"], "正文")

        conn = sqlite3.connect(str(self.master_db))
        conn.row_factory = sqlite3.Row
        tables = {
            "settings": conn.execute("SELECT value FROM settings WHERE key='wx_token'").fetchone(),
            "import_history": conn.execute("SELECT filename FROM import_history WHERE filename='seed_detail.xls'").fetchone(),
            "article_msgids": conn.execute("SELECT detail_downloaded FROM article_msgids WHERE msgid='10001'").fetchone(),
            "article_predictions": conn.execute("SELECT actual_reads FROM article_predictions WHERE id=?", (pred_id,)).fetchone(),
            "competitor_accounts": conn.execute("SELECT nickname FROM competitor_accounts WHERE id=?", (account_id,)).fetchone(),
            "competitor_articles": conn.execute("SELECT viral_analysis, content_text FROM competitor_articles WHERE account_id=?", (account_id,)).fetchone(),
        }
        conn.close()
        self.assertEqual(tables["settings"]["value"], "abc123")
        self.assertEqual(tables["import_history"]["filename"], "seed_detail.xls")
        self.assertEqual(tables["article_msgids"]["detail_downloaded"], 1)
        self.assertEqual(tables["article_predictions"]["actual_reads"], 1888)
        self.assertEqual(tables["competitor_accounts"]["nickname"], "对标号")
        self.assertEqual(json.loads(tables["competitor_articles"]["viral_analysis"])["score"], 88)
        self.assertEqual(tables["competitor_articles"]["content_text"], "正文")

    def test_query_summary_import_count_only_reads_master_import_history(self):
        self.master_db_mod.sync_master_from_import(
            "tendency",
            {
                "daily_reads": [
                    {"stat_date": "2026-03-12", "channel": "全部", "read_user": 1000},
                ],
                "daily_stats": [
                    {
                        "stat_date": "2026-03-12",
                        "share_user": 22,
                        "original_read_user": 5,
                        "fav_user": 9,
                        "article_count": 1,
                    }
                ],
                "article_sources": [
                    {
                        "channel": "全部",
                        "publish_date": "2026-03-12",
                        "title": "主库文章",
                        "read_user": 1000,
                        "read_ratio": 1.0,
                    }
                ],
            },
            "summary_only_master.xls",
        )
        legacy_conn = sqlite3.connect(str(self.analytics_db))
        legacy_conn.execute(
            "INSERT INTO import_history (filename, date_range, rows_imported) VALUES (?, ?, ?)",
            ("legacy_only.xls", "2026-03", 1),
        )
        legacy_conn.commit()
        legacy_conn.close()

        summary = self.legacy_db.query_summary()
        self.assertEqual(summary["import_count"], 0)

    def test_query_import_history_does_not_fallback_to_legacy_when_master_empty(self):
        legacy_conn = sqlite3.connect(str(self.analytics_db))
        legacy_conn.execute(
            "INSERT INTO import_history (filename, date_range, rows_imported) VALUES (?, ?, ?)",
            ("legacy_only.xls", "2026-03", 1),
        )
        legacy_conn.commit()
        legacy_conn.close()

        self.assertEqual(self.legacy_db.query_import_history(), [])
        self.assertIsNone(self.legacy_db.get_import_record("legacy_only.xls"))

    def test_update_article_field_normalizes_publish_date_to_dash(self):
        self.master_db_mod.sync_master_from_import(
            "article_detail",
            {
                "detail": {
                    "title": "日期编辑文章",
                    "read_user": 900,
                },
                "trend": [],
            },
            "edit_detail.xls",
        )

        ok, err = self.legacy_db.update_article_field("日期编辑文章", "publish_date", "2026/03/29")
        self.assertTrue(ok, err)

        conn = sqlite3.connect(str(self.master_db))
        article_date = conn.execute(
            "SELECT publish_date FROM article_master WHERE canonical_title='日期编辑文章'"
        ).fetchone()[0]
        override_value = conn.execute(
            """SELECT override_value FROM article_overrides
               WHERE field_name='publish_date' AND article_id = (
                   SELECT id FROM article_master WHERE canonical_title='日期编辑文章'
               )"""
        ).fetchone()[0]
        conn.close()

        self.assertEqual(article_date, "2026-03-29")
        self.assertEqual(override_value, "2026-03-29")

    def test_master_insight_and_article_routes_work_without_legacy_article_tables(self):
        today = datetime.now().date()
        pub_date = today - timedelta(days=2)
        self.master_db_mod.sync_master_from_import(
            "tendency",
            {
                "daily_reads": [
                    {"stat_date": str(today - timedelta(days=2)), "channel": "全部", "read_user": 900},
                    {"stat_date": str(today - timedelta(days=2)), "channel": "推荐", "read_user": 300},
                    {"stat_date": str(today - timedelta(days=1)), "channel": "全部", "read_user": 1500},
                    {"stat_date": str(today - timedelta(days=1)), "channel": "推荐", "read_user": 600},
                    {"stat_date": str(today), "channel": "全部", "read_user": 800},
                    {"stat_date": str(today), "channel": "推荐", "read_user": 100},
                ],
                "daily_stats": [
                    {"stat_date": str(today - timedelta(days=2)), "share_user": 12, "original_read_user": 2, "fav_user": 5, "article_count": 1},
                    {"stat_date": str(today - timedelta(days=1)), "share_user": 18, "original_read_user": 3, "fav_user": 7, "article_count": 1},
                    {"stat_date": str(today), "share_user": 9, "original_read_user": 1, "fav_user": 4, "article_count": 1},
                ],
                "article_sources": [
                    {"channel": "全部", "publish_date": str(pub_date), "title": "7个方法让你过线？", "read_user": 900, "read_ratio": 1.0},
                    {"channel": "推荐", "publish_date": str(pub_date), "title": "7个方法让你过线？", "read_user": 300, "read_ratio": 0.333},
                ],
            },
            "insight_tendency.xls",
        )
        self.master_db_mod.sync_master_from_import(
            "article_detail",
            {
                "detail": {
                    "title": "7个方法让你过线？",
                    "read_user": 1200,
                    "avg_read_time": 38,
                    "complete_rate": 0.62,
                    "follow_after_read": 15,
                    "share_user": 30,
                    "comment_count": 6,
                    "deliver_user": 1400,
                    "msg_read_user": 700,
                },
                "trend": [
                    {"stat_date": str(pub_date), "channel": "全部", "read_user": 600, "share_user": 10},
                    {"stat_date": str(pub_date + timedelta(days=1)), "channel": "全部", "read_user": 400, "share_user": 8},
                    {"stat_date": str(pub_date + timedelta(days=2)), "channel": "全部", "read_user": 200, "share_user": 4},
                ],
            },
            "insight_detail.xls",
        )

        title_analysis = self.legacy_db.query_title_analysis()
        lifecycle = self.legacy_db.query_lifecycle_data(1)
        trend = self.legacy_db.query_article_trend("7个方法让你过线？")
        details = self.legacy_db.query_article_details()
        calendar = self.legacy_db.query_calendar_data()
        posting = self.legacy_db.query_posting_frequency()
        follower = self.legacy_db.query_follower_attribution()
        holiday = self.legacy_db.query_holiday_analysis()
        heatmap = self.legacy_db.query_heatmap_data(30)
        month_comparison = self.legacy_db.query_month_comparison()
        yoy = self.legacy_db.query_yoy_comparison()

        self.assertGreater(len(title_analysis["by_length"]), 0)
        self.assertEqual(lifecycle[0]["data"][0]["day"], 0)
        self.assertEqual(len(trend), 3)
        self.assertEqual(details[0]["title"], "7个方法让你过线？")
        self.assertEqual(calendar[0]["title"], "7个方法让你过线？")
        self.assertGreater(len(posting), 0)
        self.assertEqual(follower[0]["follow_after_read"], 15)
        self.assertIn("workday", holiday)
        self.assertGreater(len(heatmap), 0)
        self.assertIn("this_month", month_comparison)
        self.assertIsInstance(yoy, list)

        sys.modules.pop("app", None)
        sys.modules.pop("routes", None)
        sys.modules.pop("routes.articles", None)
        sys.modules.pop("routes.competitor", None)
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()
        detail_page = client.get("/article/7%E4%B8%AA%E6%96%B9%E6%B3%95%E8%AE%A9%E4%BD%A0%E8%BF%87%E7%BA%BF%EF%BC%9F")
        competitor_pending = client.get("/api/competitor/pending-content")
        self.assertEqual(detail_page.status_code, 200)
        self.assertIn("1200", detail_page.get_data(as_text=True))
        self.assertEqual(competitor_pending.status_code, 200)

    def test_do_import_updates_master_without_legacy_tables(self):
        if self.analytics_db.exists():
            self.analytics_db.unlink()

        sys.modules.pop("routes.api_common", None)
        api_common = importlib.import_module("routes.api_common")
        fake_file = Path(self.tmpdir.name) / "tendency_fake.xls"
        fake_file.write_text("unused", encoding="utf-8")

        original_parse_any = api_common.parse_any
        try:
            today = datetime.now().date()
            api_common.parse_any = lambda _: {
                "type": "tendency",
                "data": {
                    "date_range": "mock",
                    "daily_reads": [
                        {"stat_date": str(today), "channel": "全部", "read_user": 999},
                        {"stat_date": str(today), "channel": "推荐", "read_user": 222},
                    ],
                    "daily_stats": [
                        {"stat_date": str(today), "share_user": 12, "original_read_user": 3, "fav_user": 5, "article_count": 1},
                    ],
                    "article_sources": [
                        {"channel": "全部", "publish_date": str(today), "title": "导入文章", "read_user": 999, "read_ratio": 1.0},
                        {"channel": "推荐", "publish_date": str(today), "title": "导入文章", "read_user": 222, "read_ratio": 0.222},
                    ],
                },
            }
            result = api_common.do_import(fake_file)
        finally:
            api_common.parse_any = original_parse_any

        self.assertTrue(result["ok"])
        history = self.legacy_db.query_import_history()
        self.assertEqual(history[0]["filename"], "tendency_fake.xls")
        conn = sqlite3.connect(str(self.master_db))
        article = conn.execute("SELECT canonical_title, total_reads FROM article_master WHERE canonical_title='导入文章'").fetchone()
        daily = conn.execute("SELECT total_read_user FROM account_daily_metrics").fetchone()
        conn.close()
        self.assertEqual(article[0], "导入文章")
        self.assertEqual(article[1], 999)
        self.assertEqual(daily[0], 999)

    def test_competitor_import_merges_multiple_csvs_under_one_real_nickname(self):
        os.environ["COMPETITOR_IMPORT_DIR"] = str(Path(self.tmpdir.name) / "对标账号")
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        csv_a = (
            "nickname,title,url,time,like_num,read_num,share_num,comment_count\n"
            "公众号,文章A,https://example.com/a,2026-03-19 10:00:00,1,100,0,0\n"
            "公众号,文章B,https://example.com/b,2026-03-19 09:00:00,2,200,0,0\n"
        )
        csv_b = (
            "nickname,title,url,time,like_num,read_num,share_num,comment_count\n"
            "吉井解学,文章A,https://example.com/a,2026-03-19 10:00:00,1,100,0,0\n"
            "吉井解学,文章C,https://example.com/c,2026-03-19 11:00:00,3,300,0,1\n"
        )

        response = client.post(
            "/api/competitor/import",
            data={
                "files": [
                    (io.BytesIO(csv_a.encode("utf-8")), "2026-03-19-100000.csv"),
                    (io.BytesIO(csv_b.encode("utf-8")), "2026-03-19-110000.csv"),
                ]
            },
            content_type="multipart/form-data",
        )

        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["nickname"], "吉井解学")
        self.assertEqual(payload["source_files"], 2)
        self.assertEqual(payload["total_rows"], 4)
        self.assertEqual(payload["deduped_rows"], 3)
        self.assertEqual(payload["inserted"], 3)

        accounts = self.legacy_db.get_competitor_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["nickname"], "吉井解学")
        articles = self.legacy_db.get_competitor_articles(accounts[0]["id"])
        self.assertEqual(len(articles), 3)

        prepared = Path(os.environ["COMPETITOR_IMPORT_DIR"]) / payload["prepared_filename"]
        self.assertTrue(prepared.exists())
        self.assertTrue(prepared.name.startswith("吉井解学_"))

    def test_competitor_import_rejects_multiple_real_nicknames(self):
        os.environ["COMPETITOR_IMPORT_DIR"] = str(Path(self.tmpdir.name) / "对标账号")
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        csv_body = (
            "nickname,title,url,time,like_num,read_num,share_num,comment_count\n"
            "吉井解学,文章A,https://example.com/a,2026-03-19 10:00:00,1,100,0,0\n"
            "康乐解学,文章B,https://example.com/b,2026-03-19 11:00:00,2,200,0,0\n"
        )

        response = client.post(
            "/api/competitor/import",
            data={"file": (io.BytesIO(csv_body.encode("utf-8")), "conflict.csv")},
            content_type="multipart/form-data",
        )

        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("多个真实公众号名", payload["error"])

    def test_competitor_import_local_prepares_each_download_directory(self):
        base_dir = Path(self.tmpdir.name) / "对标账号"
        os.environ["COMPETITOR_IMPORT_DIR"] = str(base_dir)
        raw_dir = base_dir / "链接5-吉井解学-130" / "下载"
        raw_dir.mkdir(parents=True)
        (raw_dir / "2026-03-18-154957.csv").write_text(
            "nickname,title,url,time,like_num,read_num,share_num,comment_count\n"
            "公众号,文章A,https://example.com/a,2026-03-18 15:49:57,1,100,0,0\n"
            "吉井解学,文章B,https://example.com/b,2026-03-18 15:50:00,2,200,0,0\n",
            encoding="utf-8",
        )
        (raw_dir / "2026-03-18-193829.csv").write_text(
            "nickname,title,url,time,like_num,read_num,share_num,comment_count\n"
            "吉井解学,文章A,https://example.com/a,2026-03-18 19:38:29,1,100,0,0\n"
            "吉井解学,文章C,https://example.com/c,2026-03-18 19:38:30,3,300,0,1\n",
            encoding="utf-8",
        )

        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        response = client.post("/api/competitor/import-local")
        payload = response.get_json()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["accounts"], 1)
        self.assertEqual(payload["details"][0]["nickname"], "吉井解学")
        self.assertEqual(payload["details"][0]["deduped_rows"], 3)
        prepared = base_dir / payload["details"][0]["prepared_filename"]
        self.assertTrue(prepared.exists())

        accounts = self.legacy_db.get_competitor_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["nickname"], "吉井解学")

    def test_competitor_import_can_infer_real_nickname_from_merged_filename(self):
        os.environ["COMPETITOR_IMPORT_DIR"] = str(Path(self.tmpdir.name) / "对标账号")
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        csv_body = (
            "nickname,title,url,time,like_num,read_num,share_num,comment_count\n"
            "公众号,文章A,https://example.com/a,2026-03-19 10:00:00,1,100,0,0\n"
            "公众号,文章B,https://example.com/b,2026-03-19 09:00:00,2,200,0,0\n"
        )

        response = client.post(
            "/api/competitor/import",
            data={
                "file": (
                    io.BytesIO(csv_body.encode("utf-8")),
                    "吉井解学_2026-03-18-154957_to_2026-03-18-193829_merged_dedup.csv",
                )
            },
            content_type="multipart/form-data",
        )

        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["nickname"], "吉井解学")
        accounts = self.legacy_db.get_competitor_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["nickname"], "吉井解学")

    def test_placeholder_competitor_account_is_repaired_from_merged_csv_files(self):
        base_dir = Path(self.tmpdir.name) / "对标账号"
        os.environ["COMPETITOR_IMPORT_DIR"] = str(base_dir)
        base_dir.mkdir(parents=True)
        (base_dir / "吉井解学_2026-03-18-154957_to_2026-03-18-193829_merged_dedup.csv").write_text(
            "nickname,title,url,time,like_num,read_num,share_num,comment_count\n"
            "公众号,文章A,https://example.com/a,2026-03-18 15:49:57,1,100,0,0\n",
            encoding="utf-8",
        )

        conn = sqlite3.connect(str(self.master_db))
        conn.execute("INSERT INTO competitor_accounts (id, nickname) VALUES (?, ?)", (99, "公众号"))
        conn.execute(
            """INSERT INTO competitor_articles
               (account_id, title, url, publish_time, like_num, read_num, share_num, comment_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (99, "文章A", "https://example.com/a", "2026-03-18 15:49:57", 1, 100, 0, 0),
        )
        conn.commit()
        conn.close()

        accounts = self.legacy_db.get_competitor_accounts()
        nicknames = {account["nickname"] for account in accounts}

        self.assertNotIn("公众号", nicknames)
        self.assertIn("吉井解学", nicknames)
        target = next(account for account in accounts if account["nickname"] == "吉井解学")
        articles = self.legacy_db.get_competitor_articles(target["id"])
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "文章A")

    def test_competitor_page_exposes_export_for_selected_account(self):
        account_id = self.legacy_db.get_or_create_competitor("测试对标号")
        self.legacy_db.import_competitor_articles(account_id, [{
            "title": "导出文章",
            "url": "https://example.com/export",
            "publish_time": "2026-03-01 08:00:00",
            "like_num": 5,
            "read_num": 666,
            "share_num": 7,
            "comment_count": 1,
        }])

        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        body = client.get(f"/competitor?account_id={account_id}").get_data(as_text=True)

        self.assertIn(f"/export/competitor/{account_id}.csv", body)
        self.assertIn('href="https://example.com/export"', body)
        self.assertIn('target="_blank"', body)
        self.assertIn('id="competitor-account-select"', body)

    def test_predict_page_prefills_title_and_draft_from_query(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        body = client.get(
            "/predict?title=%E5%BE%85%E5%8F%91%E6%96%87%E7%AB%A0&draft=%E7%AC%AC%E4%B8%80%E6%AE%B5"
        ).get_data(as_text=True)

        self.assertIn('value="待发文章"', body)
        self.assertIn(">第一段</textarea>", body)

    def test_predict_page_renders_v02_workflow_and_extended_prefills(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        body = client.get(
            "/predict?title=%E7%88%86%E6%96%87%E6%B5%8B%E8%AF%95&"
            "draft=%E8%8D%89%E7%A8%BF%E7%AC%AC%E4%BA%8C%E6%AE%B5&"
            "source=%E5%AF%B9%E6%A0%87%E5%8F%B7&"
            "publish_date=2026-04-08&publish_time=20:00"
        ).get_data(as_text=True)

        self.assertIn("7维评分", body)
        self.assertIn("G 话题普适性", body)
        self.assertIn("AI 预打分提示词", body)
        self.assertIn('value="爆文测试"', body)
        self.assertIn(">草稿第二段</textarea>", body)
        self.assertIn('value="对标号"', body)
        self.assertIn('value="2026-04-08"', body)
        self.assertIn('value="20:00"', body)

    def test_push_calendar_page_exposes_predict_prefill_payload(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        body = client.get(
            "/push-calendar?title=%E7%88%86%E6%96%87%E6%B5%8B%E8%AF%95&"
            "draft=%E8%8D%89%E7%A8%BF%E5%86%85%E5%AE%B9&"
            "source=%E9%A2%84%E6%B5%8B%E9%A1%B5&"
            "date=2026-04-08&time=20:00"
        ).get_data(as_text=True)

        self.assertIn("window.pushCalendarPrefill", body)
        payload = body.split("window.pushCalendarPrefill = ", 1)[1].split(";</script>", 1)[0]
        prefill = json.JSONDecoder().raw_decode(payload)[0]
        self.assertEqual(prefill["title"], "爆文测试")
        self.assertEqual(prefill["draft"], "草稿内容")
        self.assertEqual(prefill["source"], "预测页")
        self.assertEqual(prefill["date"], "2026-04-08")
        self.assertEqual(prefill["time"], "20:00")

    def test_api_predict_save_accepts_g_dimension(self):
        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        response = client.post(
            "/api/predict/save",
            json={
                "title": "预测标题",
                "scores": {"a": 5, "b": 4, "c": 3, "d": 5, "e": 2, "f": 4, "g": 1},
                "predictions": {
                    "total": 29,
                    "path": "刚需路径",
                    "readsRange": "5000~8000",
                    "recRange": "5~20%",
                    "readRateRange": "55%+",
                    "commentsRange": "12~25",
                },
                "notes": "v0.2",
            },
        )

        payload = response.get_json()
        self.assertTrue(payload["ok"])
        saved = self.legacy_db.get_predictions(1)[0]
        self.assertEqual(saved["title"], "预测标题")
        self.assertEqual(saved["g_score"], 1)
        self.assertEqual(saved["pred_reads"], "5000~8000")

    def test_known_competitor_name_is_canonicalized_and_grouped(self):
        account_id = self.legacy_db.get_or_create_competitor("凌水球知道")
        accounts = self.legacy_db.get_competitor_accounts()
        account = next(a for a in accounts if a["id"] == account_id)

        self.assertEqual(account["nickname"], "DUT星球")
        self.assertEqual(account["matrix_name"], "DUT/NEU/求是矩阵")

    def test_competitor_page_supports_matrix_filter(self):
        dut_id = self.legacy_db.get_or_create_competitor("凌水球知道")
        neu_id = self.legacy_db.get_or_create_competitor("NEU星球")
        self.legacy_db.get_or_create_competitor("吉井解学")
        self.legacy_db.import_competitor_articles(dut_id, [{
            "title": "矩阵文章A",
            "url": "https://example.com/matrix-a",
            "publish_time": "2026-03-01 08:00:00",
            "like_num": 1,
            "read_num": 100,
            "share_num": 0,
            "comment_count": 0,
        }])
        self.legacy_db.import_competitor_articles(neu_id, [{
            "title": "矩阵文章B",
            "url": "https://example.com/matrix-b",
            "publish_time": "2026-03-01 08:00:00",
            "like_num": 1,
            "read_num": 100,
            "share_num": 0,
            "comment_count": 0,
        }])

        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        body = client.get("/competitor?matrix=DUT/NEU/求是矩阵").get_data(as_text=True)

        self.assertIn('id="competitor-matrix-select"', body)
        self.assertIn("DUT星球｜DUT/NEU/求是矩阵", body)
        self.assertIn("NEU星球｜DUT/NEU/求是矩阵", body)
        self.assertNotIn("吉井解学（0篇）", body)

    def test_competitor_export_csv_returns_selected_account_articles(self):
        account_id = self.legacy_db.get_or_create_competitor("测试对标号")
        other_id = self.legacy_db.get_or_create_competitor("其他对标号")
        self.legacy_db.import_competitor_articles(account_id, [{
            "title": "导出文章A",
            "url": "https://example.com/a",
            "publish_time": "2026-03-01 08:00:00",
            "like_num": 5,
            "read_num": 666,
            "share_num": 7,
            "comment_count": 1,
        }])
        self.legacy_db.import_competitor_articles(other_id, [{
            "title": "其他文章",
            "url": "https://example.com/b",
            "publish_time": "2026-03-01 09:00:00",
            "like_num": 1,
            "read_num": 222,
            "share_num": 0,
            "comment_count": 0,
        }])

        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        response = client.get(f"/export/competitor/{account_id}.csv")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment; filename=", response.headers.get("Content-Disposition", ""))
        self.assertIn("nickname,title,url,time,like_num,read_num,share_num,comment_count", body)
        self.assertIn("测试对标号,导出文章A,https://example.com/a,2026-03-01 08:00:00,5,666,7,1", body)
        self.assertNotIn("其他文章", body)

    def test_competitor_manual_analysis_save_persists_to_db(self):
        account_id = self.legacy_db.get_or_create_competitor("测试对标号")
        self.legacy_db.import_competitor_articles(account_id, [{
            "title": "记录文章",
            "url": "https://example.com/record",
            "publish_time": "2026-03-01 08:00:00",
            "like_num": 5,
            "read_num": 666,
            "share_num": 7,
            "comment_count": 1,
        }])
        article_id = self.legacy_db.get_competitor_articles(account_id)[0]["id"]

        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        response = client.post(
            f"/api/competitor/article/{article_id}/manual-analysis",
            json={
                "status": "done",
                "summary": "适合移植，但要补大工本地语境。",
                "notes": "对话结论：选题成立，标题要更具体，不能直接照搬。",
            },
        )
        payload = response.get_json()

        self.assertTrue(payload["ok"])
        article = self.legacy_db.get_competitor_article(article_id)
        self.assertEqual(article["manual_analysis_status"], "done")
        self.assertEqual(article["manual_analysis_summary"], "适合移植，但要补大工本地语境。")
        self.assertIn("标题要更具体", article["manual_analysis_notes"])

    def test_competitor_page_prefills_saved_manual_analysis(self):
        account_id = self.legacy_db.get_or_create_competitor("测试对标号")
        self.legacy_db.import_competitor_articles(account_id, [{
            "title": "记录文章",
            "url": "https://example.com/record",
            "publish_time": "2026-03-01 08:00:00",
            "like_num": 5,
            "read_num": 666,
            "share_num": 7,
            "comment_count": 1,
        }])
        article = self.legacy_db.get_competitor_articles(account_id)[0]

        conn = self.master_db_mod.get_master_conn()
        conn.execute(
            """UPDATE competitor_articles
               SET manual_analysis_status=?, manual_analysis_summary=?, manual_analysis_notes=?
               WHERE id=?""",
            ("done", "已记录结论", "这是一段手动分析备注", article["id"]),
        )
        conn.commit()
        conn.close()

        purge_app_modules()
        app_mod = importlib.import_module("app")
        client = app_mod.app.test_client()

        body = client.get(f"/competitor?account_id={account_id}").get_data(as_text=True)

        self.assertIn("记录分析", body)
        self.assertIn("已记录", body)
        self.assertIn("已记录结论", body)
        self.assertIn("这是一段手动分析备注", body)

    def test_best_publish_time_ignores_invalid_publish_dates_in_master(self):
        self.master_db_mod.sync_master_from_import(
            "tendency",
            {
                "daily_reads": [],
                "daily_stats": [],
                "article_sources": [
                    {
                        "channel": "全部",
                        "publish_date": "2026-03-12",
                        "title": "有效文章",
                        "read_user": 1000,
                        "read_ratio": 1.0,
                    }
                ],
            },
            "valid_tendency.xls",
        )
        conn = self.master_db_mod.get_master_conn()
        conn.execute(
            """INSERT INTO article_master (canonical_title, normalized_title, publish_date, total_reads)
               VALUES (?, ?, ?, ?)""",
            ("坏日期文章", self.master_db_mod.normalize_title("坏日期文章"), "not-a-date", 888),
        )
        conn.commit()
        conn.close()

        best = self.legacy_db.query_best_publish_time()
        self.assertTrue(best["by_dow"])
        self.assertEqual(best["by_dow"][0]["avg_reads"], 1000.0)


if __name__ == "__main__":
    unittest.main()
