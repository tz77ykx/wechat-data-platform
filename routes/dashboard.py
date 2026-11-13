from flask import Blueprint, render_template
from core.database import query_summary, query_import_history

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def dashboard():
    return render_template(
        "dashboard.html",
        summary=query_summary(),
        imports=query_import_history(),
    )
