import csv
import io

from flask import Blueprint, render_template, request, jsonify, Response, redirect, url_for

from core.database import (
    query_article_ranking, query_article_trend, query_article_details,
    get_article_detail_by_title, upsert_article_tag, delete_article_tag, query_article_tags,
    update_article_reads, update_article_field,
)

bp = Blueprint("articles", __name__)


@bp.route("/articles")
def articles():
    return redirect(url_for("master.master_home", tab="articles", order="reads"))


@bp.route("/article/<path:title>")
def article_detail_page(title):
    trend = query_article_trend(title)
    detail = get_article_detail_by_title(title)
    return render_template("article_detail.html", title=title, detail=detail, trend=trend)


@bp.route("/api/articles")
def api_articles():
    return jsonify(query_article_ranking())


@bp.route("/api/article-details")
def api_article_details():
    return jsonify(query_article_details())


@bp.route("/api/article-trend/<path:title>")
def api_article_trend(title):
    return jsonify(query_article_trend(title))


@bp.route("/export/articles.csv")
def export_articles_csv():
    rows = query_article_ranking()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["发布日期", "标题", "总阅读量", "推荐占比%",
                     "转发", "点赞", "在看", "评论", "收藏", "完读率%", "停留(s)", "关注转化"])
    for r in rows:
        writer.writerow([
            r.get("publish_date", ""), r.get("title", ""), r.get("total_reads", ""),
            r.get("rec_pct", ""), r.get("share_user", ""), r.get("thumbup_user", ""),
            r.get("like_user", ""), r.get("comment_count", ""), r.get("fav_user", ""),
            r.get("complete_rate", ""), r.get("avg_read_time", ""), r.get("follow_after_read", ""),
        ])
    output = buf.getvalue().encode("utf-8-sig")
    return Response(output, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=articles.csv"})


# ── 手动修改文章字段 ──────────────────────────────────────────────────────────

@bp.route("/api/article-field/<path:title>", methods=["PATCH"])
def api_update_field(title):
    data = request.json or {}
    field = (data.get("field") or "").strip()
    value = data.get("value")
    if not field or value is None:
        return jsonify({"ok": False, "error": "field 和 value 不能为空"}), 400
    ok, err = update_article_field(title, field, value)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True})


# ── 文章标签 API ──────────────────────────────────────────────────────────────

@bp.route("/api/tags", methods=["GET"])
def api_tags_all():
    return jsonify(query_article_tags())


@bp.route("/api/tags/<path:title>", methods=["GET", "POST", "DELETE"])
def api_tags(title):
    if request.method == "GET":
        return jsonify(query_article_tags(title))
    data = request.json or {}
    tag = (data.get("tag") or "").strip()
    if not tag:
        return jsonify({"ok": False, "error": "tag 不能为空"}), 400
    if request.method == "POST":
        upsert_article_tag(title, tag)
    else:
        delete_article_tag(title, tag)
    return jsonify({"ok": True})
