import os
import re
import subprocess
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify

from core.database import (
    load_setting, save_setting,
    query_article_msgids, upsert_article_msgids, mark_detail_downloaded,
)
from core.wx_api import build_download_url, wx_get
from core.notifier import send_bark, send_email
from core.scheduler import apply_schedule

bp = Blueprint("settings", __name__)


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    message = None
    message_type = None
    if request.method == "POST":
        token = request.form.get("token", "").strip()
        fingerprint = request.form.get("fingerprint", "").strip()
        cookies = request.form.get("cookies", "").strip()
        save_setting("wx_token", token)
        save_setting("wx_fingerprint", fingerprint)
        save_setting("wx_cookies", cookies)
        message = "✅ 凭证已保存"
        message_type = "success"

    return render_template("settings.html",
        token=load_setting("wx_token"),
        fingerprint=load_setting("wx_fingerprint"),
        cookies=load_setting("wx_cookies"),
        msgids=query_article_msgids(),
        message=message,
        message_type=message_type,
        ext_path=str(Path(__file__).resolve().parent.parent / "chrome_extension"),
    )


# ── Bark 推送 ─────────────────────────────────────────────────────────────────

@bp.route("/api/save-bark-key", methods=["POST"])
def api_save_bark_key():
    key = (request.json or {}).get("key", "").strip()
    save_setting("bark_key", key)
    return jsonify({"ok": True})


@bp.route("/api/get-bark-key")
def api_get_bark_key():
    return jsonify({"key": load_setting("bark_key", "")})


@bp.route("/api/test-bark", methods=["POST"])
def api_test_bark():
    ok = send_bark("公众号助手测试", "推送配置成功！🎉")
    return jsonify({"ok": ok, "error": "" if ok else "发送失败，请检查 Bark Key 是否正确"})


# ── 邮件 ──────────────────────────────────────────────────────────────────────

@bp.route("/api/save-email", methods=["POST"])
def api_save_email():
    data = request.json or {}
    for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_to", "email_report_time"):
        if k in data:
            save_setting(k, str(data[k]))
    apply_schedule()
    return jsonify({"ok": True})


@bp.route("/api/get-email")
def api_get_email():
    return jsonify({k: load_setting(k, "") for k in
                    ("smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_to", "email_report_time")})


@bp.route("/api/test-email", methods=["POST"])
def api_test_email():
    ok, err = send_email("公众号助手邮件测试", "邮件推送配置成功！🎉\n\n—— 公众号数据分析助手")
    return jsonify({"ok": ok, "error": err})


# ── 定时下载 ──────────────────────────────────────────────────────────────────

@bp.route("/api/set-schedule", methods=["POST"])
def api_set_schedule():
    data = request.json or {}
    for key in ("download_schedule", "bark_report_time"):
        t = data.get(key, "").strip()
        if t and not re.match(r"^\d{1,2}:\d{2}$", t):
            return jsonify({"ok": False, "error": f"{key} 格式错误，应为 HH:MM"}), 400
        if key in data:
            save_setting(key, t)
    apply_schedule()
    return jsonify({"ok": True})


@bp.route("/api/get-schedule")
def api_get_schedule():
    return jsonify({
        "download_schedule": load_setting("download_schedule", ""),
        "bark_report_time": load_setting("bark_report_time", ""),
    })


@bp.route("/api/set-api-key", methods=["POST"])
def api_set_api_key():
    key = (request.json or {}).get("key", "").strip()
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
    return jsonify({"ok": bool(key)})


# ── 异常阈值 ──────────────────────────────────────────────────────────────────

@bp.route("/api/anomaly-threshold", methods=["GET", "POST"])
def api_anomaly_threshold():
    if request.method == "POST":
        val = str((request.json or {}).get("threshold", "40"))
        try:
            t = float(val)
            if not (5 <= t <= 200):
                raise ValueError()
        except ValueError:
            return jsonify({"ok": False, "error": "阈值范围 5~200"}), 400
        save_setting("anomaly_threshold", str(t))
        return jsonify({"ok": True})
    return jsonify({"threshold": float(load_setting("anomaly_threshold", "40") or "40")})


@bp.route("/api/anomaly-log")
def api_anomaly_log():
    from core.database import query_anomaly_log
    limit = int(request.args.get("limit", 30))
    return jsonify(query_anomaly_log(limit))
