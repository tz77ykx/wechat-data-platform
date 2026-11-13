import subprocess
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify, redirect, url_for, render_template

from config import UPLOAD_DIR
from core.database import (
    get_import_record, record_import,
    mark_detail_downloaded,
    query_daily_reads, query_daily_stats, query_summary, query_import_history,
    query_data_freshness, load_setting, save_setting,
    upsert_article_msgids, query_article_msgids,
    sync_article_reads,
)
from core.parser import parse_any
from core.wx_api import build_download_url, wx_get
from core.watcher import scan_now
from core.master_db import sync_master_from_import, get_master_conn

bp = Blueprint("api_common", __name__)


# ── 核心导入逻辑（供上传接口和 watcher 共用） ────────────────────────────────────

def do_import(filepath: Path) -> dict:
    filename = filepath.name
    existing = get_import_record(filename)

    try:
        result = parse_any(str(filepath))
    except Exception as e:
        return {"ok": False, "message": f"解析失败：{e}", "message_type": "error"}

    ftype = result["type"]
    data = result["data"]
    rows_total = 0
    date_range = data.get("date_range", "")

    if ftype == "tendency":
        rows_total = len(data["daily_reads"]) + len(data["daily_stats"]) + len(data["article_sources"])
    elif ftype == "user":
        rows_total = len(data["records"])
    elif ftype == "menu":
        rows_total = len(data["records"])
    elif ftype == "msg":
        rows_total = len(data["records"])
    elif ftype == "article_detail":
        detail = data["detail"]
        trend = data.get("trend", [])
        rows_total = 1 + len(trend)
        date_range = detail.get("title", "")[:20]
        conn = get_master_conn()
        row = conn.execute(
            """SELECT msgid
               FROM article_msgids
               WHERE title=? OR normalized_title=?
               ORDER BY fetched_at DESC LIMIT 1""",
            (detail.get("title", ""), detail.get("title", "").strip().replace(" ", "").casefold()),
        ).fetchone()
        conn.close()
        if row:
            mark_detail_downloaded(row["msgid"])

    try:
        master_sync = sync_master_from_import(ftype, data, filename)
    except Exception as e:
        return {"ok": False, "message": f"主档同步失败：{e}", "message_type": "error"}

    record_import(filename, date_range, rows_total)

    verb = "更新" if existing else "导入"
    type_label = {"tendency": "数据趋势", "user": "用户增减", "menu": "菜单分析",
                  "msg": "消息分析", "article_detail": "单篇详情"}.get(ftype, ftype)
    touched = master_sync["inserted"] + master_sync["updated"]
    return {
        "ok": True,
        "message": f"✅ {verb}成功 [{type_label}]：{filename} — {rows_total} 行，主档更新 {touched} 项",
        "message_type": "success",
    }


# ── 文件导入（手动上传） ──────────────────────────────────────────────────────────

@bp.route("/import", methods=["POST"])
def import_file():
    f = request.files.get("xls_file")
    if not f or not f.filename:
        return redirect(url_for("dashboard.dashboard"))

    filename = Path(f.filename).name
    save_path = UPLOAD_DIR / filename
    f.save(str(save_path))

    result = do_import(save_path)
    return render_template(
        "dashboard.html",
        summary=query_summary(),
        imports=query_import_history(),
        message=result["message"],
        message_type=result["message_type"],
    )


# ── JSON API ───────────────────────────────────────────────────────────────────

@bp.route("/api/daily")
def api_daily():
    start = request.args.get("start")
    end = request.args.get("end")
    days = int(request.args.get("days", 30))
    reads = query_daily_reads(days, start_date=start, end_date=end)
    stats = query_daily_stats(days, start_date=start, end_date=end)

    channels = {}
    dates_set = set()
    for r in reads:
        dates_set.add(r["stat_date"])
        channels.setdefault(r["channel"], {})[r["stat_date"]] = r["read_user"]

    dates = sorted(dates_set)
    series = [
        {"name": ch, "data": [channels[ch].get(d, 0) for d in dates]}
        for ch in channels
    ]
    return jsonify({"dates": dates, "series": series, "stats": stats})


@bp.route("/api/freshness")
def api_freshness():
    return jsonify(query_data_freshness())


@bp.route("/api/watcher-status")
def api_watcher_status():
    imports = query_import_history()
    latest = imports[0] if imports else None
    return jsonify({"latest": latest})


@bp.route("/api/scan-now", methods=["POST"])
def api_scan_now():
    results = scan_now(do_import)
    return jsonify({"ok": True, "results": results, "count": len(results)})


# ── 凭证同步 ──────────────────────────────────────────────────────────────────

