from flask import Blueprint, redirect, url_for

bp = Blueprint("summary", __name__)


@bp.route("/summary")
def summary_page():
    return redirect(url_for("dashboard.dashboard"))
