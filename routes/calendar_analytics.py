from flask import Blueprint, render_template, request, jsonify

from core.database import (
    query_calendar_data, query_heatmap_data,
    query_planned_articles, upsert_planned_article, delete_planned_article,
)

bp = Blueprint("calendar_analytics", __name__)


@bp.route("/calendar")
def calendar_page():
    return render_template("calendar_analytics.html")


@bp.route("/api/calendar")
def api_calendar():
    return jsonify(query_calendar_data())


@bp.route("/api/heatmap")
def api_heatmap():
    days = int(request.args.get("days", 365))
    return jsonify(query_heatmap_data(days))


# ── 发文规划 API ──────────────────────────────────────────────────────────────

@bp.route("/api/plans", methods=["GET"])
def api_plans_list():
    return jsonify(query_planned_articles())


@bp.route("/api/plans", methods=["POST"])
def api_plans_create():
    data = request.json or {}
    date = (data.get("plan_date") or "").strip()
    topic = (data.get("topic") or "").strip()
    if not date or not topic:
        return jsonify({"ok": False, "error": "plan_date 和 topic 不能为空"}), 400
    upsert_planned_article(date, topic, data.get("note", ""), data.get("status", "planned"))
    return jsonify({"ok": True})


@bp.route("/api/plans/<int:plan_id>", methods=["PUT", "DELETE"])
def api_plans_update(plan_id):
    if request.method == "DELETE":
        delete_planned_article(plan_id)
        return jsonify({"ok": True})
    data = request.json or {}
    date = (data.get("plan_date") or "").strip()
    topic = (data.get("topic") or "").strip()
    if not date or not topic:
        return jsonify({"ok": False, "error": "plan_date 和 topic 不能为空"}), 400
    upsert_planned_article(date, topic, data.get("note", ""),
                           data.get("status", "planned"), plan_id)
    return jsonify({"ok": True})