@bp.route("/api/sync-credentials", methods=["POST"])
def sync_credentials():
    data = request.json or {}
    if data.get("token"):
        save_setting("wx_token", data["token"])
    if data.get("fingerprint"):
        save_setting("wx_fingerprint", data["fingerprint"])
    if data.get("cookies"):
        save_setting("wx_cookies", data["cookies"])
    return jsonify({"ok": True})


# ── 下载触发 ──────────────────────────────────────────────────────────────────

@bp.route("/trigger-download", methods=["POST"])
def trigger_download():
    token = load_setting("wx_token")
    if not token:
        return jsonify({"ok": False, "error": "请先在设置页填写 Token"}), 400
    body = request.get_json(silent=True) or {}
    data_type = body.get("type", "tendency")
    url = build_download_url(data_type, token)
    if not url:
        return jsonify({"ok": False, "error": "未知数据类型"}), 400
    subprocess.Popen(["open", url])
    return jsonify({"ok": True, "url": url})


@bp.route("/trigger-download-all", methods=["POST"])
def trigger_download_all():
    token = load_setting("wx_token")
    if not token:
        return jsonify({"ok": False, "error": "请先在设置页填写 Token"}), 400
    types = ["tendency", "user", "menu", "msg"]
    opened = []
    for t in types:
        url = build_download_url(t, token)
        if url:
            subprocess.Popen(["open", url])
            opened.append(t)
    return jsonify({"ok": True, "opened": opened})


# ── 文章 msgid 获取 ───────────────────────────────────────────────────────────

def _article_date_range(values):
    start = values.get("start_date")
    end = values.get("end_date")
    if start is None and end is None:
        return None
    try:
        start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
        if start_day.isoformat() != start or end_day.isoformat() != end:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("请填写有效的起止日期，格式为 YYYY-MM-DD") from None
    if start_day > end_day:
        raise ValueError("开始日期不能晚于结束日期")
    return {"start_date": start, "end_date": end}


def _within_article_dates(publish_date, selected):
    value = (publish_date or "").replace("/", "-")
    return bool(value) and selected["start_date"] <= value <= selected["end_date"]


