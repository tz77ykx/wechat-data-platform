from flask import Blueprint, render_template, request, jsonify

from core.database import (
    query_title_analysis, query_lifecycle_data, query_posting_frequency,
    query_follower_attribution, query_holiday_analysis, query_viral_scores,
    query_recommend_analysis, query_recommend_trend,
)

bp = Blueprint("insights", __name__)


@bp.route("/insights")
def insights_page():
    return render_template("insights.html")


@bp.route("/api/title-analysis")
def api_title_analysis():
    return jsonify(query_title_analysis())


@bp.route("/api/lifecycle")
def api_lifecycle():
    top_n = int(request.args.get("n", 5))
    return jsonify(query_lifecycle_data(top_n))


@bp.route("/api/posting-frequency")
def api_posting_frequency():
    return jsonify(query_posting_frequency())


@bp.route("/api/follower-attribution")
def api_follower_attribution():
    return jsonify(query_follower_attribution())


@bp.route("/api/holiday-analysis")
def api_holiday_analysis():
    return jsonify(query_holiday_analysis())


@bp.route("/api/viral-scores")
def api_viral_scores():
    return jsonify(query_viral_scores())


@bp.route("/api/recommend-analysis")
def api_recommend_analysis():
    return jsonify(query_recommend_analysis())


@bp.route("/api/recommend-trend")
def api_recommend_trend():
    days = int(request.args.get("days", 60))
    return jsonify(query_recommend_trend(days))
