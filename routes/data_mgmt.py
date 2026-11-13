import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify, Response, redirect

from config import MASTER_DB_PATH
from core.database import (
    query_data_stats,
    delete_import_file,
    sync_article_reads,
)

bp = Blueprint("data_mgmt", __name__)


@bp.route("/data")
def data_management():
    return redirect("/")


@bp.route("/api/data-stats")
def api_data_stats():
    return jsonify(query_data_stats())



@bp.route("/api/delete-import", methods=["POST"])
def api_delete_import():
    filename = (request.json or {}).get("filename", "").strip()
    if not filename:
        return jsonify({"ok": False, "error": "filename 不能为空"}), 400
    result = delete_import_file(filename)
    return jsonify({"ok": True, **result})


@bp.route("/api/sync-reads", methods=["POST"])
def api_sync_reads():
    result = sync_article_reads()
    return jsonify({"ok": True, **result})


@bp.route("/export/db")
def export_db():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    shutil.copy2(str(MASTER_DB_PATH), tmp.name)
    tmp.close()
    data = Path(tmp.name).read_bytes()
    os.unlink(tmp.name)
    fname = f"wechat_master_{datetime.now().strftime('%Y%m%d')}.db"
    return Response(data, mimetype="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@bp.route("/export/daily.csv")
def export_daily_csv():
    import csv
    import io
    from core.database import query_daily_reads
    rows = query_daily_reads(365)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["日期", "渠道", "阅读人数"])
    for r in rows:
        writer.writerow([r["stat_date"], r["channel"], r["read_user"]])
    output = buf.getvalue().encode("utf-8-sig")
    return Response(output, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=daily_reads.csv"})
