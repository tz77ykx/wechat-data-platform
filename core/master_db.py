import json
import re
import sqlite3
from datetime import date

from core.competitor_identity import canonicalize_competitor_name, competitor_matrix_name
from config import DB_PATH, MASTER_DB_PATH


def get_master_conn():
    conn = sqlite3.connect(str(MASTER_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_legacy_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _has_distinct_legacy_db():
    try:
        return DB_PATH.exists() and DB_PATH.resolve() != MASTER_DB_PATH.resolve()
    except FileNotFoundError:
        return False


def _legacy_table_exists(table_name):
    if not _has_distinct_legacy_db():
        return False
    conn = get_legacy_conn()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    conn.close()
    return bool(row)


def normalize_publish_date(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value.replace("/", "-")


def _normalize_stored_publish_dates(conn):
    conn.execute(
        """UPDATE article_master
           SET publish_date=REPLACE(publish_date, '/', '-'),
               updated_at=CURRENT_TIMESTAMP
           WHERE publish_date LIKE '%/%'"""
    )
    conn.execute(
        """UPDATE traffic_source_stats
           SET publish_date=REPLACE(publish_date, '/', '-'),
               updated_at=CURRENT_TIMESTAMP
           WHERE publish_date LIKE '%/%'"""
    )
    conn.execute(
        """UPDATE article_msgids
           SET publish_date=REPLACE(publish_date, '/', '-'),
               fetched_at=CURRENT_TIMESTAMP
           WHERE publish_date LIKE '%/%'"""
    )
    conn.execute(
        """UPDATE article_overrides
           SET override_value=REPLACE(override_value, '/', '-'),
               updated_at=CURRENT_TIMESTAMP
           WHERE field_name='publish_date' AND override_value LIKE '%/%'"""
    )


def init_master_db():
    conn = get_master_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS article_master (
            id INTEGER PRIMARY KEY,
            msgid TEXT,
            canonical_title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            publish_date DATE,
            total_reads INTEGER DEFAULT 0,
            share_user INTEGER DEFAULT 0,
            like_user INTEGER DEFAULT 0,
            thumbup_user INTEGER DEFAULT 0,
            fav_user INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            follow_after_read INTEGER DEFAULT 0,
            deliver_user INTEGER DEFAULT 0,
            msg_read_user INTEGER DEFAULT 0,
            first_share_user INTEGER DEFAULT 0,
            total_share_user INTEGER DEFAULT 0,
            share_read_user INTEGER DEFAULT 0,
            source_count INTEGER DEFAULT 0,
            is_overridden INTEGER DEFAULT 0,
            last_source_file TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_article_master_msgid
        ON article_master(msgid)
        WHERE msgid IS NOT NULL AND msgid != '';

        CREATE UNIQUE INDEX IF NOT EXISTS idx_article_master_title_date
        ON article_master(normalized_title, publish_date)
        WHERE publish_date IS NOT NULL;

        CREATE TABLE IF NOT EXISTS article_diagnostics (
            id INTEGER PRIMARY KEY,
            article_id INTEGER NOT NULL UNIQUE,
            avg_read_time INTEGER DEFAULT 0,
            complete_rate REAL,
            rec_reads INTEGER DEFAULT 0,
            rec_ratio REAL,
            open_rate REAL,
            latest_snapshot_at DATETIME,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(article_id) REFERENCES article_master(id)
        );

        CREATE TABLE IF NOT EXISTS traffic_source_stats (
            id INTEGER PRIMARY KEY,
            article_id INTEGER,
            publish_date DATE,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            channel TEXT NOT NULL,
            read_user INTEGER DEFAULT 0,
            read_ratio REAL,
            import_file TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(publish_date, normalized_title, channel),
            FOREIGN KEY(article_id) REFERENCES article_master(id)
        );

        CREATE TABLE IF NOT EXISTS account_daily_metrics (
            id INTEGER PRIMARY KEY,
            stat_date DATE NOT NULL UNIQUE,
            total_read_user INTEGER DEFAULT 0,
            share_user INTEGER DEFAULT 0,
            original_read_user INTEGER DEFAULT 0,
            fav_user INTEGER DEFAULT 0,
            article_count INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS account_channel_daily (
            id INTEGER PRIMARY KEY,
            stat_date DATE NOT NULL,
            channel TEXT NOT NULL,
            read_user INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stat_date, channel)
        );

        CREATE TABLE IF NOT EXISTS account_user_daily (
            id INTEGER PRIMARY KEY,
            stat_date DATE NOT NULL UNIQUE,
            new_user INTEGER DEFAULT 0,
            cancel_user INTEGER DEFAULT 0,
            net_user INTEGER DEFAULT 0,
            total_user INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS account_menu_stats (
            id INTEGER PRIMARY KEY,
            menu_version TEXT NOT NULL,
            menu_level1 TEXT,
            menu_level2 TEXT,
            click_count INTEGER DEFAULT 0,
            click_user INTEGER DEFAULT 0,
            avg_click REAL DEFAULT 0,
            import_date DATE,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(menu_version, menu_level1, menu_level2)
        );

        CREATE TABLE IF NOT EXISTS account_message_stats (
            id INTEGER PRIMARY KEY,
            stat_date DATE NOT NULL UNIQUE,
            msg_user INTEGER DEFAULT 0,
            msg_count INTEGER DEFAULT 0,
            avg_msg REAL DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS import_history (
            id INTEGER PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            date_range TEXT,
            rows_imported INTEGER DEFAULT 0,
            imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS article_msgids (
            id INTEGER PRIMARY KEY,
            msgid TEXT NOT NULL UNIQUE,
            title TEXT,
            normalized_title TEXT,
            publish_date DATE,
            detail_downloaded INTEGER DEFAULT 0,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS article_trend (
            id INTEGER PRIMARY KEY,
            article_id INTEGER,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            stat_date DATE NOT NULL,
            channel TEXT NOT NULL,
            read_user INTEGER DEFAULT 0,
            share_user INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(normalized_title, stat_date, channel),
            FOREIGN KEY(article_id) REFERENCES article_master(id)
        );

        CREATE TABLE IF NOT EXISTS article_tags (
            id INTEGER PRIMARY KEY,
            article_id INTEGER,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(normalized_title, tag),
            FOREIGN KEY(article_id) REFERENCES article_master(id)
        );

        CREATE TABLE IF NOT EXISTS planned_articles (
            id INTEGER PRIMARY KEY,
            plan_date DATE NOT NULL,
            topic TEXT NOT NULL,
            note TEXT,
            status TEXT DEFAULT 'planned',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS anomaly_log (
            id INTEGER PRIMARY KEY,
            log_date DATE NOT NULL UNIQUE,
            today_reads INTEGER DEFAULT 0,
            avg7_reads INTEGER DEFAULT 0,
            pct REAL,
            direction TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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

        CREATE TABLE IF NOT EXISTS competitor_accounts (
            id INTEGER PRIMARY KEY,
            nickname TEXT NOT NULL UNIQUE,
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
            UNIQUE(account_id, title),
            FOREIGN KEY(account_id) REFERENCES competitor_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS article_overrides (
            id INTEGER PRIMARY KEY,
            article_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            override_value TEXT NOT NULL,
            reason TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(article_id, field_name),
            FOREIGN KEY(article_id) REFERENCES article_master(id)
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_file TEXT,
            inserted_count INTEGER DEFAULT 0,
            updated_count INTEGER DEFAULT 0,
            notes TEXT,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pending_records (
            id INTEGER PRIMARY KEY,
            source_file TEXT,
            record_type TEXT,
            article_hint TEXT,
            issue_type TEXT NOT NULL,
            issue_message TEXT NOT NULL,
            payload_json TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(article_diagnostics)").fetchall()
    }
    if "detail_snapshot_at" not in columns:
        conn.execute("ALTER TABLE article_diagnostics ADD COLUMN detail_snapshot_at DATETIME")
    _ensure_table_column(conn, "article_predictions", "g_score", "INTEGER")
    _ensure_table_column(conn, "competitor_accounts", "matrix_name", "TEXT")
    _normalize_competitor_accounts(conn)
    _ensure_table_column(conn, "competitor_articles", "manual_analysis_status", "TEXT DEFAULT 'pending'")
    _ensure_table_column(conn, "competitor_articles", "manual_analysis_summary", "TEXT")
    _ensure_table_column(conn, "competitor_articles", "manual_analysis_notes", "TEXT")
    _ensure_table_column(conn, "competitor_articles", "manual_analysis_updated_at", "DATETIME")
    conn.execute(
        """UPDATE article_diagnostics
           SET detail_snapshot_at=COALESCE(detail_snapshot_at, latest_snapshot_at),
               updated_at=CURRENT_TIMESTAMP
           WHERE detail_snapshot_at IS NULL
             AND (
                 COALESCE(avg_read_time, 0) > 0
                 OR complete_rate IS NOT NULL
                 OR open_rate IS NOT NULL
                 OR article_id IN (
                     SELECT id
                     FROM article_master
                     WHERE COALESCE(share_user, 0) > 0
                        OR COALESCE(like_user, 0) > 0
                        OR COALESCE(thumbup_user, 0) > 0
                        OR COALESCE(fav_user, 0) > 0
                        OR COALESCE(comment_count, 0) > 0
                        OR COALESCE(follow_after_read, 0) > 0
                        OR COALESCE(deliver_user, 0) > 0
                        OR COALESCE(msg_read_user, 0) > 0
                        OR COALESCE(first_share_user, 0) > 0
                        OR COALESCE(total_share_user, 0) > 0
                        OR COALESCE(share_read_user, 0) > 0
                 )
             )"""
    )
    _normalize_stored_publish_dates(conn)
    conn.commit()
    conn.close()


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


def _merge_competitor_accounts(conn, source_id: int, target_id: int):
    rows = conn.execute(
        "SELECT id FROM competitor_articles WHERE account_id = ?",
        (source_id,),
    ).fetchall()
    for row in rows:
        try:
            conn.execute(
                "UPDATE competitor_articles SET account_id = ? WHERE id = ?",
                (target_id, row["id"]),
            )
        except sqlite3.IntegrityError:
            conn.execute("DELETE FROM competitor_articles WHERE id = ?", (row["id"],))
    conn.execute("DELETE FROM competitor_accounts WHERE id = ?", (source_id,))


def normalize_title(title):
    raw = (title or "").strip()
    raw = raw.replace("\u3000", " ")
    raw = re.sub(r"\s+", "", raw)
    return raw.casefold()


def _max_int(current, incoming):
    current = current or 0
    incoming = incoming or 0
    return max(int(current), int(incoming))


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


DETAIL_ONLY_FIELDS = (
    "share_user",
    "like_user",
    "thumbup_user",
    "fav_user",
    "comment_count",
    "follow_after_read",
    "deliver_user",
    "msg_read_user",
    "first_share_user",
    "total_share_user",
    "share_read_user",
    "avg_read_time",
    "complete_rate",
    "complete_rate_pct",
    "open_rate",
)


def _apply_detail_snapshot_semantics(item):
    has_detail_snapshot = bool(item.get("detail_snapshot_at"))
    item["has_detail_snapshot"] = has_detail_snapshot
    if not has_detail_snapshot:
        for field in DETAIL_ONLY_FIELDS:
            if field in item:
                item[field] = None
    return item


def _record_pending(conn, source_file, record_type, article_hint, issue_type, issue_message, payload=None):
    conn.execute(
        """INSERT INTO pending_records
           (source_file, record_type, article_hint, issue_type, issue_message, payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            source_file,
            record_type,
            article_hint,
            issue_type,
            issue_message,
            json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        ),
    )


def _lookup_identity(title):
    if not title:
        return {}

    conn = get_master_conn()
    normalized_title = normalize_title(title)
    row = conn.execute(
        """SELECT msgid, publish_date
           FROM article_msgids
           WHERE normalized_title=? OR title=?
           ORDER BY fetched_at DESC
           LIMIT 1""",
        (normalized_title, title),
    ).fetchone()
    if not row:
        row = conn.execute(
            """SELECT msgid, publish_date
               FROM article_master
               WHERE normalized_title=?
               ORDER BY updated_at DESC
               LIMIT 1""",
            (normalized_title,),
    ).fetchone()
    conn.close()
    if row:
        identity = dict(row)
        identity["publish_date"] = normalize_publish_date(identity.get("publish_date"))
        return identity

    if not _has_distinct_legacy_db():
        return {}
    legacy = get_legacy_conn()
    row = None
    if _legacy_table_exists("article_msgids"):
        row = legacy.execute(
            """SELECT msgid, publish_date
               FROM article_msgids
               WHERE title=?
               ORDER BY fetched_at DESC
               LIMIT 1""",
            (title,),
        ).fetchone()
    if not row and _legacy_table_exists("article_source_stats"):
        row = legacy.execute(
            """SELECT NULL AS msgid, publish_date
               FROM article_source_stats
               WHERE title=? AND channel='全部'
               ORDER BY publish_date DESC
               LIMIT 1""",
            (title,),
        ).fetchone()
    legacy.close()
    if not row:
        return {}
    identity = dict(row)
    identity["publish_date"] = normalize_publish_date(identity.get("publish_date"))
    return identity


def _find_existing_article(conn, title=None, publish_date=None, msgid=None):
    publish_date = normalize_publish_date(publish_date)
    if msgid:
        row = conn.execute(
            "SELECT * FROM article_master WHERE msgid=?",
            (msgid,),
        ).fetchone()
        if row:
            return row

    normalized = normalize_title(title)
    if publish_date:
        row = conn.execute(
            """SELECT * FROM article_master
               WHERE normalized_title=? AND publish_date=?""",
            (normalized, publish_date),
        ).fetchone()
        if row:
            return row

    if normalized:
        rows = conn.execute(
            "SELECT * FROM article_master WHERE normalized_title=?",
            (normalized,),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]
    return None


def _ensure_article(conn, title, publish_date=None, msgid=None):
    identity = {}
    if not publish_date or not msgid:
        identity = _lookup_identity(title)
    publish_date = normalize_publish_date(publish_date or identity.get("publish_date"))
    msgid = msgid or identity.get("msgid")

    existing = _find_existing_article(conn, title=title, publish_date=publish_date, msgid=msgid)
    normalized = normalize_title(title)
    if existing:
        updates = []
        values = []
        if title and title != existing["canonical_title"]:
            updates.append("canonical_title=?")
            values.append(title)
        if publish_date and not existing["publish_date"]:
            updates.append("publish_date=?")
            values.append(publish_date)
        if msgid and not existing["msgid"]:
            updates.append("msgid=?")
            values.append(msgid)
        if updates:
            updates.extend(["normalized_title=?", "updated_at=CURRENT_TIMESTAMP"])
            values.extend([normalized, existing["id"]])
            conn.execute(
                f"UPDATE article_master SET {', '.join(updates)} WHERE id=?",
                values,
            )
            existing = conn.execute(
                "SELECT * FROM article_master WHERE id=?",
                (existing["id"],),
            ).fetchone()
        return existing, False

    conn.execute(
        """INSERT INTO article_master
           (msgid, canonical_title, normalized_title, publish_date)
           VALUES (?, ?, ?, ?)""",
        (msgid, title, normalized, publish_date),
    )
    article_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute(
        "SELECT * FROM article_master WHERE id=?",
        (article_id,),
    ).fetchone()
    return row, True


def _upsert_article_master_from_sources(conn, grouped_sources, source_file):
    inserted = 0
    updated = 0

    for (title, publish_date), records in grouped_sources.items():
        publish_date = normalize_publish_date(publish_date)
        if not title or not publish_date:
            _record_pending(
                conn,
                source_file,
                "article_source",
                title or "",
                "missing_identity",
                "文章来源记录缺少标题或发布日期",
                records,
            )
            continue

        article, created = _ensure_article(conn, title, publish_date=publish_date)
        if created:
            inserted += 1

        total_reads = 0
        rec_reads = 0
        for rec in records:
            channel = rec.get("channel") or ""
            reads = int(rec.get("read_user") or 0)
            if channel == "全部":
                total_reads = max(total_reads, reads)
            if channel == "推荐":
                rec_reads = max(rec_reads, reads)

            conn.execute(
                """INSERT INTO traffic_source_stats
                   (article_id, publish_date, title, normalized_title, channel, read_user, read_ratio, import_file, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(publish_date, normalized_title, channel)
                   DO UPDATE SET
                       article_id=excluded.article_id,
                       title=excluded.title,
                       read_user=MAX(traffic_source_stats.read_user, excluded.read_user),
                       read_ratio=excluded.read_ratio,
                       import_file=excluded.import_file,
                       updated_at=CURRENT_TIMESTAMP""",
                (
                    article["id"],
                    publish_date,
                    title,
                    normalize_title(title),
                    channel,
                    reads,
                    rec.get("read_ratio"),
                    source_file,
                ),
            )

        current = conn.execute(
            "SELECT * FROM article_master WHERE id=?",
            (article["id"],),
        ).fetchone()
        new_total_reads = _max_int(current["total_reads"], total_reads)
        source_count = len({(r.get("channel") or "").strip() for r in records if (r.get("channel") or "").strip()})

        conn.execute(
            """UPDATE article_master
               SET total_reads=?,
                   source_count=MAX(source_count, ?),
                   last_source_file=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (new_total_reads, source_count, source_file, article["id"]),
        )

        diag = conn.execute(
            "SELECT * FROM article_diagnostics WHERE article_id=?",
            (article["id"],),
        ).fetchone()
        rec_ratio = round(rec_reads / new_total_reads, 4) if new_total_reads else None
        if diag:
            conn.execute(
                """UPDATE article_diagnostics
                   SET rec_reads=MAX(rec_reads, ?),
                       rec_ratio=?,
                       latest_snapshot_at=CURRENT_TIMESTAMP,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE article_id=?""",
                (rec_reads, rec_ratio, article["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO article_diagnostics
                   (article_id, rec_reads, rec_ratio, latest_snapshot_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (article["id"], rec_reads, rec_ratio),
            )
        updated += 1

    return inserted, updated


def _attach_source_records_to_article(conn, article_id, records, source_file):
    article = conn.execute(
        "SELECT * FROM article_master WHERE id=?",
        (article_id,),
    ).fetchone()
    if not article:
        raise ValueError("目标文章不存在")

    canonical_title = article["canonical_title"]
    publish_date = article["publish_date"]
    total_reads = article["total_reads"] or 0
    rec_reads = 0
    seen_channels = set()

    for rec in records:
        record_title = rec.get("title") or canonical_title
        record_publish_date = rec.get("publish_date") or publish_date
        if not record_publish_date:
            raise ValueError("来源记录缺少发布日期")
        channel = (rec.get("channel") or "").strip() or "未知"
        reads = int(rec.get("read_user") or 0)
        seen_channels.add(channel)

        conn.execute(
            """INSERT INTO traffic_source_stats
               (article_id, publish_date, title, normalized_title, channel, read_user, read_ratio, import_file, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(publish_date, normalized_title, channel)
               DO UPDATE SET
                   article_id=excluded.article_id,
                   title=excluded.title,
                   read_user=MAX(traffic_source_stats.read_user, excluded.read_user),
                   read_ratio=excluded.read_ratio,
                   import_file=excluded.import_file,
                   updated_at=CURRENT_TIMESTAMP""",
            (
                article_id,
                record_publish_date,
                canonical_title,
                normalize_title(canonical_title),
                channel,
                reads,
                rec.get("read_ratio"),
                source_file,
            ),
        )

        if channel == "全部":
            total_reads = max(total_reads, reads)
        if channel == "推荐":
            rec_reads = max(rec_reads, reads)

    conn.execute(
        """UPDATE article_master
           SET canonical_title=?,
               normalized_title=?,
               publish_date=COALESCE(publish_date, ?),
               total_reads=?,
               source_count=MAX(source_count, ?),
               last_source_file=?,
               updated_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            canonical_title,
            normalize_title(canonical_title),
            publish_date,
            total_reads,
            len(seen_channels),
            source_file,
            article_id,
        ),
    )

    diag = conn.execute(
        "SELECT * FROM article_diagnostics WHERE article_id=?",
        (article_id,),
    ).fetchone()
    rec_ratio = round(rec_reads / total_reads, 4) if total_reads and rec_reads else None
    if diag:
        conn.execute(
            """UPDATE article_diagnostics
               SET rec_reads=MAX(rec_reads, ?),
                   rec_ratio=?,
                   latest_snapshot_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP
               WHERE article_id=?""",
            (rec_reads, rec_ratio, article_id),
        )
    else:
        conn.execute(
            """INSERT INTO article_diagnostics
               (article_id, rec_reads, rec_ratio, latest_snapshot_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
            (article_id, rec_reads, rec_ratio),
        )


def _upsert_article_master_from_detail(conn, detail, source_file):
    title = (detail.get("title") or "").strip()
    if not title:
        _record_pending(
            conn,
            source_file,
            "article_detail",
            "",
            "missing_title",
            "单篇详情缺少标题",
            detail,
        )
        return 0, 0

    article, created = _ensure_article(conn, title)
    current = conn.execute(
        "SELECT * FROM article_master WHERE id=?",
        (article["id"],),
    ).fetchone()

    updates = {
        "total_reads": _max_int(current["total_reads"], detail.get("read_user")),
        "share_user": _max_int(current["share_user"], detail.get("share_user")),
        "like_user": _max_int(current["like_user"], detail.get("like_user")),
        "thumbup_user": _max_int(current["thumbup_user"], detail.get("thumbup_user")),
        "fav_user": _max_int(current["fav_user"], detail.get("fav_user")),
        "comment_count": _max_int(current["comment_count"], detail.get("comment_count")),
        "follow_after_read": _max_int(current["follow_after_read"], detail.get("follow_after_read")),
        "deliver_user": _max_int(current["deliver_user"], detail.get("deliver_user")),
        "msg_read_user": _max_int(current["msg_read_user"], detail.get("msg_read_user")),
        "first_share_user": _max_int(current["first_share_user"], detail.get("first_share_user")),
        "total_share_user": _max_int(current["total_share_user"], detail.get("total_share_user")),
        "share_read_user": _max_int(current["share_read_user"], detail.get("share_read_user")),
    }

    conn.execute(
        """UPDATE article_master
           SET total_reads=?, share_user=?, like_user=?, thumbup_user=?, fav_user=?,
               comment_count=?, follow_after_read=?, deliver_user=?, msg_read_user=?,
               first_share_user=?, total_share_user=?, share_read_user=?,
               last_source_file=?, updated_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            updates["total_reads"],
            updates["share_user"],
            updates["like_user"],
            updates["thumbup_user"],
            updates["fav_user"],
            updates["comment_count"],
            updates["follow_after_read"],
            updates["deliver_user"],
            updates["msg_read_user"],
            updates["first_share_user"],
            updates["total_share_user"],
            updates["share_read_user"],
            source_file,
            article["id"],
        ),
    )

    total_reads = updates["total_reads"]
    rec_diag = conn.execute(
        "SELECT * FROM article_diagnostics WHERE article_id=?",
        (article["id"],),
    ).fetchone()
    rec_reads = rec_diag["rec_reads"] if rec_diag else 0
    rec_ratio = round(rec_reads / total_reads, 4) if total_reads and rec_reads else None
    open_rate = None
    if updates["deliver_user"]:
        open_rate = round(updates["msg_read_user"] / updates["deliver_user"], 4)

    if rec_diag:
        conn.execute(
            """UPDATE article_diagnostics
               SET avg_read_time=?,
                   complete_rate=?,
                   rec_ratio=?,
                   open_rate=?,
                   detail_snapshot_at=CURRENT_TIMESTAMP,
                   latest_snapshot_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP
               WHERE article_id=?""",
            (
                detail.get("avg_read_time") or rec_diag["avg_read_time"],
                _safe_float(detail.get("complete_rate")),
                rec_ratio,
                open_rate,
                article["id"],
            ),
        )
    else:
        conn.execute(
            """INSERT INTO article_diagnostics
               (article_id, avg_read_time, complete_rate, rec_reads, rec_ratio, open_rate, detail_snapshot_at, latest_snapshot_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (
                article["id"],
                detail.get("avg_read_time") or 0,
                _safe_float(detail.get("complete_rate")),
                rec_reads,
                rec_ratio,
                open_rate,
            ),
        )

    return (1 if created else 0), 1


def _upsert_article_trend_records(conn, title, records, source_file):
    if not title:
        return 0

    article, _ = _ensure_article(conn, title)
    normalized_title = normalize_title(title)
    updated = 0
    for row in records or []:
        stat_date = row.get("stat_date")
        channel = (row.get("channel") or "").strip()
        if not stat_date or not channel:
            continue
        conn.execute(
            """INSERT INTO article_trend
               (article_id, title, normalized_title, stat_date, channel, read_user, share_user, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(normalized_title, stat_date, channel) DO UPDATE SET
                   article_id=excluded.article_id,
                   title=excluded.title,
                   read_user=MAX(article_trend.read_user, excluded.read_user),
                   share_user=MAX(article_trend.share_user, excluded.share_user),
                   updated_at=CURRENT_TIMESTAMP""",
            (
                article["id"],
                article["canonical_title"],
                normalized_title,
                stat_date,
                channel,
                int(row.get("read_user") or 0),
                int(row.get("share_user") or 0),
            ),
        )
        updated += 1
    return updated


def _upsert_account_daily(conn, daily_reads, daily_stats):
    stats_by_date = {row["stat_date"]: dict(row) for row in daily_stats}
    for read in daily_reads:
        stat_date = read.get("stat_date")
        channel = read.get("channel")
        if not stat_date or not channel:
            continue
        conn.execute(
            """INSERT INTO account_channel_daily
               (stat_date, channel, read_user, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(stat_date, channel) DO UPDATE SET
                   read_user=MAX(account_channel_daily.read_user, excluded.read_user),
                   updated_at=CURRENT_TIMESTAMP""",
            (stat_date, channel, int(read.get("read_user") or 0)),
        )

        if (read.get("channel") or "") != "全部":
            continue
        stat_row = stats_by_date.get(stat_date, {})
        conn.execute(
            """INSERT INTO account_daily_metrics
               (stat_date, total_read_user, share_user, original_read_user, fav_user, article_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(stat_date) DO UPDATE SET
                   total_read_user=MAX(account_daily_metrics.total_read_user, excluded.total_read_user),
                   share_user=MAX(account_daily_metrics.share_user, excluded.share_user),
                   original_read_user=MAX(account_daily_metrics.original_read_user, excluded.original_read_user),
                   fav_user=MAX(account_daily_metrics.fav_user, excluded.fav_user),
                   article_count=MAX(account_daily_metrics.article_count, excluded.article_count),
                   updated_at=CURRENT_TIMESTAMP""",
            (
                stat_date,
                int(read.get("read_user") or 0),
                int(stat_row.get("share_user") or 0),
                int(stat_row.get("original_read_user") or 0),
                int(stat_row.get("fav_user") or 0),
                int(stat_row.get("article_count") or 0),
            ),
        )


def _upsert_history_row(conn, table, unique_field, row, columns):
    names = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    assignments = ", ".join(
        f"{col}=excluded.{col}" if col not in ("updated_at",) else "updated_at=CURRENT_TIMESTAMP"
        for col in columns
        if col != unique_field
    )
    values = [row.get(col) for col in columns]
    conn.execute(
        f"""INSERT INTO {table} ({names})
            VALUES ({placeholders})
            ON CONFLICT({unique_field}) DO UPDATE SET {assignments}""",
        values,
    )


def _upsert_menu_row(conn, row):
    conn.execute(
        """INSERT INTO account_menu_stats
           (menu_version, menu_level1, menu_level2, click_count, click_user, avg_click, import_date, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(menu_version, menu_level1, menu_level2) DO UPDATE SET
               click_count=MAX(account_menu_stats.click_count, excluded.click_count),
               click_user=MAX(account_menu_stats.click_user, excluded.click_user),
               avg_click=excluded.avg_click,
               import_date=excluded.import_date,
               updated_at=CURRENT_TIMESTAMP""",
        (
            row.get("menu_version"),
            row.get("menu_level1"),
            row.get("menu_level2"),
            int(row.get("click_count") or 0),
            int(row.get("click_user") or 0),
            _safe_float(row.get("avg_click")) or 0,
            row.get("import_date") or str(date.today()),
        ),
    )


def sync_master_from_import(ftype, data, source_file):
    init_master_db()
    conn = get_master_conn()
    inserted = 0
    updated = 0

    if ftype == "tendency":
        _upsert_account_daily(conn, data.get("daily_reads", []), data.get("daily_stats", []))
        grouped_sources = {}
        for rec in data.get("article_sources", []):
            key = (rec.get("title"), rec.get("publish_date"))
            key = (rec.get("title"), normalize_publish_date(rec.get("publish_date")))
            grouped_sources.setdefault(key, []).append(rec)
        ins, upd = _upsert_article_master_from_sources(conn, grouped_sources, source_file)
        inserted += ins
        updated += upd

    elif ftype == "article_detail":
        ins, upd = _upsert_article_master_from_detail(conn, data.get("detail", {}), source_file)
        inserted += ins
        updated += upd
        updated += _upsert_article_trend_records(
            conn,
            (data.get("detail") or {}).get("title"),
            data.get("trend", []),
            source_file,
        )

    elif ftype == "user":
        for row in data.get("records", []):
            _upsert_history_row(
                conn,
                "account_user_daily",
                "stat_date",
                {**row, "updated_at": None},
                ["stat_date", "new_user", "cancel_user", "net_user", "total_user", "updated_at"],
            )
            updated += 1

    elif ftype == "msg":
        for row in data.get("records", []):
            _upsert_history_row(
                conn,
                "account_message_stats",
                "stat_date",
                {**row, "updated_at": None},
                ["stat_date", "msg_user", "msg_count", "avg_msg", "updated_at"],
            )
            updated += 1

    elif ftype == "menu":
        for row in data.get("records", []):
            _upsert_menu_row(conn, row)
            updated += 1

    else:
        _record_pending(
            conn,
            source_file,
            ftype,
            "",
            "unknown_type",
            f"未知导入类型: {ftype}",
            data,
        )

    conn.execute(
        """INSERT INTO sync_runs
           (source_type, source_file, inserted_count, updated_count, notes, finished_at)
           VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (ftype, source_file, inserted, updated, None),
    )
    conn.commit()
    conn.close()
    return {"inserted": inserted, "updated": updated}


def bootstrap_master_from_analytics():
    init_master_db()
    if not _has_distinct_legacy_db() or not _legacy_table_exists("daily_reads"):
        conn = get_master_conn()
        summary = {
            "articles": conn.execute("SELECT COUNT(*) FROM article_master").fetchone()[0],
            "daily_metrics": conn.execute("SELECT COUNT(*) FROM account_daily_metrics").fetchone()[0],
            "users": conn.execute("SELECT COUNT(*) FROM account_user_daily").fetchone()[0],
            "messages": conn.execute("SELECT COUNT(*) FROM account_message_stats").fetchone()[0],
            "menus": conn.execute("SELECT COUNT(*) FROM account_menu_stats").fetchone()[0],
        }
        conn.close()
        return summary

    legacy = get_legacy_conn()

    daily_reads = [dict(row) for row in legacy.execute("SELECT stat_date, channel, read_user FROM daily_reads").fetchall()]
    daily_stats = [dict(row) for row in legacy.execute(
        "SELECT stat_date, share_user, original_read_user, fav_user, article_count FROM daily_stats"
    ).fetchall()]
    source_rows = [dict(row) for row in legacy.execute(
        "SELECT publish_date, title, channel, read_user, read_ratio FROM article_source_stats"
    ).fetchall()]
    detail_rows = [dict(row) for row in legacy.execute(
        """SELECT title, read_user, avg_read_time, complete_rate, follow_after_read,
                  share_user, like_user, thumbup_user, fav_user, comment_count,
                  deliver_user, msg_read_user, first_share_user, total_share_user, share_read_user
           FROM article_detail"""
    ).fetchall()]
    user_rows = [dict(row) for row in legacy.execute(
        "SELECT stat_date, new_user, cancel_user, net_user, total_user FROM daily_user_stats"
    ).fetchall()]
    msg_rows = [dict(row) for row in legacy.execute(
        "SELECT stat_date, msg_user, msg_count, avg_msg FROM daily_msg_stats"
    ).fetchall()]
    menu_rows = [dict(row) for row in legacy.execute(
        "SELECT menu_version, menu_level1, menu_level2, click_count, click_user, avg_click, import_date FROM menu_stats"
    ).fetchall()]
    import_rows = [dict(row) for row in legacy.execute(
        "SELECT filename, date_range, rows_imported, imported_at FROM import_history"
    ).fetchall()]
    setting_rows = [dict(row) for row in legacy.execute(
        "SELECT key, value FROM settings"
    ).fetchall()]
    msgid_rows = [dict(row) for row in legacy.execute(
        "SELECT msgid, title, publish_date, detail_downloaded, fetched_at FROM article_msgids"
    ).fetchall()]
    trend_rows = [dict(row) for row in legacy.execute(
        "SELECT title, stat_date, channel, read_user, share_user FROM article_trend"
    ).fetchall()]
    tag_rows = [dict(row) for row in legacy.execute(
        "SELECT title, tag, created_at FROM article_tags"
    ).fetchall()]
    plan_rows = [dict(row) for row in legacy.execute(
        "SELECT id, plan_date, topic, note, status, created_at FROM planned_articles"
    ).fetchall()]
    anomaly_rows = [dict(row) for row in legacy.execute(
        "SELECT log_date, today_reads, avg7_reads, pct, direction, created_at FROM anomaly_log"
    ).fetchall()]
    prediction_rows = [dict(row) for row in legacy.execute(
        "SELECT * FROM article_predictions"
    ).fetchall()]
    competitor_accounts = [dict(row) for row in legacy.execute(
        "SELECT * FROM competitor_accounts"
    ).fetchall()]
    competitor_articles = [dict(row) for row in legacy.execute(
        "SELECT * FROM competitor_articles"
    ).fetchall()]
    legacy.close()

    sync_master_from_import(
        "tendency",
        {"daily_reads": daily_reads, "daily_stats": daily_stats, "article_sources": source_rows},
        "bootstrap:analytics",
    )
    for row in detail_rows:
        sync_master_from_import("article_detail", {"detail": row, "trend": []}, "bootstrap:detail")
    if user_rows:
        sync_master_from_import("user", {"records": user_rows}, "bootstrap:user")
    if msg_rows:
        sync_master_from_import("msg", {"records": msg_rows}, "bootstrap:msg")
    if menu_rows:
        sync_master_from_import("menu", {"records": menu_rows}, "bootstrap:menu")

    conn = get_master_conn()
    for row in import_rows:
        conn.execute(
            """INSERT INTO import_history (filename, date_range, rows_imported, imported_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(filename) DO UPDATE SET
                   date_range=excluded.date_range,
                   rows_imported=excluded.rows_imported,
                   imported_at=excluded.imported_at""",
            (row.get("filename"), row.get("date_range"), row.get("rows_imported") or 0, row.get("imported_at")),
        )
    for row in setting_rows:
        conn.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   updated_at=CURRENT_TIMESTAMP""",
            (row.get("key"), row.get("value")),
        )
    for row in msgid_rows:
        conn.execute(
            """INSERT INTO article_msgids (msgid, title, normalized_title, publish_date, detail_downloaded, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(msgid) DO UPDATE SET
                   title=excluded.title,
                   normalized_title=excluded.normalized_title,
                   publish_date=excluded.publish_date,
                   detail_downloaded=MAX(article_msgids.detail_downloaded, excluded.detail_downloaded),
                   fetched_at=excluded.fetched_at""",
            (
                row.get("msgid"),
                row.get("title"),
                normalize_title(row.get("title")),
                row.get("publish_date"),
                int(row.get("detail_downloaded") or 0),
                row.get("fetched_at"),
            ),
        )
    for row in trend_rows:
        _upsert_article_trend_records(conn, row.get("title"), [row], "bootstrap:trend")
    for row in tag_rows:
        title = row.get("title") or ""
        article = _find_existing_article(conn, title=title) if title else None
        conn.execute(
            """INSERT INTO article_tags (article_id, title, normalized_title, tag, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(normalized_title, tag) DO UPDATE SET
                   article_id=excluded.article_id,
                   title=excluded.title""",
            (
                article["id"] if article else None,
                title,
                normalize_title(title),
                row.get("tag"),
                row.get("created_at"),
            ),
        )
    for row in plan_rows:
        conn.execute(
            """INSERT INTO planned_articles (id, plan_date, topic, note, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(id) DO UPDATE SET
                   plan_date=excluded.plan_date,
                   topic=excluded.topic,
                   note=excluded.note,
                   status=excluded.status,
                   updated_at=CURRENT_TIMESTAMP""",
            (
                row.get("id"),
                row.get("plan_date"),
                row.get("topic"),
                row.get("note"),
                row.get("status") or "planned",
                row.get("created_at"),
            ),
        )
    for row in anomaly_rows:
        conn.execute(
            """INSERT INTO anomaly_log (log_date, today_reads, avg7_reads, pct, direction, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(log_date) DO UPDATE SET
                   today_reads=excluded.today_reads,
                   avg7_reads=excluded.avg7_reads,
                   pct=excluded.pct,
                   direction=excluded.direction""",
            (
                row.get("log_date"),
                row.get("today_reads") or 0,
                row.get("avg7_reads") or 0,
                row.get("pct"),
                row.get("direction"),
                row.get("created_at"),
            ),
        )
    for row in prediction_rows:
        columns = [
            "id", "title", "created_at", "a_score", "b_score", "c_score", "d_score", "e_score", "f_score", "g_score",
            "total_score", "path_type", "pred_reads", "pred_rec_pct", "pred_read_rate", "pred_comments",
            "actual_reads", "actual_rec_pct", "actual_read_rate", "actual_comments", "notes",
        ]
        names = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{col}=excluded.{col}" for col in columns if col != "id")
        conn.execute(
            f"""INSERT INTO article_predictions ({names})
                VALUES ({placeholders})
                ON CONFLICT(id) DO UPDATE SET {updates}""",
            [row.get(col) for col in columns],
        )
    for row in competitor_accounts:
        conn.execute(
            """INSERT INTO competitor_accounts (id, nickname, matrix_name, notes, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   nickname=excluded.nickname,
                   matrix_name=excluded.matrix_name,
                   notes=excluded.notes""",
            (row.get("id"), row.get("nickname"), row.get("matrix_name"), row.get("notes"), row.get("created_at")),
        )
    for row in competitor_articles:
        columns = [
            "id", "account_id", "title", "url", "publish_time", "like_num", "read_num",
            "share_num", "comment_count", "content_text", "viral_analysis", "created_at",
        ]
        names = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{col}=excluded.{col}" for col in columns if col != "id")
        conn.execute(
            f"""INSERT INTO competitor_articles ({names})
                VALUES ({placeholders})
                ON CONFLICT(id) DO UPDATE SET {updates}""",
            [row.get(col) for col in columns],
        )
    summary = {
        "articles": conn.execute("SELECT COUNT(*) FROM article_master").fetchone()[0],
        "daily_metrics": conn.execute("SELECT COUNT(*) FROM account_daily_metrics").fetchone()[0],
        "users": conn.execute("SELECT COUNT(*) FROM account_user_daily").fetchone()[0],
        "messages": conn.execute("SELECT COUNT(*) FROM account_message_stats").fetchone()[0],
        "menus": conn.execute("SELECT COUNT(*) FROM account_menu_stats").fetchone()[0],
    }
    conn.close()
    return summary


def query_master_summary():
    conn = get_master_conn()
    row = conn.execute(
        """SELECT
               COUNT(*) AS article_count,
               COALESCE(SUM(total_reads), 0) AS total_reads,
               COALESCE(SUM(CASE WHEN publish_date >= date('now', '-30 day') THEN 1 ELSE 0 END), 0) AS recent_articles,
               MAX(updated_at) AS last_synced_at
           FROM article_master"""
    ).fetchone()
    conn.close()
    return dict(row)


def query_master_articles(limit=200, q=None, order="latest", overridden=None, recent_only=False):
    conn = get_master_conn()
    clauses = []
    params = []
    if q:
        clauses.append("m.canonical_title LIKE ?")
        params.append(f"%{q}%")
    if overridden == "1":
        clauses.append("m.is_overridden=1")
    elif overridden == "0":
        clauses.append("m.is_overridden=0")
    if recent_only:
        clauses.append("m.publish_date >= date('now', '-30 day')")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order_by = (
        "m.publish_date DESC, m.updated_at DESC"
        if order == "latest"
        else "m.total_reads DESC, m.publish_date DESC"
    )
    rows = conn.execute(
        f"""SELECT m.id,
                   m.canonical_title,
                   m.publish_date,
                   m.total_reads,
                   m.share_user,
                   m.like_user,
                   m.thumbup_user,
                   m.fav_user,
                   m.comment_count,
                   m.follow_after_read,
                   m.is_overridden,
                   m.updated_at,
                   d.avg_read_time,
                   d.complete_rate,
                   d.rec_reads,
                   d.rec_ratio,
                   d.open_rate,
                   d.detail_snapshot_at
            FROM article_master
            m
            LEFT JOIN article_diagnostics d ON d.article_id = m.id
            {where}
            ORDER BY {order_by}
            LIMIT ?""",
        [*params, limit],
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        item["rec_pct"] = round((item["rec_ratio"] or 0) * 100, 1) if item["rec_ratio"] is not None else None
        item["complete_rate_pct"] = (
            round((item["complete_rate"] or 0) * 100, 1) if item["complete_rate"] is not None else None
        )
        item["stale"] = False
        item["stale_since"] = None
        _apply_detail_snapshot_semantics(item)
        result.append(item)
    return result


def query_master_diagnostics(limit=200):
    conn = get_master_conn()
    rows = conn.execute(
        """SELECT m.id, m.canonical_title, m.publish_date, m.total_reads,
                  d.avg_read_time, d.complete_rate, d.rec_reads, d.rec_ratio, d.open_rate, d.updated_at,
                  d.detail_snapshot_at
           FROM article_master m
           LEFT JOIN article_diagnostics d ON d.article_id = m.id
           ORDER BY m.publish_date DESC, m.updated_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        _apply_detail_snapshot_semantics(item)
        result.append(item)
    return result


def query_master_article_detail(article_id):
    conn = get_master_conn()
    row = conn.execute(
        """SELECT m.*, d.avg_read_time, d.complete_rate, d.rec_reads, d.rec_ratio, d.open_rate,
                  d.latest_snapshot_at, d.detail_snapshot_at
           FROM article_master m
           LEFT JOIN article_diagnostics d ON d.article_id = m.id
           WHERE m.id=?""",
        (article_id,),
    ).fetchone()
    sources = conn.execute(
        """SELECT publish_date, channel, read_user, read_ratio, import_file, updated_at
           FROM traffic_source_stats
           WHERE article_id=?
           ORDER BY channel""",
        (article_id,),
    ).fetchall()
    overrides = conn.execute(
        """SELECT field_name, override_value, reason, updated_at
           FROM article_overrides
           WHERE article_id=?
           ORDER BY field_name""",
        (article_id,),
    ).fetchall()
    conn.close()
    return {
        "article": _apply_detail_snapshot_semantics(dict(row)) if row else None,
        "sources": [dict(item) for item in sources],
        "overrides": [dict(item) for item in overrides],
    }


def query_account_daily_metrics(limit=90):
    conn = get_master_conn()
    rows = conn.execute(
        """SELECT stat_date, total_read_user, share_user, original_read_user, fav_user, article_count
           FROM account_daily_metrics
           ORDER BY stat_date DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_account_channel_daily(days=60, start_date=None, end_date=None):
    conn = get_master_conn()
    if start_date and end_date:
        rows = conn.execute(
            """SELECT stat_date, channel, read_user
               FROM account_channel_daily
               WHERE stat_date >= ? AND stat_date <= ?
               ORDER BY stat_date, channel""",
            (start_date, end_date),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT stat_date, channel, read_user
               FROM account_channel_daily
               WHERE stat_date >= date('now', ?)
               ORDER BY stat_date, channel""",
            (f"-{days} days",),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_account_user_daily(limit=90):
    conn = get_master_conn()
    rows = conn.execute(
        """SELECT stat_date, new_user, cancel_user, net_user, total_user
           FROM account_user_daily
           ORDER BY stat_date DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_account_menu_stats(limit=120):
    conn = get_master_conn()
    rows = conn.execute(
        """SELECT menu_version, menu_level1, menu_level2, click_count, click_user, avg_click, import_date
           FROM account_menu_stats
           ORDER BY import_date DESC, click_count DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_account_message_stats(limit=90):
    conn = get_master_conn()
    rows = conn.execute(
        """SELECT stat_date, msg_user, msg_count, avg_msg
           FROM account_message_stats
           ORDER BY stat_date DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_account_message_stats_range(days=90, start_date=None, end_date=None):
    conn = get_master_conn()
    if start_date and end_date:
        rows = conn.execute(
            """SELECT stat_date, msg_user, msg_count, avg_msg
               FROM account_message_stats
               WHERE stat_date >= ? AND stat_date <= ?
               ORDER BY stat_date""",
            (start_date, end_date),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT stat_date, msg_user, msg_count, avg_msg
               FROM account_message_stats
               WHERE stat_date >= date('now', ?)
               ORDER BY stat_date""",
            (f"-{days} days",),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_pending_records(limit=100):
    conn = get_master_conn()
    rows = conn.execute(
        """SELECT id, source_file, record_type, article_hint, issue_type, issue_message, status, created_at
           FROM pending_records
           ORDER BY created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_pending_record(pending_id):
    conn = get_master_conn()
    row = conn.execute(
        """SELECT id, source_file, record_type, article_hint, issue_type, issue_message, payload_json, status, created_at
           FROM pending_records
           WHERE id=?""",
        (pending_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    payload_json = item.pop("payload_json", None)
    try:
        item["payload"] = json.loads(payload_json) if payload_json else None
    except json.JSONDecodeError:
        item["payload"] = payload_json
    return item


def update_pending_status(pending_id, status):
    conn = get_master_conn()
    conn.execute(
        "UPDATE pending_records SET status=? WHERE id=?",
        (status, pending_id),
    )
    conn.commit()
    conn.close()
    return True


def resolve_pending_associate(pending_id, article_id):
    pending = get_pending_record(pending_id)
    if not pending:
        return False, "待确认记录不存在"
    conn = get_master_conn()
    try:
        article = conn.execute(
            "SELECT * FROM article_master WHERE id=?",
            (article_id,),
        ).fetchone()
        if not article:
            return False, "目标文章不存在"

        payload = pending.get("payload")
        if pending["record_type"] == "article_source":
            records = payload if isinstance(payload, list) else [payload or {}]
            _attach_source_records_to_article(conn, article_id, records, pending["source_file"])
        elif pending["record_type"] == "article_detail":
            detail = payload if isinstance(payload, dict) else {}
            detail["title"] = article["canonical_title"]
            _upsert_article_master_from_detail(conn, detail, pending["source_file"])
        else:
            return False, "当前记录类型暂不支持关联"

        conn.execute(
            "UPDATE pending_records SET status='resolved' WHERE id=?",
            (pending_id,),
        )
        conn.commit()
        return True, None
    finally:
        conn.close()


def resolve_pending_create(pending_id, title, publish_date=None):
    pending = get_pending_record(pending_id)
    if not pending:
        return False, "待确认记录不存在"
    title = (title or "").strip()
    publish_date = normalize_publish_date(publish_date)
    if not title:
        return False, "标题不能为空"

    conn = get_master_conn()
    try:
        article, _ = _ensure_article(conn, title, publish_date=publish_date)
        payload = pending.get("payload")

        if pending["record_type"] == "article_source":
            records = payload if isinstance(payload, list) else [payload or {}]
            normalized_records = []
            for rec in records:
                current = dict(rec or {})
                current["title"] = title
                current["publish_date"] = normalize_publish_date(current.get("publish_date") or publish_date)
                normalized_records.append(current)
            _attach_source_records_to_article(conn, article["id"], normalized_records, pending["source_file"])
        elif pending["record_type"] == "article_detail":
            detail = dict(payload or {})
            detail["title"] = title
            _upsert_article_master_from_detail(conn, detail, pending["source_file"])
            if publish_date:
                conn.execute(
                    "UPDATE article_master SET publish_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (publish_date, article["id"]),
                )
        else:
            conn.execute(
                "UPDATE article_master SET publish_date=COALESCE(publish_date, ?), updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (publish_date, article["id"]),
            )

        conn.execute(
            "UPDATE pending_records SET status='resolved' WHERE id=?",
            (pending_id,),
        )
        conn.commit()
        return True, None
    finally:
        conn.close()


EDITABLE_FIELDS = {
    "canonical_title",
    "publish_date",
    "total_reads",
    "share_user",
    "like_user",
    "thumbup_user",
    "fav_user",
    "comment_count",
    "avg_read_time",
    "complete_rate",
    "rec_reads",
    "rec_ratio",
    "open_rate",
}


def save_article_override(article_id, field_name, value, reason=""):
    if field_name not in EDITABLE_FIELDS:
        return False, "不支持修改该字段"
    if field_name == "publish_date":
        value = normalize_publish_date(value)
    conn = get_master_conn()
    conn.execute(
        """INSERT INTO article_overrides (article_id, field_name, override_value, reason, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(article_id, field_name) DO UPDATE SET
               override_value=excluded.override_value,
               reason=excluded.reason,
               updated_at=CURRENT_TIMESTAMP""",
        (article_id, field_name, str(value), reason),
    )
    if field_name in {"avg_read_time", "complete_rate", "rec_reads", "rec_ratio", "open_rate"}:
        conn.execute(
            """INSERT INTO article_diagnostics (article_id)
               VALUES (?)
               ON CONFLICT(article_id) DO NOTHING""",
            (article_id,),
        )
        conn.execute(
            f"UPDATE article_diagnostics SET {field_name}=?, updated_at=CURRENT_TIMESTAMP WHERE article_id=?",
            (value, article_id),
        )
    else:
        conn.execute(
            f"UPDATE article_master SET {field_name}=?, is_overridden=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (value, article_id),
        )
    conn.execute(
        "UPDATE article_master SET is_overridden=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (article_id,),
    )
    conn.commit()
    conn.close()
    return True, None


def clear_article_override(article_id, field_name):
    conn = get_master_conn()
    conn.execute(
        "DELETE FROM article_overrides WHERE article_id=? AND field_name=?",
        (article_id, field_name),
    )
    remaining = conn.execute(
        "SELECT COUNT(*) FROM article_overrides WHERE article_id=?",
        (article_id,),
    ).fetchone()[0]
    conn.execute(
        "UPDATE article_master SET is_overridden=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (1 if remaining else 0, article_id),
    )
    conn.commit()
    conn.close()
    return True