@bp.route("/fetch-msgids", methods=["POST"])
def fetch_msgids():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "请求参数必须是对象"}), 400
    try:
        selected = _article_date_range(body)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    token = load_setting("wx_token")
    cookies = load_setting("wx_cookies")
    fingerprint = load_setting("wx_fingerprint")

    if not all([token, cookies, fingerprint]):
        return jsonify({"ok": False, "error": "请先在设置页填写 Token、Cookies、Fingerprint"}), 400

    tz = ZoneInfo("Asia/Shanghai")
    if selected:
        begin_dt = datetime.combine(date.fromisoformat(selected["start_date"]), time.min, tzinfo=tz)
        end_dt = datetime.combine(date.fromisoformat(selected["end_date"]), time(23, 59, 59), tzinfo=tz)
    else:
        end_dt = datetime.now(tz)
        begin_dt = end_dt - timedelta(days=365)
    end_ts = int(end_dt.timestamp())
    begin_ts = int(begin_dt.timestamp())

    all_articles = []
    offset = 0
    count = 50

    try:
        while True:
            path = (
                f"/misc/appmsganalysis?action=get_article_list"
                f"&begin_timestamp={begin_ts}&end_timestamp={end_ts}"
                f"&article_source=9999&offset={offset}&count={count}"
                f"&fingerprint={fingerprint}&token={token}&lang=zh_CN&f=json&ajax=1"
            )
            data = wx_get(path, cookies, token, fingerprint)
            base_resp = data.get("base_resp") or {}
            ret_code = base_resp.get("ret", 0)
            if ret_code != 0:
                err_msg = base_resp.get("err_msg") or ""
                raise RuntimeError(f"微信接口返回 ret={ret_code}" + (f" ({err_msg})" if err_msg else ""))
            articles = (
                data.get("articles") or
                data.get("article_list") or
                data.get("list") or []
            )
            if not articles:
                break
            all_articles.extend(articles)
            if len(articles) < count:
                break
            offset += count
    except Exception as e:
        return jsonify({"ok": False, "error": f"请求失败：{e}"}), 500

    if not all_articles and not selected:
        return jsonify({"ok": False, "error": "返回数据为空，请检查 Cookies 是否过期"}), 400

    records = []
    for a in all_articles:
        msgid = a.get("msgid") or a.get("msg_id") or ""
        title = a.get("title", "")
        raw_date = str(a.get("ref_date") or a.get("publish_date") or "")
        if len(raw_date) == 8 and raw_date.isdigit():
            pub_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        else:
            pub_date = raw_date.replace("/", "-")
        if msgid and (not selected or _within_article_dates(pub_date, selected)):
            records.append({"msgid": msgid, "title": title, "publish_date": pub_date})

    upsert_article_msgids(records)
    conn = get_master_conn()
    missing_rows = conn.execute(
        """SELECT m.canonical_title, m.publish_date
           FROM article_master m
           LEFT JOIN article_msgids am
             ON am.normalized_title = m.normalized_title
            AND (
                am.publish_date IS NULL
                OR m.publish_date IS NULL
                OR am.publish_date = m.publish_date
            )
           WHERE m.publish_date >= ?
             AND m.publish_date <= ?
             AND am.msgid IS NULL
           ORDER BY m.publish_date DESC, m.canonical_title""",
        (begin_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")),
    ).fetchall()
    conn.close()
    missing_titles = [
        {"title": row["canonical_title"], "publish_date": row["publish_date"]}
        for row in missing_rows
    ]
    msgids = query_article_msgids()
    if selected:
        msgids = [row for row in msgids if _within_article_dates(row["publish_date"], selected)]
    return jsonify({
        "ok": True,
        "count": len(records),
        "fetched": len(records),
        "msgids": msgids,
        "date_range": selected or {"start_date": begin_dt.date().isoformat(), "end_date": end_dt.date().isoformat()},
        "missing_titles": missing_titles,
        "sample": records[:3],
    })


@bp.route("/download-all-articles", methods=["POST"])
def download_all_articles():
    token = load_setting("wx_token")
    if not token:
        return jsonify({"ok": False, "error": "请先填写 Token"}), 400

    body = request.get_json(silent=True) or {}
    pending = body.get("pending_only", True)
    articles = query_article_msgids(only_pending=pending)
    if not articles:
        return jsonify({"ok": False, "error": "没有待下载的文章，请先点击「获取文章列表」"}), 400

    urls = []
    for art in articles:
        if not art["publish_date"]:
            continue
        msgid_raw = art["msgid"]
        msgid_wx = msgid_raw if "_" in msgid_raw else f"{msgid_raw}_1"
        pub_date = art["publish_date"].replace("/", "-")
        urls.append({
            "msgid": msgid_raw,
            "title": art["title"] or msgid_raw,
            "detail_url": (
                f"https://mp.weixin.qq.com/misc/appmsganalysis"
                f"?action=detailpage"
                f"&msgid={msgid_wx}"
                f"&publish_date={pub_date}"
                f"&type=int"
                f"&pageVersion=1"
                f"&token={token}&lang=zh_CN"
            ),
        })

    return jsonify({"ok": True, "urls": urls})


@bp.route("/api/pending-details")
def api_pending_details():
    """供 Chrome 扩展获取待下载文章详情列表（GET，无需 JSON body）。"""
    try:
        selected = _article_date_range(request.args)
        mode = request.args.get("download_mode", "missing" if selected else "pending")
        if selected and mode not in {"missing", "refresh"}:
            raise ValueError("下载方式必须是 missing 或 refresh")
        if not selected and "download_mode" in request.args:
            raise ValueError("请同时选择文章发布日期范围")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    token = load_setting("wx_token")
    if not token:
        return jsonify({"ok": False, "error": "Token 未配置"}), 400
    articles = query_article_msgids(only_pending=not bool(selected))
    if selected:
        articles = [article for article in articles
                    if _within_article_dates(article["publish_date"], selected)
                    and (mode == "refresh" or not article["has_detail_snapshot"])]
    urls = []
    for art in articles:
        if not art["publish_date"]:
            continue
        # msgid 需要带 _1 后缀（文章在推送中的位置索引）
        msgid_raw = art["msgid"]
        msgid_wx = msgid_raw if "_" in msgid_raw else f"{msgid_raw}_1"
        # publish_date 统一为 YYYY-MM-DD 连字符格式
        pub_date = art["publish_date"].replace("/", "-")
        urls.append({
            "msgid": msgid_raw,
            "title": art["title"] or msgid_raw,
            "publish_date": pub_date,
            "detail_url": (
                f"https://mp.weixin.qq.com/misc/appmsganalysis"
                f"?action=detailpage"
                f"&msgid={msgid_wx}"
                f"&publish_date={pub_date}"
                f"&type=int"
                f"&pageVersion=1"
                f"&token={token}&lang=zh_CN"
            ),
        })
    return jsonify({
        "ok": True, "count": len(urls), "urls": urls,
        "selection": {**selected, "download_mode": mode} if selected else None,
    })
