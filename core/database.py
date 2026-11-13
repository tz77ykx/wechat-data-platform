from __future__ import annotations

import csv
import io
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from core.competitor_identity import canonicalize_competitor_name, competitor_matrix_name
from core.competitor_import_prep import EXPECTED_COLUMNS, PLACEHOLDER_NICKNAMES, infer_nickname_from_source_names
from config import BASE_DIR, DB_PATH, MASTER_DB_PATH


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_date_text(value):
    if value in (None, ""):
        return value
    return str(value).replace("/", "-")


def _legacy_table_exists(table_name: str) -> bool:
    if not DB_PATH.exists():
        return False
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        conn.close()
        return bool(row)
    except sqlite3.Error:
        return False


def _master_ready():
    if not MASTER_DB_PATH.exists():
        return False
    try:
        conn = sqlite3.connect(str(MASTER_DB_PATH))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='article_master'"
        ).fetchone()
        if not row:
            conn.close()
            return False
        conn.close()
        return True
    except sqlite3.Error:
        return False


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_reads (
            id INTEGER PRIMARY KEY,
            stat_date DATE NOT NULL,
            channel TEXT NOT NULL,
            read_user INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stat_date, channel)
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY,
            stat_date DATE UNIQUE NOT NULL,
            share_user INTEGER,
            original_read_user INTEGER,
            fav_user INTEGER,
            article_count INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS article_source_stats (
            id INTEGER PRIMARY KEY,
            publish_date DATE NOT NULL,
            title TEXT NOT NULL,
            channel TEXT NOT NULL,
            read_user INTEGER,
            read_ratio REAL,
            import_file TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(publish_date, title, channel)
        );

        CREATE TABLE IF NOT EXISTS import_history (
            id INTEGER PRIMARY KEY,
            filename TEXT UNIQUE,
            date_range TEXT,
            rows_imported INTEGER,
            imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS article_msgids (
            id INTEGER PRIMARY KEY,
            msgid TEXT UNIQUE NOT NULL,
            title TEXT,
            publish_date DATE,
            detail_downloaded INTEGER DEFAULT 0,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS daily_user_stats (
            id INTEGER PRIMARY KEY,
            stat_date DATE UNIQUE NOT NULL,
            new_user INTEGER,
            cancel_user INTEGER,
            net_user INTEGER,
            total_user INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS daily_msg_stats (
            id INTEGER PRIMARY KEY,
            stat_date DATE UNIQUE NOT NULL,
            msg_user INTEGER,
            msg_count INTEGER,
            avg_msg REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS menu_stats (
            id INTEGER PRIMARY KEY,
            menu_version TEXT NOT NULL,
            menu_level1 TEXT,
            menu_level2 TEXT,
            click_count INTEGER,
            click_user INTEGER,
            avg_click REAL,
            import_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(menu_version, menu_level1, menu_level2)
        );

        CREATE TABLE IF NOT EXISTS article_detail (
            id INTEGER PRIMARY KEY,
            title TEXT UNIQUE NOT NULL,
            read_user INTEGER,
            avg_read_time INTEGER,
            complete_rate REAL,
            follow_after_read INTEGER,
            share_user INTEGER,
            like_user INTEGER,
            thumbup_user INTEGER,
            fav_user INTEGER,
            reward INTEGER,
            comment_count INTEGER,
            deliver_user INTEGER,
            msg_read_user INTEGER,
            first_share_user INTEGER,
            total_share_user INTEGER,
            share_read_user INTEGER,
            import_file TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS article_trend (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            stat_date DATE NOT NULL,
            channel TEXT NOT NULL,
            read_user INTEGER,
            share_user INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(title, stat_date, channel)
        );

        CREATE TABLE IF NOT EXISTS article_tags (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(title, tag)
        );

        CREATE TABLE IF NOT EXISTS planned_articles (
            id INTEGER PRIMARY KEY,
            plan_date DATE NOT NULL,
            topic TEXT NOT NULL,
            note TEXT,
            status TEXT DEFAULT 'planned',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS anomaly_log (
            id INTEGER PRIMARY KEY,
            log_date DATE NOT NULL,
            today_reads INTEGER,
            avg7_reads INTEGER,
            pct REAL,
            direction TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(log_date)
        );

        CREATE TABLE IF NOT EXISTS competitor_accounts (
            id INTEGER PRIMARY KEY,
            nickname TEXT UNIQUE NOT NULL,
            matrix_name TEXT,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS competitor_articles (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            publish_time TEXT,
            like_num INTEGER DEFAULT 0,
            read_num INTEGER DEFAULT 0,
            share_num INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            content_text TEXT,
            viral_analysis TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, title)
        );

        CREATE TABLE IF NOT EXISTS article_predictions (
            id INTEGER PRIMARY KEY,
            title TEXT,
            created_at TEXT,
            a_score INTEGER,
            b_score INTEGER,
            c_score INTEGER,
            d_score INTEGER,
            e_score INTEGER,
            f_score INTEGER,
            g_score INTEGER,
            total_score INTEGER,
            path_type TEXT,
            pred_reads TEXT,
            pred_rec_pct TEXT,
            pred_read_rate TEXT,
            pred_comments TEXT,
            actual_reads INTEGER,
            actual_rec_pct REAL,
            actual_read_rate REAL,
            actual_comments INTEGER,
            notes TEXT
        );
    """)
    _ensure_competitor_article_columns(conn)
    _ensure_prediction_columns(conn)
    conn.commit()
    conn.close()


def _ensure_competitor_article_columns(conn):
    _ensure_table_column(conn, "competitor_accounts", "matrix_name", "TEXT")
    _normalize_competitor_accounts(conn)
    _ensure_table_column(conn, "competitor_articles", "manual_analysis_status", "TEXT DEFAULT 'pending'")
    _ensure_table_column(conn, "competitor_articles", "manual_analysis_summary", "TEXT")
    _ensure_table_column(conn, "competitor_articles", "manual_analysis_notes", "TEXT")
    _ensure_table_column(conn, "competitor_articles", "manual_analysis_updated_at", "DATETIME")


def _ensure_prediction_columns(conn):
    _ensure_table_column(conn, "article_predictions", "g_score", "INTEGER")


def _prepare_competitor_conn(conn):
    _ensure_competitor_article_columns(conn)
    conn.commit()
    return conn


def _prepare_prediction_conn(conn):
    _ensure_prediction_columns(conn)
    conn.commit()
    return conn


def _ensure_table_column(conn, table_name, column_name, column_def):
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name in columns:
        return
    try:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def _normalize_competitor_accounts(conn):
    rows = conn.execute("SELECT id, nickname FROM competitor_accounts").fetchall()
    for row in rows:
        old_id = row["id"]
        old_name = row["nickname"]
        new_name = canonicalize_competitor_name(old_name)
        if old_name != new_name:
            existing = conn.execute(
                "SELECT id FROM competitor_accounts WHERE nickname = ?",
                (new_name,),
            ).fetchone()
            if existing and existing["id"] != old_id:
                _merge_competitor_accounts(conn, old_id, existing["id"])
            else:
                conn.execute(
                    "UPDATE competitor_accounts SET nickname = ? WHERE id = ?",
                    (new_name, old_id),
                )

    for nickname in {"凌水球知道", "DUT星球", "NEU星球", "求是情报站"}:
        canonical = canonicalize_competitor_name(nickname)
        matrix_name = competitor_matrix_name(canonical)
        if matrix_name:
            conn.execute(
                "UPDATE competitor_accounts SET matrix_name = ? WHERE nickname = ?",
                (matrix_name, canonical),
            )
    _repair_placeholder_competitor_accounts(conn)


def _merge_competitor_accounts(conn, source_id: int, target_id: int):
    article_rows = conn.execute(
        "SELECT id FROM competitor_articles WHERE account_id = ?",
        (source_id,),
    ).fetchall()
    for row in article_rows:
        try:
            conn.execute(
                "UPDATE competitor_articles SET account_id = ? WHERE id = ?",
                (target_id, row["id"]),
            )
        except sqlite3.IntegrityError:
            conn.execute("DELETE FROM competitor_articles WHERE id = ?", (row["id"],))
    conn.execute("DELETE FROM competitor_accounts WHERE id = ?", (source_id,))


def _repair_placeholder_competitor_accounts(conn):
    placeholder_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM competitor_accounts WHERE nickname IN ({})".format(
                ", ".join("?" for _ in PLACEHOLDER_NICKNAMES)
            ),
            tuple(sorted(PLACEHOLDER_NICKNAMES)),
        ).fetchall()
    ]
    if not placeholder_ids:
        return

    target_by_key = _load_placeholder_article_targets()
    if not target_by_key:
        return

    for source_id in placeholder_ids:
        rows = conn.execute(
            "SELECT id, title, url FROM competitor_articles WHERE account_id = ?",
            (source_id,),
        ).fetchall()
        for row in rows:
            target_name = target_by_key.get(_competitor_article_key(row["title"], row["url"]))
            if not target_name:
                continue
            target_id = _get_or_create_competitor_account_row(conn, target_name)
            if target_id == source_id:
                continue
            try:
                conn.execute(
                    "UPDATE competitor_articles SET account_id = ? WHERE id = ?",
                    (target_id, row["id"]),
                )
            except sqlite3.IntegrityError:
                conn.execute("DELETE FROM competitor_articles WHERE id = ?", (row["id"],))

        remaining = conn.execute(
            "SELECT COUNT(*) FROM competitor_articles WHERE account_id = ?",
            (source_id,),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute("DELETE FROM competitor_accounts WHERE id = ?", (source_id,))


def _get_or_create_competitor_account_row(conn, nickname: str) -> int:
    canonical = canonicalize_competitor_name(nickname)
    matrix_name = competitor_matrix_name(canonical)
    row = conn.execute(
        "SELECT id FROM competitor_accounts WHERE nickname = ?",
        (canonical,),
    ).fetchone()
    if row:
        if matrix_name:
            conn.execute(
                "UPDATE competitor_accounts SET matrix_name = ? WHERE id = ?",
                (matrix_name, row["id"]),
            )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO competitor_accounts (nickname, matrix_name) VALUES (?, ?)",
        (canonical, matrix_name),
    )
    return cur.lastrowid


def _load_placeholder_article_targets() -> dict[str, str]:
    import_dir = Path(os.environ.get("COMPETITOR_IMPORT_DIR", str(Path(BASE_DIR) / "对标账号")))
    if not import_dir.exists():
        return {}

    target_by_key: dict[str, str] = {}
    for path in sorted(import_dir.glob("*.csv")):
        target_name = infer_nickname_from_source_names([path.name])
        if not target_name or target_name in PLACEHOLDER_NICKNAMES:
            continue
        try:
            reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))
        except OSError:
            continue
        if reader.fieldnames != EXPECTED_COLUMNS:
            continue
        for row in reader:
            nickname = (row.get("nickname") or "").strip()
            if nickname and nickname not in PLACEHOLDER_NICKNAMES:
                continue
            target_by_key[_competitor_article_key(row.get("title", ""), row.get("url", ""))] = target_name
    return target_by_key


def _competitor_article_key(title: str, url: str) -> str:
    url = (url or "").strip()
    if url:
        return url.replace("&amp;", "&")
    return f"title::{(title or '').strip()}"


def query_baseline_summary() -> dict:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        summary = conn.execute(
            """SELECT
                   COUNT(*) as article_count,
                   ROUND(AVG(total_reads), 0) as avg_reads,
                   MAX(total_reads) as max_reads,
                   MIN(total_reads) as min_reads,
                   ROUND(AVG(complete_rate), 3) as avg_complete_rate,
                   ROUND(AVG(comment_count), 1) as avg_comments,
                   ROUND(AVG(CAST(share_user AS REAL) / NULLIF(total_reads, 0)), 3) as avg_share_rate,
                   ROUND(AVG(CAST(msg_read_user AS REAL) / NULLIF(deliver_user, 0)), 3) as avg_open_rate,
                   ROUND(AVG(rec_ratio), 3) as avg_rec_ratio
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id"""
        ).fetchone()
        conn.close()
        return dict(summary)

    conn = get_conn()
    summary = conn.execute("""
        SELECT
            COUNT(*) as article_count,
            ROUND(AVG(read_user)) as avg_reads,
            MAX(read_user) as max_reads,
            MIN(read_user) as min_reads,
            ROUND(AVG(complete_rate), 3) as avg_complete_rate,
            ROUND(AVG(comment_count), 1) as avg_comments,
            ROUND(AVG(CAST(share_user AS REAL) / NULLIF(read_user, 0)), 3) as avg_share_rate,
            ROUND(AVG(CAST(msg_read_user AS REAL) / NULLIF(deliver_user, 0)), 3) as avg_open_rate
        FROM article_detail
    """).fetchone()
    rec = conn.execute("""
        SELECT ROUND(AVG(CAST(r.read_user AS REAL) / NULLIF(d.read_user, 0)), 3) as avg_rec_ratio
        FROM article_detail d
        JOIN article_source_stats r ON d.title = r.title AND r.channel = '推荐'
        WHERE d.read_user > 0
    """).fetchone()
    conn.close()
    result = dict(summary)
    result['avg_rec_ratio'] = rec['avg_rec_ratio'] if rec else None
    return result


def query_articles_performance() -> list:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT
                   m.canonical_title AS title,
                   m.publish_date,
                   strftime('%w', m.publish_date) as weekday,
                   m.total_reads as read_user,
                   ROUND(d.complete_rate, 3) as complete_rate,
                   m.comment_count,
                   m.share_user,
                   m.deliver_user,
                   m.msg_read_user,
                   ROUND(CAST(m.msg_read_user AS REAL) / NULLIF(m.deliver_user, 0), 3) as open_rate,
                   ROUND(d.rec_ratio, 3) as rec_ratio,
                   d.rec_reads as rec_reads
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               ORDER BY m.total_reads DESC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    rows = conn.execute("""
        SELECT
            d.title,
            s.publish_date,
            strftime('%w', s.publish_date) as weekday,
            d.read_user,
            ROUND(d.complete_rate, 3) as complete_rate,
            d.comment_count,
            d.share_user,
            d.deliver_user,
            d.msg_read_user,
            ROUND(CAST(d.msg_read_user AS REAL) / NULLIF(d.deliver_user, 0), 3) as open_rate,
            ROUND(CAST(r.read_user AS REAL) / NULLIF(d.read_user, 0), 3) as rec_ratio,
            r.read_user as rec_reads
        FROM article_detail d
        LEFT JOIN article_source_stats s ON d.title = s.title AND s.channel = '全部'
        LEFT JOIN article_source_stats r ON d.title = r.title AND r.channel = '推荐'
        ORDER BY d.read_user DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_weekday_performance() -> list:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT
                   strftime('%w', publish_date) as weekday,
                   ROUND(AVG(total_reads), 0) as avg_reads,
                   ROUND(AVG(complete_rate), 3) as avg_complete_rate,
                   COUNT(*) as count
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               WHERE publish_date IS NOT NULL AND publish_date != ''
               GROUP BY weekday
               ORDER BY weekday"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    rows = conn.execute("""
        SELECT
            strftime('%w', s.publish_date) as weekday,
            ROUND(AVG(d.read_user)) as avg_reads,
            ROUND(AVG(d.complete_rate), 3) as avg_complete_rate,
            COUNT(*) as count
        FROM article_detail d
        JOIN article_source_stats s ON d.title = s.title AND s.channel = '全部'
        GROUP BY weekday
        ORDER BY weekday
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_prediction(data: dict) -> int:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_prediction_conn(get_master_conn())
        cur = conn.execute(
            """INSERT INTO article_predictions
               (title, created_at, a_score, b_score, c_score, d_score, e_score, f_score, g_score,
                total_score, path_type, pred_reads, pred_rec_pct, pred_read_rate, pred_comments, notes)
               VALUES (:title, :created_at, :a_score, :b_score, :c_score, :d_score, :e_score, :f_score, :g_score,
                       :total_score, :path_type, :pred_reads, :pred_rec_pct, :pred_read_rate, :pred_comments, :notes)""",
            {
                "title": data.get("title", ""),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "a_score": data.get("a_score"),
                "b_score": data.get("b_score"),
                "c_score": data.get("c_score"),
                "d_score": data.get("d_score"),
                "e_score": data.get("e_score"),
                "f_score": data.get("f_score"),
                "g_score": data.get("g_score"),
                "total_score": data.get("total_score"),
                "path_type": data.get("path_type", ""),
                "pred_reads": data.get("pred_reads", ""),
                "pred_rec_pct": data.get("pred_rec_pct", ""),
                "pred_read_rate": data.get("pred_read_rate", ""),
                "pred_comments": data.get("pred_comments", ""),
                "notes": data.get("notes", ""),
            },
        )
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id

    conn = _prepare_prediction_conn(get_conn())
    cur = conn.execute(
        """INSERT INTO article_predictions
           (title, created_at, a_score, b_score, c_score, d_score, e_score, f_score, g_score,
            total_score, path_type, pred_reads, pred_rec_pct, pred_read_rate, pred_comments, notes)
           VALUES (:title, :created_at, :a_score, :b_score, :c_score, :d_score, :e_score, :f_score, :g_score,
                   :total_score, :path_type, :pred_reads, :pred_rec_pct, :pred_read_rate, :pred_comments, :notes)""",
        {
            "title": data.get("title", ""),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "a_score": data.get("a_score"),
            "b_score": data.get("b_score"),
            "c_score": data.get("c_score"),
            "d_score": data.get("d_score"),
            "e_score": data.get("e_score"),
            "f_score": data.get("f_score"),
            "g_score": data.get("g_score"),
            "total_score": data.get("total_score"),
            "path_type": data.get("path_type", ""),
            "pred_reads": data.get("pred_reads", ""),
            "pred_rec_pct": data.get("pred_rec_pct", ""),
            "pred_read_rate": data.get("pred_read_rate", ""),
            "pred_comments": data.get("pred_comments", ""),
            "notes": data.get("notes", ""),
        },
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_predictions(limit: int = 50) -> list:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_prediction_conn(get_master_conn())
        rows = conn.execute(
            "SELECT * FROM article_predictions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = _prepare_prediction_conn(get_conn())
    rows = conn.execute(
        "SELECT * FROM article_predictions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_prediction_actuals(pred_id: int, actuals: dict) -> bool:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_prediction_conn(get_master_conn())
        cur = conn.execute(
            """UPDATE article_predictions
               SET actual_reads = :actual_reads,
                   actual_rec_pct = :actual_rec_pct,
                   actual_read_rate = :actual_read_rate,
                   actual_comments = :actual_comments
               WHERE id = :id""",
            {
                "id": pred_id,
                "actual_reads": actuals.get("actual_reads"),
                "actual_rec_pct": actuals.get("actual_rec_pct"),
                "actual_read_rate": actuals.get("actual_read_rate"),
                "actual_comments": actuals.get("actual_comments"),
            },
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0

    conn = _prepare_prediction_conn(get_conn())
    cur = conn.execute(
        """UPDATE article_predictions
           SET actual_reads = :actual_reads,
               actual_rec_pct = :actual_rec_pct,
               actual_read_rate = :actual_read_rate,
               actual_comments = :actual_comments
           WHERE id = :id""",
        {
            "id": pred_id,
            "actual_reads": actuals.get("actual_reads"),
            "actual_rec_pct": actuals.get("actual_rec_pct"),
            "actual_read_rate": actuals.get("actual_read_rate"),
            "actual_comments": actuals.get("actual_comments"),
        },
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_or_create_competitor(nickname: str) -> int:
    nickname = canonicalize_competitor_name(nickname)
    matrix_name = competitor_matrix_name(nickname)
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        row = conn.execute(
            "SELECT id FROM competitor_accounts WHERE nickname = ?", (nickname,)
        ).fetchone()
        if row:
            if matrix_name:
                conn.execute(
                    "UPDATE competitor_accounts SET matrix_name = ? WHERE id = ?",
                    (matrix_name, row["id"]),
                )
                conn.commit()
            conn.close()
            return row["id"]
        cur = conn.execute(
            "INSERT INTO competitor_accounts (nickname, matrix_name) VALUES (?, ?)",
            (nickname, matrix_name),
        )
        account_id = cur.lastrowid
        conn.commit()
        conn.close()
        return account_id

    conn = _prepare_competitor_conn(get_conn())
    row = conn.execute(
        "SELECT id FROM competitor_accounts WHERE nickname = ?", (nickname,)
    ).fetchone()
    if row:
        if matrix_name:
            conn.execute(
                "UPDATE competitor_accounts SET matrix_name = ? WHERE id = ?",
                (matrix_name, row["id"]),
            )
            conn.commit()
        conn.close()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO competitor_accounts (nickname, matrix_name) VALUES (?, ?)",
        (nickname, matrix_name),
    )
    account_id = cur.lastrowid
    conn.commit()
    conn.close()
    return account_id


def import_competitor_articles(account_id: int, articles: list) -> dict:
    """articles: list of dicts with keys matching CSV columns."""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        inserted = skipped = 0
        for a in articles:
            try:
                conn.execute(
                    """INSERT INTO competitor_articles
                       (account_id, title, url, publish_time, like_num, read_num, share_num, comment_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (account_id, a["title"], a.get("url"), a.get("publish_time"),
                     a.get("like_num", 0), a.get("read_num", 0),
                     a.get("share_num", 0), a.get("comment_count", 0)),
                )
                inserted += 1
            except Exception:
                skipped += 1
        conn.commit()
        conn.close()
        return {"inserted": inserted, "skipped": skipped}

    conn = _prepare_competitor_conn(get_conn())
    inserted = skipped = 0
    for a in articles:
        try:
            conn.execute(
                """INSERT INTO competitor_articles
                   (account_id, title, url, publish_time, like_num, read_num, share_num, comment_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, a["title"], a.get("url"), a.get("publish_time"),
                 a.get("like_num", 0), a.get("read_num", 0),
                 a.get("share_num", 0), a.get("comment_count", 0)),
            )
            inserted += 1
        except Exception:
            skipped += 1
    conn.commit()
    conn.close()
    return {"inserted": inserted, "skipped": skipped}


def get_competitor_accounts(matrix_name: str | None = None) -> list:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        sql = """
            SELECT a.id, a.nickname, a.matrix_name, a.created_at,
                   COUNT(ar.id) as article_count,
                   MAX(ar.read_num) as max_reads,
                   ROUND(AVG(ar.read_num)) as avg_reads
            FROM competitor_accounts a
            LEFT JOIN competitor_articles ar ON a.id = ar.account_id
        """
        params = ()
        if matrix_name:
            sql += " WHERE a.matrix_name = ?"
            params = (matrix_name,)
        sql += " GROUP BY a.id ORDER BY COALESCE(a.matrix_name, ''), a.nickname"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = _prepare_competitor_conn(get_conn())
    sql = """
        SELECT a.id, a.nickname, a.matrix_name, a.created_at,
               COUNT(ar.id) as article_count,
               MAX(ar.read_num) as max_reads,
               ROUND(AVG(ar.read_num)) as avg_reads
        FROM competitor_accounts a
        LEFT JOIN competitor_articles ar ON a.id = ar.account_id
    """
    params = ()
    if matrix_name:
        sql += " WHERE a.matrix_name = ?"
        params = (matrix_name,)
    sql += " GROUP BY a.id ORDER BY COALESCE(a.matrix_name, ''), a.nickname"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_competitor_articles(account_id: int) -> list:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        rows = conn.execute(
            """SELECT * FROM competitor_articles
               WHERE account_id = ? ORDER BY read_num DESC""",
            (account_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = _prepare_competitor_conn(get_conn())
    rows = conn.execute(
        """SELECT * FROM competitor_articles
           WHERE account_id = ? ORDER BY read_num DESC""",
        (account_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_viral_analysis(article_id: int, analysis_json: str) -> None:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        conn.execute(
            "UPDATE competitor_articles SET viral_analysis = ? WHERE id = ?",
            (analysis_json, article_id),
        )
        conn.commit()
        conn.close()
        return

    conn = _prepare_competitor_conn(get_conn())
    conn.execute(
        "UPDATE competitor_articles SET viral_analysis = ? WHERE id = ?",
        (analysis_json, article_id),
    )
    conn.commit()
    conn.close()


def save_article_content(article_id: int, content: str) -> None:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        conn.execute(
            "UPDATE competitor_articles SET content_text = ? WHERE id = ?",
            (content, article_id),
        )
        conn.commit()
        conn.close()
        return

    conn = _prepare_competitor_conn(get_conn())
    conn.execute(
        "UPDATE competitor_articles SET content_text = ? WHERE id = ?",
        (content, article_id),
    )
    conn.commit()
    conn.close()


def save_competitor_manual_analysis(article_id: int, status: str, summary: str, notes: str) -> None:
    params = (
        status or "pending",
        summary or "",
        notes or "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        article_id,
    )
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        conn.execute(
            """UPDATE competitor_articles
               SET manual_analysis_status = ?,
                   manual_analysis_summary = ?,
                   manual_analysis_notes = ?,
                   manual_analysis_updated_at = ?
               WHERE id = ?""",
            params,
        )
        conn.commit()
        conn.close()
        return

    conn = _prepare_competitor_conn(get_conn())
    conn.execute(
        """UPDATE competitor_articles
           SET manual_analysis_status = ?,
               manual_analysis_summary = ?,
               manual_analysis_notes = ?,
               manual_analysis_updated_at = ?
           WHERE id = ?""",
        params,
    )
    conn.commit()
    conn.close()


def get_competitor_article(article_id: int) -> dict | None:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        row = conn.execute(
            "SELECT * FROM competitor_articles WHERE id = ?",
            (article_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    conn = _prepare_competitor_conn(get_conn())
    row = conn.execute(
        "SELECT * FROM competitor_articles WHERE id = ?",
        (article_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def query_pending_competitor_content() -> list[dict]:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = _prepare_competitor_conn(get_master_conn())
        rows = conn.execute("""
            SELECT id, title, url FROM competitor_articles
            WHERE viral_analysis IS NOT NULL
              AND (content_text IS NULL OR content_text = '')
              AND url != ''
            ORDER BY read_num DESC
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = _prepare_competitor_conn(get_conn())
    rows = conn.execute("""
        SELECT id, title, url FROM competitor_articles
        WHERE viral_analysis IS NOT NULL
          AND (content_text IS NULL OR content_text = '')
          AND url != ''
        ORDER BY read_num DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_import_record(filename):
    """返回已有导入记录，无则返回 None"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        row = conn.execute(
            "SELECT * FROM import_history WHERE filename = ?", (filename,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    if not _legacy_table_exists("import_history"):
        return None

    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM import_history WHERE filename = ?", (filename,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def record_import(filename, date_range, rows_imported):
    """记录或更新导入历史（同名文件允许重新导入以更新数据）"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        conn.execute(
            """INSERT INTO import_history (filename, date_range, rows_imported, imported_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(filename) DO UPDATE SET
                   date_range=excluded.date_range,
                   rows_imported=excluded.rows_imported,
                   imported_at=excluded.imported_at""",
            (filename, date_range, rows_imported),
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.execute(
        """INSERT INTO import_history (filename, date_range, rows_imported, imported_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(filename) DO UPDATE SET
               rows_imported = excluded.rows_imported,
               imported_at   = excluded.imported_at""",
        (filename, date_range, rows_imported),
    )
    conn.commit()
    conn.close()


def upsert_daily_reads(records):
    """records: list of {stat_date, channel, read_user}"""
    conn = get_conn()
    conn.executemany(
        """INSERT INTO daily_reads (stat_date, channel, read_user)
           VALUES (:stat_date, :channel, :read_user)
           ON CONFLICT(stat_date, channel) DO UPDATE SET
               read_user = excluded.read_user""",
        records,
    )
    conn.commit()
    conn.close()


def upsert_daily_stats(records):
    """records: list of {stat_date, share_user, original_read_user, fav_user, article_count}"""
    conn = get_conn()
    conn.executemany(
        """INSERT INTO daily_stats (stat_date, share_user, original_read_user, fav_user, article_count)
           VALUES (:stat_date, :share_user, :original_read_user, :fav_user, :article_count)
           ON CONFLICT(stat_date) DO UPDATE SET
               share_user = excluded.share_user,
               original_read_user = excluded.original_read_user,
               fav_user = excluded.fav_user,
               article_count = excluded.article_count""",
        records,
    )
    conn.commit()
    conn.close()


def upsert_article_source_stats(records):
    """records: list of {publish_date, title, channel, read_user, read_ratio, import_file}"""
    conn = get_conn()
    conn.executemany(
        """INSERT INTO article_source_stats (publish_date, title, channel, read_user, read_ratio, import_file)
           VALUES (:publish_date, :title, :channel, :read_user, :read_ratio, :import_file)
           ON CONFLICT(publish_date, title, channel) DO UPDATE SET
               read_user = excluded.read_user,
               read_ratio = excluded.read_ratio""",
        records,
    )
    conn.commit()
    conn.close()


# ── Query helpers ──────────────────────────────────────────────────────────────

def query_daily_reads(days=30, start_date=None, end_date=None):
    """每日各渠道阅读人数，支持固定天数或自定义日期范围。"""
    if _master_ready():
        from core.master_db import query_account_channel_daily
        return query_account_channel_daily(days=days, start_date=start_date, end_date=end_date)

    conn = get_conn()
    if start_date and end_date:
        rows = conn.execute(
            """SELECT stat_date, channel, read_user FROM daily_reads
               WHERE stat_date >= ? AND stat_date <= ?
               ORDER BY stat_date, channel""",
            (start_date, end_date),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT stat_date, channel, read_user FROM daily_reads
               WHERE stat_date >= date('now', ?)
               ORDER BY stat_date, channel""",
            (f"-{days} days",),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_daily_stats(days=30, start_date=None, end_date=None):
    if _master_ready():
        from core.master_db import query_account_daily_metrics
        rows = query_account_daily_metrics(limit=max(days, 120))
        if start_date and end_date:
            rows = [r for r in rows if start_date <= (r["stat_date"] or "") <= end_date]
        elif days and len(rows) > days:
            rows = rows[:days]
        rows.sort(key=lambda r: r.get("stat_date") or "")
        return rows

    conn = get_conn()
    if start_date and end_date:
        rows = conn.execute(
            "SELECT * FROM daily_stats WHERE stat_date >= ? AND stat_date <= ? ORDER BY stat_date",
            (start_date, end_date),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM daily_stats WHERE stat_date >= date('now', ?) ORDER BY stat_date",
            (f"-{days} days",),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_article_ranking():
    """
    文章排行：合并 article_source_stats（渠道分布）和 article_detail（互动指标）。
    以文章标题为 JOIN key（两表共有字段）。
    每条记录附带 stale 字段：若文章 publish_date 早于最新 tendency 文件的覆盖起点，
    说明该篇阅读数未被最新文件更新，stale=True。
    """
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT
                   m.id,
                   m.publish_date,
                   m.canonical_title AS title,
                   m.total_reads,
                   m.share_user,
                   m.like_user,
                   m.thumbup_user,
                   m.fav_user,
                   m.comment_count,
                   m.follow_after_read,
                   d.avg_read_time,
                   d.complete_rate,
                   d.rec_reads,
                   d.rec_ratio
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               ORDER BY m.total_reads DESC, m.publish_date DESC"""
        ).fetchall()
        source_rows = conn.execute(
            """SELECT article_id, channel, read_user
               FROM traffic_source_stats
               WHERE article_id IS NOT NULL
               ORDER BY article_id, read_user DESC"""
        ).fetchall()
        conn.close()

        channels_by_article = {}
        for row in source_rows:
            channels_by_article.setdefault(row["article_id"], []).append(
                {"channel": row["channel"], "count": row["read_user"], "pct": None}
            )

        result = []
        for row in rows:
            total = row["total_reads"] or 0
            channels = channels_by_article.get(row["id"], [])
            normalized_channels = []
            for ch in channels:
                pct = round((ch["count"] or 0) / total * 100, 1) if total else 0
                normalized_channels.append({**ch, "pct": pct})
            rec_pct = round((row["rec_ratio"] or 0) * 100, 1) if row["rec_ratio"] is not None else 0.0
            result.append({
                "publish_date": _normalize_date_text(row["publish_date"]),
                "title": row["title"],
                "total_reads": total,
                "rec_pct": rec_pct,
                "channels": normalized_channels,
                "stale": False,
                "stale_since": None,
                "avg_read_time": row["avg_read_time"],
                "complete_rate": round((row["complete_rate"] or 0) * 100, 1) if row["complete_rate"] is not None else None,
                "share_user": row["share_user"],
                "like_user": row["like_user"],
                "thumbup_user": row["thumbup_user"],
                "fav_user": row["fav_user"],
                "comment_count": row["comment_count"],
                "follow_after_read": row["follow_after_read"],
            })
        return result

    conn = get_conn()

    # 渠道明细
    src_rows = conn.execute(
        "SELECT publish_date, title, channel, read_user, import_file, created_at FROM article_source_stats ORDER BY title, channel"
    ).fetchall()

    # 单篇详情（互动指标）- 按标题 JOIN，含 created_at 用于时间戳比较
    detail_rows = conn.execute(
        """SELECT title, read_user AS d_read, avg_read_time, complete_rate,
                  follow_after_read, share_user, like_user, thumbup_user,
                  fav_user, reward, comment_count, deliver_user, created_at AS d_created_at
           FROM article_detail"""
    ).fetchall()

    # 最新 tendency 文件及其覆盖的最早发布日期
    # tendency 文件覆盖范围 = 该文件里 publish_date 的最小值
    latest_tendency = conn.execute(
        """SELECT import_file, MIN(publish_date) AS min_date
           FROM article_source_stats
           WHERE import_file LIKE 'tendency_%' AND channel = '全部'
           GROUP BY import_file
           ORDER BY import_file DESC
           LIMIT 1"""
    ).fetchone()
    conn.close()

    # 最新 tendency 文件覆盖的最早日期；若无则不标记
    latest_tendency_file = latest_tendency["import_file"] if latest_tendency else None
    latest_min_date = latest_tendency["min_date"] if latest_tendency else None

    detail_map = {r["title"]: dict(r) for r in detail_rows}

    from collections import defaultdict
    articles = defaultdict(lambda: {"total_reads": 0, "channels": {}, "import_file": None, "src_created_at": None})
    for r in src_rows:
        key = (r["publish_date"], r["title"])
        if r["channel"] == "全部":
            articles[key]["total_reads"] = r["read_user"]
            articles[key]["publish_date"] = r["publish_date"]
            articles[key]["title"] = r["title"]
            articles[key]["import_file"] = r["import_file"]
            articles[key]["src_created_at"] = r["created_at"]
        else:
            articles[key]["channels"][r["channel"]] = r["read_user"]
            articles[key].setdefault("publish_date", r["publish_date"])
            articles[key].setdefault("title", r["title"])

    result = []
    for key, art in articles.items():
        total = art["total_reads"]
        title = art.get("title", key[1])
        pub_date = art.get("publish_date", key[0])

        # 没有"全部"汇总行时，用各渠道累加作为 total_reads 的兜底
        if not total and art["channels"]:
            total = sum(art["channels"].values())

        channels_with_pct = []
        for ch, cnt in sorted(art["channels"].items(), key=lambda x: -x[1]):
            pct = round(cnt / total * 100, 1) if total else 0
            channels_with_pct.append({"channel": ch, "count": cnt, "pct": pct})

        rec_ch = next((c for c in channels_with_pct if c["channel"] == "推荐"), None)
        rec_pct = rec_ch["pct"] if rec_ch else 0.0

        # stale：文章不在最新 tendency 文件里（publish_date 早于其覆盖起点）
        import_file = art.get("import_file")
        stale = bool(
            latest_tendency_file
            and latest_min_date
            and import_file != latest_tendency_file
            and pub_date < latest_min_date
        )

        # 合并互动指标
        d = detail_map.get(title, {})

        # total_reads 取时间戳更晚的来源：
        # 若 article_detail 的 created_at 晚于 article_source_stats，则用 detail 的 read_user
        src_ts = art.get("src_created_at") or ""
        det_ts = d.get("d_created_at") or ""
        if d.get("d_read") is not None and det_ts > src_ts:
            total = d["d_read"]
            stale = False  # detail 数据更新，不再标记为旧

        result.append({
            "publish_date":     pub_date,
            "title":            title,
            "total_reads":      total,
            "rec_pct":          rec_pct,
            "channels":         channels_with_pct,
            "stale":            stale,
            "stale_since":      latest_min_date if stale else None,
            # 互动指标（无数据时为 None）
            "avg_read_time":    d.get("avg_read_time"),
            "complete_rate":    round(d["complete_rate"] * 100, 1) if d.get("complete_rate") else None,
            "share_user":       d.get("share_user"),
            "like_user":        d.get("like_user"),
            "thumbup_user":     d.get("thumbup_user"),
            "fav_user":         d.get("fav_user"),
            "comment_count":    d.get("comment_count"),
            "follow_after_read": d.get("follow_after_read"),
        })

    result.sort(key=lambda x: -(x["total_reads"] or 0))
    return result


def upsert_daily_user_stats(records):
    conn = get_conn()
    conn.executemany(
        """INSERT INTO daily_user_stats (stat_date, new_user, cancel_user, net_user, total_user)
           VALUES (:stat_date, :new_user, :cancel_user, :net_user, :total_user)
           ON CONFLICT(stat_date) DO UPDATE SET
               new_user=excluded.new_user, cancel_user=excluded.cancel_user,
               net_user=excluded.net_user, total_user=excluded.total_user""",
        records,
    )
    conn.commit(); conn.close()


def upsert_daily_msg_stats(records):
    conn = get_conn()
    conn.executemany(
        """INSERT INTO daily_msg_stats (stat_date, msg_user, msg_count, avg_msg)
           VALUES (:stat_date, :msg_user, :msg_count, :avg_msg)
           ON CONFLICT(stat_date) DO UPDATE SET
               msg_user=excluded.msg_user, msg_count=excluded.msg_count, avg_msg=excluded.avg_msg""",
        records,
    )
    conn.commit(); conn.close()


def sync_article_reads():
    """
    跨表同步阅读数：对 article_source_stats 和 article_detail 中同名文章，
    以 created_at 更晚的表为准，将 read_user 写回另一张表。
    返回 {updated_source: n, updated_detail: n}。
    """
    if _master_ready():
        return {"updated_source": 0, "updated_detail": 0}

    conn = get_conn()

    # 取两张表中共有文章的阅读数和时间戳
    rows = conn.execute(
        """SELECT
               s.title,
               s.read_user  AS s_read,
               s.created_at AS s_ts,
               d.read_user  AS d_read,
               d.created_at AS d_ts
           FROM article_source_stats s
           JOIN article_detail d ON s.title = d.title
           WHERE s.channel = '全部'"""
    ).fetchall()

    updated_source = 0
    updated_detail = 0

    for r in rows:
        s_ts = r["s_ts"] or ""
        d_ts = r["d_ts"] or ""
        if s_ts == d_ts or r["s_read"] == r["d_read"]:
            continue
        if d_ts > s_ts:
            # detail 更新 → 把 detail 的 read_user 写回 source_stats
            # 但不用 0 覆盖有效数据
            if not r["d_read"] and r["s_read"]:
                continue
            conn.execute(
                "UPDATE article_source_stats SET read_user=? WHERE title=? AND channel='全部'",
                (r["d_read"], r["title"]),
            )
            updated_source += 1
        else:
            # source_stats 更新 → 把 source_stats 的 read_user 写回 detail
            # 但不用 0 覆盖有效数据
            if not r["s_read"] and r["d_read"]:
                continue
            conn.execute(
                "UPDATE article_detail SET read_user=? WHERE title=?",
                (r["s_read"], r["title"]),
            )
            updated_detail += 1

    conn.commit()
    conn.close()
    return {"updated_source": updated_source, "updated_detail": updated_detail}


def update_article_reads(title, read_user):
    """手动修改某篇文章的阅读数，同步写入两张表（均以当前时间更新 created_at）。"""
    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        conn = get_master_conn()
        normalized_title = normalize_title(title)
        article = conn.execute(
            "SELECT id FROM article_master WHERE normalized_title=? LIMIT 1",
            (normalized_title,),
        ).fetchone()
        if not article:
            conn.close()
            return
        conn.execute(
            """UPDATE article_master
               SET total_reads=?, is_overridden=1, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (read_user, article["id"]),
        )
        conn.execute(
            """INSERT INTO article_overrides (article_id, field_name, override_value, reason, updated_at)
               VALUES (?, 'total_reads', ?, 'legacy edit', CURRENT_TIMESTAMP)
               ON CONFLICT(article_id, field_name) DO UPDATE SET
                   override_value=excluded.override_value,
                   reason=excluded.reason,
                   updated_at=CURRENT_TIMESTAMP""",
            (article["id"], str(read_user)),
        )
        conn.execute(
            """UPDATE traffic_source_stats
               SET read_user=?, updated_at=CURRENT_TIMESTAMP
               WHERE article_id=? AND channel='全部'""",
            (read_user, article["id"]),
        )
        rec_row = conn.execute(
            "SELECT rec_reads FROM article_diagnostics WHERE article_id=?",
            (article["id"],),
        ).fetchone()
        rec_reads = rec_row["rec_reads"] if rec_row else 0
        rec_ratio = round(rec_reads / read_user, 4) if read_user and rec_reads else None
        conn.execute(
            """INSERT INTO article_diagnostics(article_id, rec_reads, rec_ratio, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(article_id) DO UPDATE SET
                   rec_ratio=excluded.rec_ratio,
                   updated_at=CURRENT_TIMESTAMP""",
            (article["id"], rec_reads, rec_ratio),
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE article_source_stats SET read_user=?, created_at=? WHERE title=? AND channel='全部'",
        (read_user, now, title),
    )
    conn.execute(
        "UPDATE article_detail SET read_user=?, created_at=? WHERE title=?",
        (read_user, now, title),
    )
    conn.commit()
    conn.close()


# 可手动编辑的字段白名单：field_name → (table, column, type)
# complete_rate 在 DB 里存 0~1 小数，前端显示/输入百分比，需转换
_EDITABLE_FIELDS = {
    "total_reads":   ("both",           "read_user",      "int"),
    "publish_date":  ("source_stats",   "publish_date",   "str"),
    "rec_pct":       ("source_stats",   "rec_pct",        "rec_pct"),  # 特殊处理
    "share_user":    ("article_detail", "share_user",     "int"),
    "like_user":     ("article_detail", "like_user",      "int"),
    "fav_user":      ("article_detail", "fav_user",       "int"),
    "avg_read_time": ("article_detail", "avg_read_time",  "int"),
    "complete_rate": ("article_detail", "complete_rate",  "pct"),   # 前端 % → DB 小数
    "comment_count": ("article_detail", "comment_count",  "int"),
    "follow_after_read": ("article_detail", "follow_after_read", "int"),
}


def update_article_field(title, field, raw_value):
    """
    通用字段更新。raw_value 为前端传入的原始值（字符串）。
    返回 (ok, error_msg)。
    """
    if field not in _EDITABLE_FIELDS:
        return False, f"字段 {field} 不可编辑"

    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        normalized_title = normalize_title(title)
        conn = get_master_conn()
        article = conn.execute(
            """SELECT m.id, m.total_reads, d.rec_reads
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               WHERE m.normalized_title=?
               LIMIT 1""",
            (normalized_title,),
        ).fetchone()
        if not article:
            conn.close()
            return False, "文章不存在"

        def save_override(field_name, value, reason="legacy edit"):
            conn.execute(
                """INSERT INTO article_overrides (article_id, field_name, override_value, reason, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(article_id, field_name) DO UPDATE SET
                       override_value=excluded.override_value,
                       reason=excluded.reason,
                       updated_at=CURRENT_TIMESTAMP""",
                (article["id"], field_name, str(value), reason),
            )
            conn.execute(
                "UPDATE article_master SET is_overridden=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (article["id"],),
            )

        try:
            if field == "publish_date":
                value = _normalize_date_text(str(raw_value).strip())
                if not value:
                    conn.close()
                    return False, "值不能为空"
                conn.execute(
                    "UPDATE article_master SET publish_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (value, article["id"]),
                )
                conn.execute(
                    "UPDATE traffic_source_stats SET publish_date=?, updated_at=CURRENT_TIMESTAMP WHERE article_id=?",
                    (value, article["id"]),
                )
                save_override("publish_date", value)
            elif field == "rec_pct":
                pct = float(raw_value)
                if not 0 <= pct <= 100:
                    conn.close()
                    return False, "推荐占比须在 0~100 之间"
                total = int(article["total_reads"] or 0)
                rec_reads = round(total * pct / 100)
                rec_ratio = round(rec_reads / total, 4) if total else None
                conn.execute(
                    """INSERT INTO article_diagnostics (article_id, rec_reads, rec_ratio, updated_at)
                       VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(article_id) DO UPDATE SET
                           rec_reads=excluded.rec_reads,
                           rec_ratio=excluded.rec_ratio,
                           updated_at=CURRENT_TIMESTAMP""",
                    (article["id"], rec_reads, rec_ratio),
                )
                source_row = conn.execute(
                    "SELECT publish_date FROM article_master WHERE id=?",
                    (article["id"],),
                ).fetchone()
                conn.execute(
                    """INSERT INTO traffic_source_stats
                       (article_id, publish_date, title, normalized_title, channel, read_user, read_ratio, updated_at)
                       VALUES (?, ?, ?, ?, '推荐', ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(publish_date, normalized_title, channel) DO UPDATE SET
                           article_id=excluded.article_id,
                           title=excluded.title,
                           read_user=excluded.read_user,
                           read_ratio=excluded.read_ratio,
                           updated_at=CURRENT_TIMESTAMP""",
                    (
                        article["id"],
                        source_row["publish_date"] if source_row else None,
                        title,
                        normalized_title,
                        rec_reads,
                        rec_ratio,
                    ),
                )
                save_override("rec_ratio", rec_ratio)
                save_override("rec_reads", rec_reads)
            else:
                table, column, vtype = _EDITABLE_FIELDS[field]
                if vtype == "int":
                    value = int(raw_value)
                    if value < 0:
                        conn.close()
                        return False, "数值不能为负"
                elif vtype == "pct":
                    pct = float(raw_value)
                    if not 0 <= pct <= 100:
                        conn.close()
                        return False, "完读率须在 0~100 之间"
                    value = round(pct / 100, 6)
                else:
                    value = str(raw_value).strip()
                    if not value:
                        conn.close()
                        return False, "值不能为空"

                if field == "total_reads":
                    conn.execute(
                        "UPDATE article_master SET total_reads=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (value, article["id"]),
                    )
                    conn.execute(
                        """UPDATE traffic_source_stats
                           SET read_user=?, updated_at=CURRENT_TIMESTAMP
                           WHERE article_id=? AND channel='全部'""",
                        (value, article["id"]),
                    )
                elif table == "article_detail":
                    target_column = {
                        "share_user": "share_user",
                        "like_user": "like_user",
                        "fav_user": "fav_user",
                        "comment_count": "comment_count",
                        "follow_after_read": "follow_after_read",
                    }.get(field)
                    if target_column:
                        conn.execute(
                            f"UPDATE article_master SET {target_column}=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (value, article["id"]),
                        )
                    else:
                        conn.execute(
                            f"""INSERT INTO article_diagnostics (article_id, {field}, updated_at)
                                VALUES (?, ?, CURRENT_TIMESTAMP)
                                ON CONFLICT(article_id) DO UPDATE SET
                                    {field}=excluded.{field},
                                    updated_at=CURRENT_TIMESTAMP""",
                            (article["id"], value),
                        )
                save_override(
                    field if field not in {"rec_pct"} else "rec_ratio",
                    value if field != "complete_rate" else value,
                )

            conn.commit()
            conn.close()
            return True, None
        except (ValueError, TypeError):
            conn.close()
            return False, "数值格式不正确"

    table, column, vtype = _EDITABLE_FIELDS[field]

    # rec_pct 特殊处理：根据新百分比反算"推荐"渠道 read_user，upsert 到 source_stats
    if vtype == "rec_pct":
        try:
            pct = float(raw_value)
            if not 0 <= pct <= 100:
                return False, "推荐占比须在 0~100 之间"
        except (ValueError, TypeError):
            return False, "数值格式不正确"
        conn = get_conn()
        total_row = conn.execute(
            "SELECT read_user FROM article_source_stats WHERE title=? AND channel='全部'",
            (title,),
        ).fetchone()
        total = total_row["read_user"] if total_row else 0
        rec_read = round(total * pct / 100)
        pub_row = conn.execute(
            "SELECT publish_date, import_file FROM article_source_stats WHERE title=? LIMIT 1",
            (title,),
        ).fetchone()
        pub_date = pub_row["publish_date"] if pub_row else ""
        imp_file = pub_row["import_file"] if pub_row else ""
        conn.execute(
            """INSERT INTO article_source_stats (publish_date, title, channel, read_user, import_file)
               VALUES (?, ?, '推荐', ?, ?)
               ON CONFLICT(publish_date, title, channel) DO UPDATE SET read_user=excluded.read_user""",
            (pub_date, title, rec_read, imp_file),
        )
        conn.commit()
        conn.close()
        return True, None

    # 类型转换
    try:
        if vtype == "int":
            value = int(raw_value)
            if value < 0:
                return False, "数值不能为负"
        elif vtype == "pct":
            pct = float(raw_value)
            if not 0 <= pct <= 100:
                return False, "完读率须在 0~100 之间"
            value = round(pct / 100, 6)
        else:
            value = str(raw_value).strip()
            if not value:
                return False, "值不能为空"
    except (ValueError, TypeError):
        return False, "数值格式不正确"

    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if table == "both":
        conn.execute(
            f"UPDATE article_source_stats SET {column}=?, created_at=? WHERE title=? AND channel='全部'",
            (value, now, title),
        )
        conn.execute(
            f"UPDATE article_detail SET {column}=?, created_at=? WHERE title=?",
            (value, now, title),
        )
    elif table == "source_stats":
        conn.execute(
            f"UPDATE article_source_stats SET {column}=? WHERE title=?",
            (value, title),
        )
    else:
        conn.execute(
            f"UPDATE article_detail SET {column}=?, created_at=? WHERE title=?",
            (value, now, title),
        )

    conn.commit()
    conn.close()
    return True, None


def upsert_menu_stats(records, import_date):
    conn = get_conn()
    for r in records:
        r["import_date"] = import_date
    conn.executemany(
        """INSERT INTO menu_stats (menu_version, menu_level1, menu_level2, click_count, click_user, avg_click, import_date)
           VALUES (:menu_version, :menu_level1, :menu_level2, :click_count, :click_user, :avg_click, :import_date)
           ON CONFLICT(menu_version, menu_level1, menu_level2) DO UPDATE SET
               click_count=excluded.click_count, click_user=excluded.click_user,
               avg_click=excluded.avg_click, import_date=excluded.import_date""",
        records,
    )
    conn.commit(); conn.close()


def upsert_article_detail(record):
    defaults = {
        "read_user": 0,
        "avg_read_time": 0,
        "complete_rate": 0,
        "follow_after_read": 0,
        "share_user": 0,
        "like_user": 0,
        "thumbup_user": 0,
        "fav_user": 0,
        "reward": 0,
        "comment_count": 0,
        "deliver_user": 0,
        "msg_read_user": 0,
        "first_share_user": 0,
        "total_share_user": 0,
        "share_read_user": 0,
        "import_file": "",
    }
    payload = {**defaults, **record}
    conn = get_conn()
    conn.execute(
        """INSERT INTO article_detail (title, read_user, avg_read_time, complete_rate,
               follow_after_read, share_user, like_user, thumbup_user, fav_user, reward,
               comment_count, deliver_user, msg_read_user, first_share_user,
               total_share_user, share_read_user, import_file)
           VALUES (:title, :read_user, :avg_read_time, :complete_rate,
               :follow_after_read, :share_user, :like_user, :thumbup_user, :fav_user, :reward,
               :comment_count, :deliver_user, :msg_read_user, :first_share_user,
               :total_share_user, :share_read_user, :import_file)
           ON CONFLICT(title) DO UPDATE SET
               read_user=excluded.read_user, avg_read_time=excluded.avg_read_time,
               complete_rate=excluded.complete_rate, follow_after_read=excluded.follow_after_read,
               share_user=excluded.share_user, like_user=excluded.like_user,
               thumbup_user=excluded.thumbup_user, fav_user=excluded.fav_user,
               reward=excluded.reward, comment_count=excluded.comment_count,
               deliver_user=excluded.deliver_user, msg_read_user=excluded.msg_read_user,
               first_share_user=excluded.first_share_user, total_share_user=excluded.total_share_user,
               share_read_user=excluded.share_read_user""",
        payload,
    )
    conn.commit(); conn.close()


def query_user_stats(days=60, start_date=None, end_date=None):
    if _master_ready():
        from core.master_db import query_account_user_daily
        rows = query_account_user_daily(limit=max(days, 365))
        if start_date and end_date:
            rows = [r for r in rows if start_date <= (r["stat_date"] or "") <= end_date]
        elif days and len(rows) > days:
            rows = rows[:days]
        rows.sort(key=lambda r: r.get("stat_date") or "")
        return rows

    conn = get_conn()
    if start_date and end_date:
        rows = conn.execute(
            "SELECT * FROM daily_user_stats WHERE stat_date >= ? AND stat_date <= ? ORDER BY stat_date",
            (start_date, end_date),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM daily_user_stats WHERE stat_date >= date('now',?) ORDER BY stat_date",
            (f"-{days} days",),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_msg_stats(days=60, start_date=None, end_date=None):
    if _master_ready():
        from core.master_db import query_account_message_stats_range
        return query_account_message_stats_range(days=days, start_date=start_date, end_date=end_date)

    conn = get_conn()
    if start_date and end_date:
        rows = conn.execute(
            "SELECT * FROM daily_msg_stats WHERE stat_date >= ? AND stat_date <= ? ORDER BY stat_date",
            (start_date, end_date),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM daily_msg_stats WHERE stat_date >= date('now',?) ORDER BY stat_date",
            (f"-{days} days",),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_article_details():
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT m.canonical_title AS title,
                      m.publish_date,
                      m.total_reads AS read_user,
                      d.avg_read_time,
                      ROUND(d.complete_rate * 100, 1) AS complete_rate,
                      m.share_user,
                      m.like_user,
                      m.thumbup_user,
                      m.fav_user,
                      m.comment_count,
                      m.follow_after_read,
                      m.deliver_user,
                      m.msg_read_user,
                      m.first_share_user,
                      m.total_share_user,
                      m.share_read_user
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               ORDER BY m.total_reads DESC"""
        ).fetchall()
        conn.close()
        result = []
        for row in rows:
            current = dict(row)
            current["publish_date"] = _normalize_date_text(current.get("publish_date"))
            result.append(current)
        return result

    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM article_detail ORDER BY read_user DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_article_detail_by_title(title: str) -> dict:
    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        conn = get_master_conn()
        row = conn.execute(
            """SELECT m.canonical_title AS title,
                      m.publish_date,
                      m.total_reads AS read_user,
                      d.avg_read_time,
                      ROUND(d.complete_rate * 100, 1) AS complete_rate,
                      m.share_user,
                      m.like_user,
                      m.thumbup_user,
                      m.fav_user,
                      m.comment_count,
                      m.follow_after_read,
                      m.deliver_user,
                      m.msg_read_user,
                      m.first_share_user,
                      m.total_share_user,
                      m.share_read_user
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               WHERE m.normalized_title=?
               LIMIT 1""",
            (normalize_title(title),),
        ).fetchone()
        conn.close()
        if not row:
            return {}
        result = dict(row)
        result["publish_date"] = _normalize_date_text(result.get("publish_date"))
        return result

    conn = get_conn()
    row = conn.execute("SELECT * FROM article_detail WHERE title=?", (title,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def query_summary():
    """总览指标"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        summary = conn.execute(
            """SELECT
                   COALESCE(SUM(total_read_user), 0) AS total_reads_30d,
                   COALESCE(SUM(article_count), 0) AS total_articles_30d,
                   COALESCE(AVG(share_user), 0) AS avg_share_30d
               FROM account_daily_metrics
               WHERE stat_date >= date('now', '-30 days')"""
        ).fetchone()
        net_user_30d = conn.execute(
            """SELECT COALESCE(SUM(net_user), 0)
               FROM account_user_daily
               WHERE stat_date >= date('now', '-30 days')"""
        ).fetchone()[0]
        latest_total_user = conn.execute(
            """SELECT total_user
               FROM account_user_daily
               WHERE total_user > 0
               ORDER BY stat_date DESC
               LIMIT 1"""
        ).fetchone()
        import_count = conn.execute("SELECT COUNT(*) FROM import_history").fetchone()[0]
        conn.close()
        return {
            "total_reads_30d": int(summary["total_reads_30d"] or 0),
            "total_articles_30d": int(summary["total_articles_30d"] or 0),
            "avg_share_30d": round(float(summary["avg_share_30d"] or 0), 1),
            "net_user_30d": int(net_user_30d or 0),
            "total_user": int(latest_total_user["total_user"]) if latest_total_user else None,
            "import_count": import_count,
        }

    conn = get_conn()
    total_reads = conn.execute(
        """SELECT SUM(read_user) FROM daily_reads
           WHERE channel='全部' AND stat_date >= date('now', '-30 days')"""
    ).fetchone()[0] or 0
    total_articles = conn.execute(
        "SELECT SUM(article_count) FROM daily_stats WHERE stat_date >= date('now', '-30 days')"
    ).fetchone()[0] or 0
    avg_share = conn.execute(
        "SELECT AVG(share_user) FROM daily_stats WHERE stat_date >= date('now', '-30 days')"
    ).fetchone()[0] or 0
    # 用户增减
    net_user_30d = conn.execute(
        "SELECT SUM(net_user) FROM daily_user_stats WHERE stat_date >= date('now', '-30 days')"
    ).fetchone()[0] or 0
    latest_total_user = conn.execute(
        "SELECT total_user FROM daily_user_stats WHERE total_user > 0 ORDER BY stat_date DESC LIMIT 1"
    ).fetchone()
    import_count = conn.execute("SELECT COUNT(*) FROM import_history").fetchone()[0]
    conn.close()
    return {
        "total_reads_30d": int(total_reads),
        "total_articles_30d": int(total_articles),
        "avg_share_30d": round(float(avg_share), 1),
        "net_user_30d": int(net_user_30d),
        "total_user": int(latest_total_user["total_user"]) if latest_total_user else None,
        "import_count": import_count,
    }


def query_import_history():
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            "SELECT * FROM import_history ORDER BY imported_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    if not _legacy_table_exists("import_history"):
        return []

    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM import_history ORDER BY imported_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_setting(key: str, value: str):
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        conn.execute(
            """INSERT INTO settings(key, value, updated_at)
               VALUES(?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   updated_at=CURRENT_TIMESTAMP""",
            (key, value),
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def load_setting(key: str, default: str = "") -> str:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else default

    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def upsert_article_msgids(records: list[dict]):
    """records: [{msgid, title, publish_date}]"""
    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        conn = get_master_conn()
        conn.executemany(
            """INSERT INTO article_msgids (msgid, title, normalized_title, publish_date)
               VALUES (:msgid, :title, :normalized_title, :publish_date)
               ON CONFLICT(msgid) DO UPDATE SET
                   title=excluded.title,
                   normalized_title=excluded.normalized_title,
                   publish_date=excluded.publish_date,
                   fetched_at=CURRENT_TIMESTAMP""",
            [
                {
                    "msgid": r.get("msgid"),
                    "title": r.get("title"),
                    "normalized_title": normalize_title(r.get("title")),
                    "publish_date": r.get("publish_date"),
                }
                for r in records
            ],
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.executemany(
        """INSERT INTO article_msgids (msgid, title, publish_date)
           VALUES (:msgid, :title, :publish_date)
           ON CONFLICT(msgid) DO UPDATE SET
               title=excluded.title,
               publish_date=excluded.publish_date,
               fetched_at=CURRENT_TIMESTAMP""",
        records,
    )
    conn.commit()
    conn.close()


def mark_detail_downloaded(msgid: str):
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        conn.execute(
            "UPDATE article_msgids SET detail_downloaded=1 WHERE msgid=?", (msgid,)
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.execute(
        "UPDATE article_msgids SET detail_downloaded=1 WHERE msgid=?", (msgid,)
    )
    conn.commit()
    conn.close()


def query_article_msgids(only_pending=False) -> list[dict]:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        detail_match = """
            FROM article_master m
            JOIN article_diagnostics d ON d.article_id = m.id
            WHERE m.normalized_title = article_msgids.normalized_title
              AND (
                  article_msgids.publish_date IS NULL
                  OR m.publish_date IS NULL
                  OR m.publish_date = article_msgids.publish_date
              )
              AND d.detail_snapshot_at IS NOT NULL
        """
        has_detail_snapshot = f"EXISTS(SELECT 1 {detail_match})"
        detail_ready = f"""EXISTS(
            SELECT 1 {detail_match}
              AND (
                  article_msgids.fetched_at IS NULL
                  OR d.detail_snapshot_at >= article_msgids.fetched_at
              )
        )"""
        q = f"""SELECT article_msgids.*,
                       {has_detail_snapshot} AS has_detail_snapshot,
                       {detail_ready} AS detail_ready
                FROM article_msgids"""
        if only_pending:
            q += f" WHERE NOT {detail_ready}"
        q += " ORDER BY publish_date DESC, fetched_at DESC"
        rows = conn.execute(q).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    has_detail_snapshot = """
        EXISTS (
            SELECT 1
            FROM article_detail d
            WHERE d.title = article_msgids.title
        )
    """
    detail_ready = """
        EXISTS (
            SELECT 1
            FROM article_detail d
            WHERE d.title = article_msgids.title
              AND (
                  article_msgids.fetched_at IS NULL
                  OR d.created_at >= article_msgids.fetched_at
              )
        )
    """
    q = f"""SELECT article_msgids.*,
                   {has_detail_snapshot} AS has_detail_snapshot,
                   {detail_ready} AS detail_ready
            FROM article_msgids"""
    if only_pending:
        q += f" WHERE NOT {detail_ready}"
    q += " ORDER BY publish_date DESC"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 文章趋势 ───────────────────────────────────────────────────────────────────

def upsert_article_trend(title: str, records: list[dict]):
    """records: [{stat_date, channel, read_user, share_user}]"""
    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        conn = get_master_conn()
        normalized_title = normalize_title(title)
        article = conn.execute(
            "SELECT id, canonical_title FROM article_master WHERE normalized_title=? LIMIT 1",
            (normalized_title,),
        ).fetchone()
        conn.executemany(
            """INSERT INTO article_trend (article_id, title, normalized_title, stat_date, channel, read_user, share_user, updated_at)
               VALUES (:article_id, :title, :normalized_title, :stat_date, :channel, :read_user, :share_user, CURRENT_TIMESTAMP)
               ON CONFLICT(normalized_title, stat_date, channel) DO UPDATE SET
                   article_id=excluded.article_id,
                   title=excluded.title,
                   read_user=MAX(article_trend.read_user, excluded.read_user),
                   share_user=MAX(article_trend.share_user, excluded.share_user),
                   updated_at=CURRENT_TIMESTAMP""",
            [
                {
                    "article_id": article["id"] if article else None,
                    "title": article["canonical_title"] if article else title,
                    "normalized_title": normalized_title,
                    **r,
                }
                for r in records
            ],
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.executemany(
        """INSERT INTO article_trend (title, stat_date, channel, read_user, share_user)
           VALUES (:title, :stat_date, :channel, :read_user, :share_user)
           ON CONFLICT(title, stat_date, channel) DO UPDATE SET
               read_user=excluded.read_user, share_user=excluded.share_user""",
        [{"title": title, **r} for r in records],
    )
    conn.commit()
    conn.close()


def query_article_trend(title: str) -> list[dict]:
    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT stat_date, channel, read_user, share_user
               FROM article_trend
               WHERE normalized_title=?
               ORDER BY stat_date, channel""",
            (normalize_title(title),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    rows = conn.execute(
        """SELECT stat_date, channel, read_user, share_user
           FROM article_trend WHERE title=? ORDER BY stat_date, channel""",
        (title,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 数据新鲜度 ─────────────────────────────────────────────────────────────────

def query_data_freshness() -> dict:
    """返回各类数据的最新日期，超过2天标红。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        def latest(sql):
            row = conn.execute(sql).fetchone()
            return row[0] if row and row[0] else None

        result = [
            {"source": "趋势数据", "last_update": latest("SELECT MAX(stat_date) FROM account_channel_daily WHERE channel='全部'")},
            {"source": "用户数据", "last_update": latest("SELECT MAX(stat_date) FROM account_user_daily")},
            {"source": "消息数据", "last_update": latest("SELECT MAX(stat_date) FROM account_message_stats")},
            {"source": "菜单数据", "last_update": latest("SELECT MAX(import_date) FROM account_menu_stats")},
            {"source": "文章主档", "last_update": latest("SELECT MAX(DATE(updated_at)) FROM article_master")},
        ]
        conn.close()
        return [item for item in result if item["last_update"]]

    conn = get_conn()
    def latest(sql):
        row = conn.execute(sql).fetchone()
        return row[0] if row and row[0] else None

    result = {
        "tendency":  latest("SELECT MAX(stat_date) FROM daily_reads WHERE channel='全部'"),
        "user":      latest("SELECT MAX(stat_date) FROM daily_user_stats"),
        "msg":       latest("SELECT MAX(stat_date) FROM daily_msg_stats"),
        "menu":      latest("SELECT MAX(import_date) FROM menu_stats"),
        "article":   latest("SELECT MAX(DATE(created_at)) FROM article_detail"),
    }
    conn.close()
    return result


# ── 推荐命中率趋势 ─────────────────────────────────────────────────────────────

def query_recommend_trend(days=60) -> list[dict]:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT stat_date,
                      ROUND(
                          SUM(CASE WHEN channel='推荐' THEN read_user ELSE 0 END) * 100.0
                          / NULLIF(SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END), 0),
                      1) AS rec_pct,
                      SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END) AS total_reads
               FROM account_channel_daily
               WHERE stat_date >= date('now', ?)
               GROUP BY stat_date
               ORDER BY stat_date""",
            (f"-{days} days",),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    rows = conn.execute(
        """SELECT stat_date,
               ROUND(
                   SUM(CASE WHEN channel='推荐' THEN read_user ELSE 0 END) * 100.0
                   / NULLIF(SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END), 0),
               1) AS rec_pct,
               SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END) AS total_reads
           FROM daily_reads
           WHERE stat_date >= date('now', ?)
           GROUP BY stat_date
           ORDER BY stat_date""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 最佳发文时间 ───────────────────────────────────────────────────────────────

def query_best_publish_time() -> dict:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        dow_rows = conn.execute(
            """SELECT
                   CAST(strftime('%w', publish_date) AS INTEGER) AS dow,
                   ROUND(AVG(total_reads), 1) AS avg_reads,
                   COUNT(*) AS article_count
               FROM article_master
               WHERE publish_date IS NOT NULL
                 AND publish_date != ''
                 AND strftime('%w', publish_date) IS NOT NULL
               GROUP BY dow ORDER BY dow"""
        ).fetchall()
        month_rows = conn.execute(
            """SELECT
                   CAST(strftime('%m', publish_date) AS INTEGER) AS month,
                   ROUND(AVG(total_reads), 1) AS avg_reads,
                   COUNT(*) AS article_count
               FROM article_master
               WHERE publish_date IS NOT NULL
                 AND publish_date != ''
                 AND strftime('%m', publish_date) IS NOT NULL
               GROUP BY month ORDER BY month"""
        ).fetchall()
        conn.close()
        dow_labels = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
        return {
            "by_dow": [
                {"label": dow_labels[r["dow"]], "avg_reads": r["avg_reads"], "count": r["article_count"]}
                for r in dow_rows
            ],
            "by_month": [
                {"label": f"{r['month']}月", "avg_reads": r["avg_reads"], "count": r["article_count"]}
                for r in month_rows
            ],
        }

    conn = get_conn()
    # 按星期几分析（0=周日，1=周一...6=周六）
    dow_rows = conn.execute(
        """SELECT
               CAST(strftime('%w', publish_date) AS INTEGER) AS dow,
               ROUND(AVG(total_reads), 0) AS avg_reads,
               COUNT(*) AS article_count
           FROM (
               SELECT publish_date, SUM(read_user) AS total_reads
               FROM article_source_stats
               WHERE channel='全部' AND publish_date IS NOT NULL AND publish_date != ''
               GROUP BY publish_date, title
           )
           GROUP BY dow ORDER BY dow"""
    ).fetchall()

    # 按月份分析
    month_rows = conn.execute(
        """SELECT
               CAST(strftime('%m', publish_date) AS INTEGER) AS month,
               ROUND(AVG(total_reads), 0) AS avg_reads,
               COUNT(*) AS article_count
           FROM (
               SELECT publish_date, SUM(read_user) AS total_reads
               FROM article_source_stats
               WHERE channel='全部' AND publish_date IS NOT NULL AND publish_date != ''
               GROUP BY publish_date, title
           )
           GROUP BY month ORDER BY month"""
    ).fetchall()
    conn.close()

    dow_labels = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    return {
        "by_dow": [
            {"label": dow_labels[r["dow"]], "avg_reads": r["avg_reads"], "count": r["article_count"]}
            for r in dow_rows
        ],
        "by_month": [
            {"label": f"{r['month']}月", "avg_reads": r["avg_reads"], "count": r["article_count"]}
            for r in month_rows
        ],
    }


# ── 粉丝转化漏斗 ───────────────────────────────────────────────────────────────

def query_funnel() -> dict:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        row = conn.execute(
            """SELECT
                   COALESCE(SUM(total_reads), 0) AS reads,
                   COALESCE(SUM(share_user), 0) AS shares,
                   COALESCE(SUM(like_user), 0) AS likes,
                   COALESCE(SUM(fav_user), 0) AS favs,
                   COALESCE(SUM(follow_after_read), 0) AS follows,
                   COALESCE(SUM(comment_count), 0) AS comments
               FROM article_master"""
        ).fetchone()
        conn.close()
        if not row or not row["reads"]:
            return {}
        reads = row["reads"] or 1
        return {
            "reads": row["reads"] or 0,
            "shares": row["shares"] or 0,
            "likes": row["likes"] or 0,
            "favs": row["favs"] or 0,
            "follows": row["follows"] or 0,
            "comments": row["comments"] or 0,
            "share_rate": round((row["shares"] or 0) / reads * 100, 2),
            "like_rate": round((row["likes"] or 0) / reads * 100, 2),
            "fav_rate": round((row["favs"] or 0) / reads * 100, 2),
            "follow_rate": round((row["follows"] or 0) / reads * 100, 2),
        }

    conn = get_conn()
    row = conn.execute(
        """SELECT
               SUM(read_user)         AS reads,
               SUM(share_user)        AS shares,
               SUM(like_user)         AS likes,
               SUM(fav_user)          AS favs,
               SUM(follow_after_read) AS follows,
               SUM(comment_count)     AS comments
           FROM article_detail"""
    ).fetchone()
    conn.close()
    if not row or not row["reads"]:
        return {}
    reads = row["reads"] or 1
    return {
        "reads":    row["reads"]   or 0,
        "shares":   row["shares"]  or 0,
        "likes":    row["likes"]   or 0,
        "favs":     row["favs"]    or 0,
        "follows":  row["follows"] or 0,
        "comments": row["comments"]or 0,
        "share_rate":  round((row["shares"]  or 0) / reads * 100, 2),
        "like_rate":   round((row["likes"]   or 0) / reads * 100, 2),
        "fav_rate":    round((row["favs"]    or 0) / reads * 100, 2),
        "follow_rate": round((row["follows"] or 0) / reads * 100, 2),
    }


# ── 月环比对比 ─────────────────────────────────────────────────────────────────

def query_month_comparison() -> dict:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        def month_reads(offset_months: int) -> int:
            row = conn.execute(
                """SELECT COALESCE(SUM(total_read_user), 0)
                   FROM account_daily_metrics
                   WHERE stat_date >= date('now', 'start of month', ?)
                     AND stat_date <  date('now', 'start of month', ?)""",
                (f"{offset_months} months", f"{offset_months + 1} months"),
            ).fetchone()
            return row[0] if row else 0

        this_month = month_reads(0)
        last_month = month_reads(-1)
        diff = this_month - last_month
        pct = round(diff / last_month * 100, 1) if last_month else None
        conn.close()
        return {"this_month": this_month, "last_month": last_month, "diff": diff, "pct": pct}

    conn = get_conn()
    def month_reads(offset_months: int) -> int:
        row = conn.execute(
            """SELECT COALESCE(SUM(read_user), 0)
               FROM daily_reads
               WHERE channel='全部'
                 AND stat_date >= date('now', 'start of month', ?)
                 AND stat_date <  date('now', 'start of month', ?)""",
            (f"{offset_months} months", f"{offset_months + 1} months"),
        ).fetchone()
        return row[0] if row else 0

    this_month  = month_reads(0)
    last_month  = month_reads(-1)
    diff = this_month - last_month
    pct  = round(diff / last_month * 100, 1) if last_month else None
    conn.close()
    return {"this_month": this_month, "last_month": last_month, "diff": diff, "pct": pct}


# ── Bark 日报数据 ──────────────────────────────────────────────────────────────

def query_yesterday_report() -> dict:
    """昨日数据快报，供 Bark 推送使用。"""
    from datetime import timedelta
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        reads_row = conn.execute(
            "SELECT total_read_user FROM account_daily_metrics WHERE stat_date=?", (yesterday,)
        ).fetchone()
        user_row = conn.execute(
            "SELECT new_user, cancel_user, net_user FROM account_user_daily WHERE stat_date=?", (yesterday,)
        ).fetchone()
        avg7_row = conn.execute(
            """SELECT ROUND(AVG(total_read_user)) FROM account_daily_metrics
               WHERE stat_date BETWEEN date(?, '-7 days') AND date(?, '-1 days')""",
            (yesterday, yesterday),
        ).fetchone()
        top_row = conn.execute(
            """SELECT canonical_title AS title, total_reads AS r
               FROM article_master
               WHERE publish_date >= date('now', '-7 days')
               ORDER BY total_reads DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        reads = reads_row["total_read_user"] if reads_row else 0
        avg7 = int(avg7_row[0] or 0)
        diff = reads - avg7
        pct = round(diff / avg7 * 100, 1) if avg7 else None
        return {
            "date": yesterday,
            "reads": reads,
            "avg7": avg7,
            "diff": diff,
            "pct": pct,
            "new_user": user_row["new_user"] if user_row else None,
            "net_user": user_row["net_user"] if user_row else None,
            "top_title": top_row["title"] if top_row else None,
            "top_reads": top_row["r"] if top_row else None,
        }

    conn = get_conn()
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    reads_row = conn.execute(
        "SELECT read_user FROM daily_reads WHERE stat_date=? AND channel='全部'", (yesterday,)
    ).fetchone()

    user_row = conn.execute(
        "SELECT new_user, cancel_user, net_user FROM daily_user_stats WHERE stat_date=?", (yesterday,)
    ).fetchone()

    avg7_row = conn.execute(
        """SELECT ROUND(AVG(read_user)) FROM daily_reads
           WHERE channel='全部'
             AND stat_date BETWEEN date(?, '-7 days') AND date(?, '-1 days')""",
        (yesterday, yesterday),
    ).fetchone()

    top_row = conn.execute(
        """SELECT title, SUM(read_user) AS r FROM article_source_stats
           WHERE channel='全部' AND publish_date >= date('now', '-7 days')
           GROUP BY title ORDER BY r DESC LIMIT 1"""
    ).fetchone()

    conn.close()
    reads = reads_row["read_user"] if reads_row else 0
    avg7  = int(avg7_row[0] or 0)
    diff  = reads - avg7
    pct   = round(diff / avg7 * 100, 1) if avg7 else None

    return {
        "date":     yesterday,
        "reads":    reads,
        "avg7":     avg7,
        "diff":     diff,
        "pct":      pct,
        "new_user": user_row["new_user"] if user_row else None,
        "net_user": user_row["net_user"] if user_row else None,
        "top_title": top_row["title"] if top_row else None,
        "top_reads": top_row["r"]     if top_row else None,
    }


def query_anomaly_check() -> dict | None:
    """检测今日阅读量是否异常（偏离7日均值 ±40% 以上）。"""
    from datetime import timedelta
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        today = datetime.now().strftime("%Y-%m-%d")
        today_row = conn.execute(
            "SELECT total_read_user FROM account_daily_metrics WHERE stat_date=?", (today,)
        ).fetchone()
        if not today_row:
            conn.close()
            return None
        avg7_row = conn.execute(
            """SELECT ROUND(AVG(total_read_user)) FROM account_daily_metrics
               WHERE stat_date BETWEEN date(?, '-7 days') AND date(?, '-1 days')""",
            (today, today),
        ).fetchone()
        conn.close()
        today_reads = today_row["total_read_user"]
        avg7 = int(avg7_row[0] or 0)
        if avg7 == 0:
            return None
        pct = (today_reads - avg7) / avg7 * 100
        threshold = float(load_setting("anomaly_threshold", "40") or "40")
        if abs(pct) < threshold:
            return None
        direction = "暴涨" if pct > 0 else "骤降"
        return {"today": today_reads, "avg7": avg7, "pct": round(pct, 1), "direction": direction}

    conn = get_conn()
    today = datetime.now().strftime("%Y-%m-%d")

    today_row = conn.execute(
        "SELECT read_user FROM daily_reads WHERE stat_date=? AND channel='全部'", (today,)
    ).fetchone()
    if not today_row:
        conn.close()
        return None

    avg7_row = conn.execute(
        """SELECT ROUND(AVG(read_user)) FROM daily_reads
           WHERE channel='全部'
             AND stat_date BETWEEN date(?, '-7 days') AND date(?, '-1 days')""",
        (today, today),
    ).fetchone()
    conn.close()

    today_reads = today_row["read_user"]
    avg7 = int(avg7_row[0] or 0)
    if avg7 == 0:
        return None

    pct = (today_reads - avg7) / avg7 * 100
    threshold = float(load_setting("anomaly_threshold", "40") or "40")
    if abs(pct) < threshold:
        return None

    direction = "暴涨" if pct > 0 else "骤降"
    return {"today": today_reads, "avg7": avg7, "pct": round(pct, 1), "direction": direction}


# ── 推荐入选规律分析 ───────────────────────────────────────────────────────────

def query_recommend_analysis() -> dict:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        dow_rows = conn.execute(
            """SELECT CAST(strftime('%w', publish_date) AS INTEGER) AS dow,
                      ROUND(AVG(rec_ratio * 100), 1) AS avg_rec_pct,
                      COUNT(*) AS cnt
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               WHERE publish_date IS NOT NULL AND publish_date != '' AND rec_ratio IS NOT NULL
               GROUP BY dow ORDER BY dow"""
        ).fetchall()
        dist_rows = conn.execute(
            """SELECT
                   CASE
                       WHEN rec_ratio * 100 < 10 THEN '0-10%'
                       WHEN rec_ratio * 100 < 30 THEN '10-30%'
                       WHEN rec_ratio * 100 < 50 THEN '30-50%'
                       ELSE '50%以上'
                   END AS range_label,
                   COUNT(*) AS cnt
               FROM article_diagnostics
               WHERE rec_ratio IS NOT NULL
               GROUP BY range_label ORDER BY range_label"""
        ).fetchall()
        conn.close()
        dow_labels = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
        return {
            "by_dow": [
                {"label": dow_labels[r["dow"]], "avg_rec_pct": r["avg_rec_pct"], "count": r["cnt"]}
                for r in dow_rows
            ],
            "distribution": [
                {"range": r["range_label"], "count": r["cnt"]} for r in dist_rows
            ],
        }

    conn = get_conn()

    # 按星期几：平均推荐占比
    dow_rows = conn.execute(
        """SELECT CAST(strftime('%w', pub_date) AS INTEGER) AS dow,
                  ROUND(AVG(rec_pct), 1) AS avg_rec_pct,
                  COUNT(*) AS cnt
           FROM (
               SELECT publish_date AS pub_date,
                      SUM(CASE WHEN channel='推荐' THEN read_user ELSE 0 END) * 100.0
                      / NULLIF(SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END), 0) AS rec_pct
               FROM article_source_stats
               GROUP BY publish_date, title
               HAVING SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END) > 0
           ) GROUP BY dow ORDER BY dow"""
    ).fetchall()

    # 推荐占比分布
    dist_rows = conn.execute(
        """SELECT
               CASE
                   WHEN rec_pct < 10 THEN '0-10%'
                   WHEN rec_pct < 30 THEN '10-30%'
                   WHEN rec_pct < 50 THEN '30-50%'
                   ELSE '50%以上'
               END AS range_label,
               COUNT(*) AS cnt
           FROM (
               SELECT SUM(CASE WHEN channel='推荐' THEN read_user ELSE 0 END) * 100.0
                      / NULLIF(SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END), 0) AS rec_pct
               FROM article_source_stats
               GROUP BY publish_date, title
               HAVING SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END) > 0
           ) GROUP BY range_label ORDER BY range_label"""
    ).fetchall()

    conn.close()
    dow_labels = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    return {
        "by_dow": [
            {"label": dow_labels[r["dow"]], "avg_rec_pct": r["avg_rec_pct"], "count": r["cnt"]}
            for r in dow_rows
        ],
        "distribution": [
            {"range": r["range_label"], "count": r["cnt"]} for r in dist_rows
        ],
    }


# ── 日历数据 ───────────────────────────────────────────────────────────────────

def query_calendar_data() -> list[dict]:
    """每篇文章的发布日期和总阅读量，供日历视图使用。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT publish_date, canonical_title AS title, total_reads
               FROM article_master
               WHERE publish_date IS NOT NULL AND publish_date != ''
               ORDER BY publish_date"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    rows = conn.execute(
        """SELECT publish_date, title, SUM(read_user) AS total_reads
           FROM article_source_stats
           WHERE channel='全部' AND publish_date IS NOT NULL AND publish_date != ''
           GROUP BY publish_date, title
           ORDER BY publish_date"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 标题特征分析 ────────────────────────────────────────────────────────────────

def query_title_analysis() -> dict:
    """分析标题长度、数字、疑问句对阅读量和推荐占比的影响。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT m.publish_date, m.canonical_title AS title, m.total_reads,
                      COALESCE(d.rec_ratio, 0) * 100.0 AS rec_pct
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               WHERE m.total_reads > 0"""
        ).fetchall()
        conn.close()
    else:
        conn = get_conn()
        rows = conn.execute(
            """SELECT a.publish_date, a.title,
                      SUM(CASE WHEN a.channel='全部' THEN a.read_user ELSE 0 END) AS total_reads,
                      SUM(CASE WHEN a.channel='推荐' THEN a.read_user ELSE 0 END) * 100.0
                      / NULLIF(SUM(CASE WHEN a.channel='全部' THEN a.read_user ELSE 0 END), 0) AS rec_pct
               FROM article_source_stats a
               GROUP BY a.publish_date, a.title
               HAVING total_reads > 0"""
        ).fetchall()
        conn.close()

    import re
    buckets_len  = {}   # 标题长度分段
    has_num_yes  = {"reads": [], "rec": []}
    has_num_no   = {"reads": [], "rec": []}
    has_q_yes    = {"reads": [], "rec": []}
    has_q_no     = {"reads": [], "rec": []}

    for r in rows:
        title = r["title"] or ""
        reads = r["total_reads"] or 0
        rec   = r["rec_pct"] or 0

        # 长度桶 (每5字一桶)
        llen = len(title)
        bucket = f"{(llen // 5) * 5 + 1}-{(llen // 5) * 5 + 5}字"
        if bucket not in buckets_len:
            buckets_len[bucket] = {"reads": [], "rec": [], "raw": (llen // 5) * 5}
        buckets_len[bucket]["reads"].append(reads)
        buckets_len[bucket]["rec"].append(rec)

        # 含数字？
        if re.search(r'\d', title):
            has_num_yes["reads"].append(reads); has_num_yes["rec"].append(rec)
        else:
            has_num_no["reads"].append(reads);  has_num_no["rec"].append(rec)

        # 含疑问？
        if re.search(r'[？?]|为什么|怎么|如何|吗$', title):
            has_q_yes["reads"].append(reads); has_q_yes["rec"].append(rec)
        else:
            has_q_no["reads"].append(reads);  has_q_no["rec"].append(rec)

    def avg(lst): return round(sum(lst) / len(lst), 1) if lst else 0

    len_data = sorted(
        [{"label": k, "avg_reads": avg(v["reads"]), "avg_rec": avg(v["rec"]),
          "count": len(v["reads"]), "_raw": v["raw"]}
         for k, v in buckets_len.items()],
        key=lambda x: x["_raw"],
    )
    for d in len_data:
        del d["_raw"]

    return {
        "by_length": len_data,
        "by_number": [
            {"label": "含数字", "avg_reads": avg(has_num_yes["reads"]),
             "avg_rec": avg(has_num_yes["rec"]), "count": len(has_num_yes["reads"])},
            {"label": "不含数字", "avg_reads": avg(has_num_no["reads"]),
             "avg_rec": avg(has_num_no["rec"]), "count": len(has_num_no["reads"])},
        ],
        "by_question": [
            {"label": "疑问式", "avg_reads": avg(has_q_yes["reads"]),
             "avg_rec": avg(has_q_yes["rec"]), "count": len(has_q_yes["reads"])},
            {"label": "非疑问", "avg_reads": avg(has_q_no["reads"]),
             "avg_rec": avg(has_q_no["rec"]), "count": len(has_q_no["reads"])},
        ],
    }


# ── 文章生命周期 ────────────────────────────────────────────────────────────────

def query_lifecycle_data(top_n: int = 5) -> list[dict]:
    """
    返回阅读量最高的 top_n 篇文章在发布后各天的阅读量衰减曲线。
    依赖 article_trend 表（单篇数据明细导入后才有数据）。
    """
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
    else:
        conn = get_conn()

    top = conn.execute(
        """SELECT title, SUM(read_user) AS total
           FROM article_trend WHERE channel='全部'
           GROUP BY title ORDER BY total DESC LIMIT ?""",
        (top_n,),
    ).fetchall()

    result = []
    for art in top:
        title = art["title"]
        pub = conn.execute(
            "SELECT MIN(stat_date) AS pub FROM article_trend WHERE title=? AND channel='全部'",
            (title,),
        ).fetchone()
        if not pub or not pub["pub"]:
            continue
        pub_date = pub["pub"]
        rows = conn.execute(
            """SELECT stat_date,
                      SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END) AS reads
               FROM article_trend WHERE title=?
               GROUP BY stat_date ORDER BY stat_date""",
            (title,),
        ).fetchall()
        days_data = []
        for r in rows:
            from datetime import date as _d
            delta = (_d.fromisoformat(r["stat_date"]) - _d.fromisoformat(pub_date)).days
            days_data.append({"day": delta, "reads": r["reads"] or 0})
        result.append({"title": title[:20], "data": days_data})
    conn.close()
    return result


# ── 发文频率分析 ────────────────────────────────────────────────────────────────

def query_posting_frequency() -> list[dict]:
    """每周发文篇数 vs 当周平均阅读量。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT strftime('%Y-W%W', publish_date) AS week,
                      COUNT(*) AS article_count,
                      ROUND(AVG(total_reads), 0) AS avg_reads
               FROM article_master
               WHERE publish_date IS NOT NULL AND publish_date != ''
               GROUP BY week ORDER BY week"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    rows = conn.execute(
        """SELECT strftime('%Y-W%W', publish_date) AS week,
                  COUNT(DISTINCT title) AS article_count,
                  ROUND(AVG(total_reads), 0) AS avg_reads
           FROM (
               SELECT publish_date, title,
                      SUM(read_user) AS total_reads
               FROM article_source_stats
               WHERE channel='全部' AND publish_date IS NOT NULL AND publish_date != ''
               GROUP BY publish_date, title
           )
           GROUP BY week ORDER BY week"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 涨粉归因 ──────────────────────────────────────────────────────────────────

def query_follower_attribution() -> list[dict]:
    """
    涨粉归因：优先使用 article_detail 表中的真实「阅读后关注」数据，
    没有详情数据的文章标注为无数据。
    """
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT publish_date,
                      canonical_title AS title,
                      total_reads,
                      follow_after_read
               FROM article_master
               WHERE publish_date IS NOT NULL AND publish_date != ''
               ORDER BY follow_after_read DESC, total_reads DESC"""
        ).fetchall()
        conn.close()
        return [
            {
                "publish_date": r["publish_date"],
                "title": r["title"],
                "total_reads": r["total_reads"],
                "follow_after_read": r["follow_after_read"],
                "source": "master",
            }
            for r in rows
        ]

    conn = get_conn()
    articles = conn.execute(
        """SELECT publish_date, title,
                  SUM(CASE WHEN channel='全部' THEN read_user ELSE 0 END) AS total_reads
           FROM article_source_stats
           WHERE channel='全部' AND publish_date IS NOT NULL AND publish_date != ''
           GROUP BY publish_date, title"""
    ).fetchall()

    # 从 article_detail 表获取真实的「阅读后关注」数据
    detail_rows = conn.execute(
        "SELECT title, follow_after_read, deliver_user FROM article_detail"
    ).fetchall()
    detail_map = {r["title"]: r for r in detail_rows}

    result = []
    for art in articles:
        title = art["title"]
        detail = detail_map.get(title)
        if detail and detail["follow_after_read"] is not None:
            follow = detail["follow_after_read"]
            source = "detail"
        else:
            follow = None
            source = "none"
        result.append({
            "publish_date":      art["publish_date"],
            "title":             title,
            "total_reads":       art["total_reads"],
            "follow_after_read": follow,
            "source":            source,
        })
    conn.close()
    result.sort(key=lambda x: -(x["follow_after_read"] if x["follow_after_read"] is not None else -1))
    return result


# ── 节假日影响分析 ─────────────────────────────────────────────────────────────

# 中国常见节假日（月-日格式，不含年份，适用于多年数据）
_CN_HOLIDAYS = {
    "01-01", "01-02", "01-03",                         # 元旦
    "02-10", "02-11", "02-12", "02-13", "02-14",       # 春节（2024近似）
    "04-04", "04-05", "04-06",                         # 清明
    "05-01", "05-02", "05-03",                         # 劳动节
    "06-10",                                            # 端午（近似）
    "09-17",                                            # 中秋（近似）
    "10-01", "10-02", "10-03", "10-04", "10-05", "10-06", "10-07",  # 国庆
}


def query_holiday_analysis() -> dict:
    """节假日 vs 工作日阅读量对比。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            "SELECT stat_date, total_read_user AS read_user FROM account_daily_metrics ORDER BY stat_date"
        ).fetchall()
        conn.close()
    else:
        conn = get_conn()
        rows = conn.execute(
            "SELECT stat_date, read_user FROM daily_reads WHERE channel='全部' ORDER BY stat_date"
        ).fetchall()
        conn.close()

    holiday_reads, workday_reads = [], []
    weekend_reads = []
    for r in rows:
        d = r["stat_date"]
        if not d:
            continue
        md = d[5:]  # MM-DD
        from datetime import date as _date
        try:
            weekday = _date.fromisoformat(d).weekday()  # 0=Mon, 6=Sun
        except Exception:
            continue
        reads = r["read_user"] or 0
        if md in _CN_HOLIDAYS:
            holiday_reads.append(reads)
        elif weekday >= 5:
            weekend_reads.append(reads)
        else:
            workday_reads.append(reads)

    def avg(lst): return round(sum(lst) / len(lst), 1) if lst else 0

    return {
        "holiday":  {"avg": avg(holiday_reads),  "count": len(holiday_reads)},
        "weekend":  {"avg": avg(weekend_reads),  "count": len(weekend_reads)},
        "workday":  {"avg": avg(workday_reads),  "count": len(workday_reads)},
    }


# ── 爆款概率评分 ───────────────────────────────────────────────────────────────

def query_viral_scores() -> list[dict]:
    """
    基于已有数据给每篇文章打"爆款评分"(0-100)。
    指标：阅读量分位、推荐占比、转发率、完读率。
    """
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        arts = conn.execute(
            """SELECT m.publish_date, m.canonical_title AS title, m.total_reads,
                      COALESCE(d.rec_ratio, 0) * 100.0 AS rec_pct,
                      m.share_user, d.complete_rate
               FROM article_master m
               LEFT JOIN article_diagnostics d ON d.article_id = m.id
               WHERE m.total_reads > 0"""
        ).fetchall()
        conn.close()
        reads_list = [r["total_reads"] for r in arts if r["total_reads"]]
        if not reads_list:
            return []
        max_reads = max(reads_list)
        result = []
        for r in arts:
            reads = r["total_reads"] or 0
            rec_pct = r["rec_pct"] or 0
            read_score = min(40, int(reads / max_reads * 40))
            rec_score = min(25, int(rec_pct / 50 * 25))
            share_rate = (r["share_user"] or 0) / reads * 100 if reads else 0
            share_score = min(20, int(share_rate / 5 * 20))
            cr = (r["complete_rate"] or 0) * 100 if (r["complete_rate"] or 0) <= 1 else (r["complete_rate"] or 0)
            cr_score = min(15, int(cr / 50 * 15))
            total_score = read_score + rec_score + share_score + cr_score
            result.append({
                "publish_date": r["publish_date"],
                "title": r["title"],
                "total_reads": reads,
                "rec_pct": round(rec_pct, 1),
                "score": total_score,
                "breakdown": {"reads": read_score, "rec": rec_score, "share": share_score, "complete": cr_score},
            })
        result.sort(key=lambda x: -x["score"])
        return result

    conn = get_conn()
    arts = conn.execute(
        """SELECT a.publish_date, a.title,
                  SUM(CASE WHEN a.channel='全部' THEN a.read_user ELSE 0 END) AS total_reads,
                  SUM(CASE WHEN a.channel='推荐' THEN a.read_user ELSE 0 END) * 100.0
                  / NULLIF(SUM(CASE WHEN a.channel='全部' THEN a.read_user ELSE 0 END), 0) AS rec_pct
           FROM article_source_stats a
           GROUP BY a.publish_date, a.title
           HAVING total_reads > 0"""
    ).fetchall()
    details = conn.execute(
        "SELECT title, share_user, complete_rate, read_user FROM article_detail"
    ).fetchall()
    conn.close()

    detail_map = {d["title"]: dict(d) for d in details}

    reads_list = [r["total_reads"] for r in arts if r["total_reads"]]
    if not reads_list:
        return []
    max_reads = max(reads_list)

    result = []
    for r in arts:
        title   = r["title"]
        reads   = r["total_reads"] or 0
        rec_pct = r["rec_pct"] or 0
        d       = detail_map.get(title, {})

        # 阅读量分位评分 (0-40)
        read_score = min(40, int(reads / max_reads * 40))
        # 推荐占比评分 (0-25): 推荐>=50% → 25分
        rec_score  = min(25, int(rec_pct / 50 * 25))
        # 转发率评分 (0-20)
        share_rate = (d.get("share_user") or 0) / reads * 100 if reads else 0
        share_score = min(20, int(share_rate / 5 * 20))
        # 完读率评分 (0-15)
        cr = (d.get("complete_rate") or 0) * 100 if (d.get("complete_rate") or 0) <= 1 else (d.get("complete_rate") or 0)
        cr_score = min(15, int(cr / 50 * 15))

        total_score = read_score + rec_score + share_score + cr_score
        result.append({
            "publish_date": r["publish_date"],
            "title":        title,
            "total_reads":  reads,
            "rec_pct":      round(rec_pct, 1),
            "score":        total_score,
            "breakdown":    {"reads": read_score, "rec": rec_score,
                             "share": share_score, "complete": cr_score},
        })

    result.sort(key=lambda x: -x["score"])
    return result


# ── 文章标签 CRUD ───────────────────────────────────────────────────────────────

def upsert_article_tag(title: str, tag: str):
    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        conn = get_master_conn()
        normalized_title = normalize_title(title)
        article = conn.execute(
            "SELECT id, canonical_title FROM article_master WHERE normalized_title=? LIMIT 1",
            (normalized_title,),
        ).fetchone()
        conn.execute(
            """INSERT INTO article_tags (article_id, title, normalized_title, tag)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(normalized_title, tag) DO NOTHING""",
            (article["id"] if article else None, article["canonical_title"] if article else title, normalized_title, tag),
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.execute(
        "INSERT INTO article_tags (title, tag) VALUES (?, ?) ON CONFLICT(title, tag) DO NOTHING",
        (title, tag),
    )
    conn.commit(); conn.close()


def delete_article_tag(title: str, tag: str):
    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        conn = get_master_conn()
        conn.execute(
            "DELETE FROM article_tags WHERE normalized_title=? AND tag=?",
            (normalize_title(title), tag),
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.execute("DELETE FROM article_tags WHERE title=? AND tag=?", (title, tag))
    conn.commit(); conn.close()


def query_article_tags(title: str = None) -> list[dict]:
    if _master_ready():
        from core.master_db import get_master_conn, normalize_title
        conn = get_master_conn()
        if title:
            rows = conn.execute(
                """SELECT id, article_id, title, tag, created_at
                   FROM article_tags
                   WHERE normalized_title=?
                   ORDER BY tag""",
                (normalize_title(title),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT title, GROUP_CONCAT(tag, ',') AS tags FROM article_tags GROUP BY normalized_title, title ORDER BY title"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    if title:
        rows = conn.execute(
            "SELECT * FROM article_tags WHERE title=? ORDER BY tag", (title,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT title, GROUP_CONCAT(tag, ',') AS tags FROM article_tags GROUP BY title"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 发文规划 CRUD ───────────────────────────────────────────────────────────────

def upsert_planned_article(plan_date: str, topic: str, note: str = "", status: str = "planned", plan_id: int = None):
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        if plan_id:
            conn.execute(
                """UPDATE planned_articles
                   SET plan_date=?, topic=?, note=?, status=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (plan_date, topic, note, status, plan_id),
            )
        else:
            conn.execute(
                """INSERT INTO planned_articles (plan_date, topic, note, status, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (plan_date, topic, note, status),
            )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    if plan_id:
        conn.execute(
            "UPDATE planned_articles SET plan_date=?, topic=?, note=?, status=? WHERE id=?",
            (plan_date, topic, note, status, plan_id),
        )
    else:
        conn.execute(
            "INSERT INTO planned_articles (plan_date, topic, note, status) VALUES (?, ?, ?, ?)",
            (plan_date, topic, note, status),
        )
    conn.commit(); conn.close()


def delete_planned_article(plan_id: int):
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        conn.execute("DELETE FROM planned_articles WHERE id=?", (plan_id,))
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.execute("DELETE FROM planned_articles WHERE id=?", (plan_id,))
    conn.commit(); conn.close()


def query_planned_articles() -> list[dict]:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            "SELECT * FROM planned_articles ORDER BY plan_date, id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM planned_articles ORDER BY plan_date, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 贡献热力图 ─────────────────────────────────────────────────────────────────

def query_heatmap_data(days: int = 365) -> list[dict]:
    """返回近 N 天每日总阅读量，供 GitHub 热力图使用。含 level(0-4) 字段。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT stat_date, total_read_user AS read_user
               FROM account_daily_metrics
               WHERE stat_date >= date('now', ?)
               ORDER BY stat_date""",
            (f"-{days} days",),
        ).fetchall()
        conn.close()
    else:
        conn = get_conn()
        rows = conn.execute(
            """SELECT stat_date, read_user
               FROM daily_reads
               WHERE channel='全部' AND stat_date >= date('now', ?)
               ORDER BY stat_date""",
            (f"-{days} days",),
        ).fetchall()
        conn.close()

    values = [r["read_user"] or 0 for r in rows]
    non_zero = sorted(v for v in values if v > 0)
    if non_zero:
        n = len(non_zero)
        p25 = non_zero[n // 4]
        p50 = non_zero[n // 2]
        p75 = non_zero[3 * n // 4]
    else:
        p25 = p50 = p75 = 1

    def level(reads):
        if reads == 0:   return 0
        if reads <= p25: return 1
        if reads <= p50: return 2
        if reads <= p75: return 3
        return 4

    return [{"date": r["stat_date"], "reads": r["read_user"] or 0,
             "level": level(r["read_user"] or 0)} for r in rows]


# ── 同比分析 ──────────────────────────────────────────────────────────────────

def query_yoy_comparison() -> list[dict]:
    """按月返回今年 vs 去年的阅读量对比。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            """SELECT strftime('%m', stat_date) AS month,
                      strftime('%Y', stat_date) AS year,
                      SUM(total_read_user) AS total
               FROM account_daily_metrics
               GROUP BY year, month ORDER BY year, month"""
        ).fetchall()
        conn.close()
    else:
        conn = get_conn()
        rows = conn.execute(
            """SELECT strftime('%m', stat_date) AS month,
                      strftime('%Y', stat_date) AS year,
                      SUM(read_user) AS total
               FROM daily_reads WHERE channel='全部'
               GROUP BY year, month ORDER BY year, month"""
        ).fetchall()
        conn.close()

    from datetime import datetime as _dt
    this_year = str(_dt.now().year)
    last_year = str(_dt.now().year - 1)

    this = {r["month"]: r["total"] for r in rows if r["year"] == this_year}
    last = {r["month"]: r["total"] for r in rows if r["year"] == last_year}

    result = []
    for m in [f"{i:02d}" for i in range(1, 13)]:
        t = this.get(m)
        l = last.get(m)
        if t is None and l is None:
            continue
        yoy = round((t - l) / l * 100, 1) if (t and l) else None
        result.append({
            "month":     f"{int(m)}月",
            "this_year": t,
            "last_year": l,
            "yoy_pct":   yoy,
        })
    return result


# ── 粉丝总量趋势 ───────────────────────────────────────────────────────────────

def query_total_user_trend(days: int = 180) -> list[dict]:
    """返回有记录的每日粉丝总量（total_user > 0）。"""
    if _master_ready():
        from core.master_db import query_account_user_daily
        rows = query_account_user_daily(limit=max(days, 365))
        rows = [r for r in rows if (r.get("total_user") or 0) > 0]
        if days and len(rows) > days:
            rows = rows[:days]
        rows.sort(key=lambda r: r.get("stat_date") or "")
        return rows

    conn = get_conn()
    rows = conn.execute(
        """SELECT stat_date, total_user
           FROM daily_user_stats
           WHERE total_user > 0 AND stat_date >= date('now', ?)
           ORDER BY stat_date""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 异常事件记录 ───────────────────────────────────────────────────────────────

def log_anomaly(log_date: str, today_reads: int, avg7: int, pct: float, direction: str):
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        conn.execute(
            """INSERT INTO anomaly_log (log_date, today_reads, avg7_reads, pct, direction)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(log_date) DO UPDATE SET
                   today_reads=excluded.today_reads, avg7_reads=excluded.avg7_reads,
                   pct=excluded.pct, direction=excluded.direction""",
            (log_date, today_reads, avg7, pct, direction),
        )
        conn.commit()
        conn.close()
        return

    conn = get_conn()
    conn.execute(
        """INSERT INTO anomaly_log (log_date, today_reads, avg7_reads, pct, direction)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(log_date) DO UPDATE SET
               today_reads=excluded.today_reads, avg7_reads=excluded.avg7_reads,
               pct=excluded.pct, direction=excluded.direction""",
        (log_date, today_reads, avg7, pct, direction),
    )
    conn.commit()
    conn.close()


def query_anomaly_log(limit: int = 30) -> list[dict]:
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        rows = conn.execute(
            "SELECT * FROM anomaly_log ORDER BY log_date DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM anomaly_log ORDER BY log_date DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 数据管理 ───────────────────────────────────────────────────────────────────

def query_data_stats() -> dict:
    """返回各表的行数、最早/最晚日期，用于数据管理页概览。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        def tbl(sql):
            return conn.execute(sql).fetchone()

        result = {
            "daily_reads": dict(tbl(
                "SELECT COUNT(*) AS rows, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d FROM account_daily_metrics"
            )),
            "daily_user_stats": dict(tbl(
                "SELECT COUNT(*) AS rows, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d FROM account_user_daily"
            )),
            "daily_msg_stats": dict(tbl(
                "SELECT COUNT(*) AS rows, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d FROM account_message_stats"
            )),
            "daily_stats": dict(tbl(
                "SELECT COUNT(*) AS rows, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d FROM account_daily_metrics"
            )),
            "article_source_stats": dict(tbl(
                "SELECT COUNT(*) AS rows, MIN(publish_date) AS min_d, MAX(publish_date) AS max_d FROM article_master"
            )),
            "article_detail": dict(tbl(
                "SELECT COUNT(*) AS rows, MIN(publish_date) AS min_d, MAX(publish_date) AS max_d FROM article_master"
            )),
            "import_history": dict(tbl(
                "SELECT COUNT(*) AS rows, MIN(imported_at) AS min_d, MAX(imported_at) AS max_d FROM import_history"
            )),
        }
        conn.close()
        try:
            result["db_size_mb"] = round(MASTER_DB_PATH.stat().st_size / 1024 / 1024, 2)
        except Exception:
            result["db_size_mb"] = 0
        return result

    conn = get_conn()
    def tbl(sql):
        return conn.execute(sql).fetchone()

    result = {
        "daily_reads": dict(tbl(
            "SELECT COUNT(*) AS rows, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d FROM daily_reads WHERE channel='全部'"
        )),
        "daily_user_stats": dict(tbl(
            "SELECT COUNT(*) AS rows, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d FROM daily_user_stats"
        )),
        "daily_msg_stats": dict(tbl(
            "SELECT COUNT(*) AS rows, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d FROM daily_msg_stats"
        )),
        "daily_stats": dict(tbl(
            "SELECT COUNT(*) AS rows, MIN(stat_date) AS min_d, MAX(stat_date) AS max_d FROM daily_stats"
        )),
        "article_source_stats": dict(tbl(
            "SELECT COUNT(DISTINCT title) AS rows, MIN(publish_date) AS min_d, MAX(publish_date) AS max_d FROM article_source_stats WHERE channel='全部'"
        )),
        "article_detail": dict(tbl(
            "SELECT COUNT(*) AS rows, NULL AS min_d, NULL AS max_d FROM article_detail"
        )),
        "import_history": dict(tbl(
            "SELECT COUNT(*) AS rows, MIN(imported_at) AS min_d, MAX(imported_at) AS max_d FROM import_history"
        )),
    }
    conn.close()
    # 查数据库文件大小
    try:
        result["db_size_mb"] = round(DB_PATH.stat().st_size / 1024 / 1024, 2)
    except Exception:
        result["db_size_mb"] = 0
    return result



def delete_import_file(filename: str) -> dict:
    """删除某次导入文件产生的所有数据（通过 import_file 字段和 import_history 联动）。"""
    if _master_ready():
        from core.master_db import get_master_conn
        conn = get_master_conn()
        r1 = conn.execute(
            "DELETE FROM traffic_source_stats WHERE import_file=?", (filename,)
        ).rowcount
        r2 = conn.execute(
            "DELETE FROM article_master WHERE last_source_file=?", (filename,)
        ).rowcount
        r3 = conn.execute(
            "DELETE FROM import_history WHERE filename=?", (filename,)
        ).rowcount
        pending = conn.execute(
            "DELETE FROM pending_records WHERE source_file=?", (filename,)
        ).rowcount
        sync_runs = conn.execute(
            "DELETE FROM sync_runs WHERE source_file=?", (filename,)
        ).rowcount
        conn.commit()
        conn.close()
        return {"article_source": r1, "article_detail": r2, "history": r3, "pending": pending, "sync_runs": sync_runs}

    conn = get_conn()
    # article_source_stats 有 import_file 字段
    r1 = conn.execute(
        "DELETE FROM article_source_stats WHERE import_file=?", (filename,)
    ).rowcount
    r2 = conn.execute(
        "DELETE FROM article_detail WHERE import_file=?", (filename,)
    ).rowcount
    r3 = conn.execute(
        "DELETE FROM import_history WHERE filename=?", (filename,)
    ).rowcount
    conn.commit()
    conn.close()
    return {"article_source": r1, "article_detail": r2, "history": r3}
