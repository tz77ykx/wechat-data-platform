"""Bark 推送 & 邮件通知（从 web_app.py 提取）"""

import json
import urllib.request
from datetime import datetime

from core.database import load_setting, query_yesterday_report, query_anomaly_check, log_anomaly


def send_bark(title: str, body: str, group: str = "公众号助手") -> bool:
    key = load_setting("bark_key", "")
    if not key:
        return False
    try:
        payload = json.dumps({
            "title": title, "body": body,
            "group": group, "device_key": key,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.day.app/push",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[bark] 推送失败: {e}")
        return False


def bark_daily_report():
    """每日数据快报推送（由 scheduler 调用）。"""
    d = query_yesterday_report()
    if not d["reads"]:
        return
    lines = [f"📅 {d['date']} 数据快报"]
    arrow = "▲" if (d["pct"] or 0) >= 0 else "▼"
    pct_str = f"{arrow}{abs(d['pct'])}% vs 7日均值" if d["pct"] is not None else ""
    lines.append(f"阅读量：{d['reads']:,}  {pct_str}")
    if d["net_user"] is not None:
        lines.append(f"净增粉丝：{'+' if d['net_user']>=0 else ''}{d['net_user']}")
    if d["top_title"]:
        lines.append(f"近7日最热：《{d['top_title'][:20]}》{d['top_reads']:,}读")
    send_bark("公众号日报", "\n".join(lines[1:]))


def bark_anomaly_check():
    """异常检测推送（由 scheduler 调用）。"""
    a = query_anomaly_check()
    if not a:
        return
    # 入库记录
    log_anomaly(
        datetime.now().strftime("%Y-%m-%d"),
        a["today"], a["avg7"], a["pct"], a["direction"],
    )
    emoji = "🚀" if a["pct"] > 0 else "⚠️"
    send_bark(
        f"{emoji} 阅读量{a['direction']}",
        f"今日 {a['today']:,} 读，7日均值 {a['avg7']:,}，偏差 {a['pct']:+.1f}%",
        group="公众号告警",
    )


def send_email(subject: str, body: str) -> tuple[bool, str]:
    """用 SMTP 发送邮件。配置从数据库 settings 读取。"""
    import smtplib, ssl
    from email.mime.text import MIMEText
    smtp_host = load_setting("smtp_host", "")
    smtp_port = int(load_setting("smtp_port", "465") or "465")
    smtp_user = load_setting("smtp_user", "")
    smtp_pass = load_setting("smtp_pass", "")
    smtp_to   = load_setting("smtp_to",   "")
    if not all([smtp_host, smtp_user, smtp_pass, smtp_to]):
        return False, "邮件配置未填写"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = smtp_to
    try:
        if smtp_port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as s:
                s.login(smtp_user, smtp_pass)
                s.sendmail(smtp_user, smtp_to, msg.as_bytes())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(smtp_user, smtp_pass)
                s.sendmail(smtp_user, smtp_to, msg.as_bytes())
        return True, ""
    except Exception as e:
        return False, str(e)


def email_daily_report():
    """邮件日报（由 scheduler 调用）。"""
    d = query_yesterday_report()
    if not d["reads"]:
        return
    arrow = "▲" if (d["pct"] or 0) >= 0 else "▼"
    pct_str = f"{arrow}{abs(d['pct'])}% vs 7日均值" if d["pct"] is not None else ""
    lines = [
        f"📅 {d['date']} 公众号数据快报",
        f"阅读量：{d['reads']:,}  {pct_str}",
    ]
    if d["net_user"] is not None:
        lines.append(f"净增粉丝：{'+' if d['net_user']>=0 else ''}{d['net_user']}")
    if d["top_title"]:
        lines.append(f"近7日最热：《{d['top_title'][:30]}》{d['top_reads']:,}读")
    lines.append("\n—— 公众号数据分析助手自动发送")
    ok, err = send_email(f"公众号日报 {d['date']}", "\n".join(lines))
    if not ok:
        print(f"[email] 发送失败: {err}")
