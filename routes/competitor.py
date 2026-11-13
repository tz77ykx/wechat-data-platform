import csv
import io
import json
import os
import re
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, Response, abort

from core.competitor_import_prep import (
    prepare_competitor_csv_paths,
    prepare_competitor_csv_texts,
    normalize_folder_nickname,
)
from core.database import (
    get_or_create_competitor, import_competitor_articles,
    get_competitor_accounts, get_competitor_articles,
    save_viral_analysis, save_article_content, save_competitor_manual_analysis, query_baseline_summary,
    get_competitor_article, query_pending_competitor_content,
)
from core.competitor_ai import analyze_competitor_article

bp = Blueprint("competitor", __name__)


@bp.route("/competitor")
def competitor_page():
    all_accounts = get_competitor_accounts()
    selected_matrix = (request.args.get("matrix") or "").strip()
    matrix_options = sorted({a.get("matrix_name") for a in all_accounts if a.get("matrix_name")})
    accounts = [a for a in all_accounts if not selected_matrix or a.get("matrix_name") == selected_matrix]
    selected_id = request.args.get("account_id", type=int)
    articles = []
    selected = None
    if selected_id and any(a["id"] == selected_id for a in accounts):
        articles = get_competitor_articles(selected_id)
        selected = next((a for a in accounts if a["id"] == selected_id), None)
    elif accounts:
        selected_id = accounts[0]["id"]
        articles = get_competitor_articles(selected_id)
        selected = accounts[0]
    baseline = query_baseline_summary()
    return render_template("competitor.html",
                           accounts=accounts, articles=articles,
                           selected=selected, selected_id=selected_id,
                           baseline=baseline,
                           selected_matrix=selected_matrix,
                           matrix_options=matrix_options)


@bp.route("/export/competitor/<int:account_id>.csv")
def export_competitor_csv(account_id):
    accounts = get_competitor_accounts()
    selected = next((a for a in accounts if a["id"] == account_id), None)
    if not selected:
        abort(404)

    rows = get_competitor_articles(account_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["nickname", "title", "url", "time", "like_num", "read_num", "share_num", "comment_count"])
    for row in rows:
        writer.writerow([
            selected["nickname"],
            row.get("title", ""),
            row.get("url", ""),
            row.get("publish_time", ""),
            row.get("like_num", 0),
            row.get("read_num", 0),
            row.get("share_num", 0),
            row.get("comment_count", 0),
        ])

    filename = f"{_safe_export_name(selected['nickname'])}_competitor.csv"
    output = buf.getvalue().encode("utf-8-sig")
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.route("/api/competitor/import", methods=["POST"])
def api_competitor_import():
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")
        if single:
            files = [single]
    if not files:
        return jsonify({"ok": False, "error": "未上传文件"})
    try:
        prepared = prepare_competitor_csv_texts(
            [(f.filename or "uploaded.csv", f.read().decode("utf-8-sig")) for f in files],
            _competitor_base_dir(),
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    account_id = get_or_create_competitor(prepared["nickname"])
    result = import_competitor_articles(account_id, prepared["articles"])
    return jsonify({
        "ok": True,
        "account_id": account_id,
        "nickname": prepared["nickname"],
        "source_files": prepared["source_files"],
        "total_rows": prepared["total_rows"],
        "deduped_rows": prepared["deduped_rows"],
        "prepared_filename": prepared["prepared_filename"],
        **result,
    })


@bp.route("/api/competitor/article/<int:article_id>/analyze", methods=["POST"])
def api_analyze_article(article_id):
    article = get_competitor_article(article_id)
    if not article:
        return jsonify({"ok": False, "error": "文章不存在"})

    baseline = query_baseline_summary()
    result = analyze_competitor_article(article, baseline)

    if result["ok"]:
        save_viral_analysis(article_id, json.dumps(result["analysis"], ensure_ascii=False))

    return jsonify(result)


@bp.route("/api/competitor/article/<int:article_id>/content", methods=["POST"])
def api_save_content(article_id):
    data = request.get_json(force=True)
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"ok": False, "error": "内容为空"})
    save_article_content(article_id, content)
    return jsonify({"ok": True})


@bp.route("/api/competitor/article/<int:article_id>/manual-analysis", methods=["POST"])
def api_save_manual_analysis(article_id):
    article = get_competitor_article(article_id)
    if not article:
        return jsonify({"ok": False, "error": "文章不存在"})
    data = request.get_json(force=True) or {}
    status = (data.get("status") or "pending").strip()
    if status not in {"pending", "discussing", "done"}:
        return jsonify({"ok": False, "error": "状态不合法"})
    summary = (data.get("summary") or "").strip()
    notes = (data.get("notes") or "").strip()
    save_competitor_manual_analysis(article_id, status, summary, notes)
    return jsonify({"ok": True})


@bp.route("/api/competitor/import-local", methods=["POST"])
def api_import_local():
    """扫描本地 对标账号/*/下载/*.csv，逐目录整理后导入。"""
    base_dir = _competitor_base_dir()
    if not os.path.isdir(base_dir):
        return jsonify({"ok": False, "error": f"目录不存在: {base_dir}"})

    download_dirs = sorted(Path(base_dir).glob("*/下载"))
    if not download_dirs:
        return jsonify({"ok": False, "error": "未找到任何 CSV 文件"})

    results = []
    for download_dir in download_dirs:
        csv_files = sorted(
            path for path in download_dir.glob("*.csv")
            if "_merged" not in path.stem and "_dedup" not in path.stem
        )
        if not csv_files:
            continue
        try:
            prepared = prepare_competitor_csv_paths(
                csv_files,
                base_dir,
                fallback_name=normalize_folder_nickname(download_dir.parent.name),
            )
        except Exception:
            continue
        account_id = get_or_create_competitor(prepared["nickname"])
        res = import_competitor_articles(account_id, prepared["articles"])
        results.append({
            "nickname": prepared["nickname"],
            "account_id": account_id,
            "source_files": prepared["source_files"],
            "total_rows": prepared["total_rows"],
            "deduped_rows": prepared["deduped_rows"],
            "prepared_filename": prepared["prepared_filename"],
            "inserted": res.get("inserted", 0),
            "skipped": res.get("skipped", 0),
        })

    if not results:
        return jsonify({"ok": False, "error": "未找到可整理的 CSV 文件"})

    return jsonify({
        "ok": True,
        "accounts": len(results),
        "total_inserted": sum(r["inserted"] for r in results),
        "total_skipped": sum(r["skipped"] for r in results),
        "details": results,
    })


@bp.route("/api/competitor/pending-content")
def api_pending_content():
    """返回有分析结果但没有正文的文章列表（供扩展批量抓取）。"""
    rows = query_pending_competitor_content()
    return jsonify({
        "ok": True,
        "count": len(rows),
        "articles": [{"id": r["id"], "title": r["title"], "url": r["url"].replace("&amp;", "&")} for r in rows],
    })


@bp.route("/api/competitor/accounts")
def api_accounts():
    return jsonify(get_competitor_accounts())


def _competitor_base_dir() -> str:
    env_dir = os.environ.get("COMPETITOR_IMPORT_DIR")
    if env_dir:
        return env_dir
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "对标账号")


def _safe_export_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "", value or "competitor")
