"""APScheduler 定时任务管理（从 web_app.py 提取）"""

import subprocess
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from core.database import load_setting, save_setting
from core.wx_api import build_download_url
from core.notifier import bark_daily_report, bark_anomaly_check, email_daily_report

_scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _scheduled_download_job():
    token = load_setting("wx_token")
    if not token:
        print("[scheduler] 未配置 Token，跳过定时下载")
        return
    types = ["tendency", "user", "menu", "msg"]
    for t in types:
        url = build_download_url(t, token)
        if url:
            subprocess.Popen(["open", url])
    print(f"[scheduler] 定时下载已触发：{datetime.now().strftime('%Y-%m-%d %H:%M')}")


def apply_schedule():
    """Read schedule settings from DB and apply to scheduler."""
    schedule_time = load_setting("download_schedule", "")
    bark_report_time = load_setting("bark_report_time", "")
    email_report_time = load_setting("email_report_time", "")
    _scheduler.remove_all_jobs()

    if schedule_time and ":" in schedule_time:
        h, m = schedule_time.split(":")
        _scheduler.add_job(_scheduled_download_job, "cron",
                           hour=int(h), minute=int(m), id="auto_download")
        print(f"[scheduler] 定时下载已设置：每天 {schedule_time}")

    if bark_report_time and ":" in bark_report_time:
        h, m = bark_report_time.split(":")
        _scheduler.add_job(bark_daily_report, "cron",
                           hour=int(h), minute=int(m), id="bark_report")
        print(f"[scheduler] Bark 日报已设置：每天 {bark_report_time}")

    if email_report_time and ":" in email_report_time:
        h, m = email_report_time.split(":")
        _scheduler.add_job(email_daily_report, "cron",
                           hour=int(h), minute=int(m), id="email_report")
        print(f"[scheduler] 邮件日报已设置：每天 {email_report_time}")

    # 异常检测每小时跑一次（有数据时才推送）
    _scheduler.add_job(bark_anomaly_check, "interval", hours=1, id="anomaly_check")


def start_scheduler():
    apply_schedule()
    _scheduler.start()
