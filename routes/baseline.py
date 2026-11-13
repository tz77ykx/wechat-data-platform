from flask import Blueprint, jsonify, redirect, url_for

from core.database import (
    query_baseline_summary, query_articles_performance
)

bp = Blueprint("baseline", __name__)


@bp.route("/baseline")
def baseline_page():
    return redirect(url_for("competitor.competitor_page"))


@bp.route("/api/baseline/summary")
def api_baseline_summary():
    return jsonify(query_baseline_summary())


@bp.route("/api/baseline/articles")
def api_baseline_articles():
    return jsonify(query_articles_performance())
