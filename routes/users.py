from flask import Blueprint, redirect, request, jsonify, url_for

from core.database import (
    query_user_stats, query_msg_stats, query_funnel, query_best_publish_time,
    query_total_user_trend, get_conn,
)

bp = Blueprint("users", __name__)


@bp.route("/users")
def users():
    return redirect(url_for("master.master_home"))


@bp.route("/api/users")
def api_users():
    start = request.args.get("start")
    end = request.args.get("end")
    days = int(request.args.get("days", 60))
    return jsonify(query_user_stats(days, start_date=start, end_date=end))


@bp.route("/api/msg-stats")
def api_msg_stats():
    start = request.args.get("start")
    end = request.args.get("end")
    days = int(request.args.get("days", 60))
    return jsonify(query_msg_stats(days, start_date=start, end_date=end))


@bp.route("/api/funnel")
def api_funnel():
    data = query_funnel()
    if not data:
        return jsonify([])
    stages = [
        ("阅读", data.get("reads", 0), 100),
        ("转发", data.get("shares", 0), data.get("share_rate", 0)),
        ("点赞", data.get("likes", 0), data.get("like_rate", 0)),
        ("收藏", data.get("favs", 0), data.get("fav_rate", 0)),
        ("关注", data.get("follows", 0), data.get("follow_rate", 0)),
        ("评论", data.get("comments", 0), round((data.get("comments", 0) / max(data.get("reads", 1), 1)) * 100, 2)),
    ]
    return jsonify([{"stage": s, "value": v, "pct": p} for s, v, p in stages])


@bp.route("/api/best-publish-time")
def api_best_publish_time():
    return jsonify(query_best_publish_time())


@bp.route("/api/total-user-trend")
def api_total_user_trend():
    days = int(request.args.get("days", 180))
    return jsonify(query_total_user_trend(days))
