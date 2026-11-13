from flask import Blueprint, render_template, request, jsonify

from core.database import (
    query_heatmap_data, query_calendar_data,
    query_planned_articles, upsert_planned_article, delete_planned_article,
)

bp = Blueprint("calendar_push", __name__)


@bp.route("/push-calendar")
def push_calendar():
    prefill = {
        "title": (request.args.get("title") or "").strip(),
        "draft": (request.args.get("draft") or "").strip(),
        "source": (request.args.get("source") or "").strip(),
        "date": (request.args.get("date") or "").strip(),
        "time": (request.args.get("time") or "").strip(),
        "note": (request.args.get("note") or "").strip(),
    }
    return render_template("push_calendar.html", push_calendar_prefill=prefill)


@bp.route("/calendar")
def calendar_alias():
    return push_calendar()


@bp.route("/api/heatmap")
def api_heatmap():
    days = int(request.args.get("days", 365))
    return jsonify(query_heatmap_data(days))


@bp.route("/api/calendar")
def api_calendar():
    return jsonify(query_calendar_data())


@bp.route("/api/plans", methods=["GET"])
def api_plans_list():
    return jsonify(query_planned_articles())


@bp.route("/api/plans", methods=["POST"])
def api_plans_create():
    data = request.json or {}
    plan_date = (data.get("plan_date") or "").strip()
    topic = (data.get("topic") or "").strip()
    if not plan_date or not topic:
        return jsonify({"ok": False, "error": "plan_date 和 topic 不能为空"}), 400
    upsert_planned_article(plan_date, topic, data.get("note", ""), data.get("status", "planned"))
    return jsonify({"ok": True})


@bp.route("/api/plans/<int:plan_id>", methods=["PUT", "DELETE"])
def api_plans_update(plan_id):
    if request.method == "DELETE":
        delete_planned_article(plan_id)
        return jsonify({"ok": True})
    data = request.json or {}
    plan_date = (data.get("plan_date") or "").strip()
    topic = (data.get("topic") or "").strip()
    if not plan_date or not topic:
        return jsonify({"ok": False, "error": "plan_date 和 topic 不能为空"}), 400
    upsert_planned_article(plan_date, topic, data.get("note", ""), data.get("status", "planned"), plan_id)
    return jsonify({"ok": True})
