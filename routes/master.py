from flask import Blueprint, render_template, request

from core.master_db import (
    EDITABLE_FIELDS,
    bootstrap_master_from_analytics,
    clear_article_override,
    get_pending_record,
    query_account_daily_metrics,
    query_account_menu_stats,
    query_account_message_stats,
    query_account_user_daily,
    query_master_article_detail,
    query_master_articles,
    query_master_diagnostics,
    query_master_summary,
    query_pending_records,
    resolve_pending_associate,
    resolve_pending_create,
    save_article_override,
    update_pending_status,
)

bp = Blueprint("master", __name__)


def _render_master_page(message=None, message_type="success"):
    tab = request.args.get("tab", "articles")
    order = request.args.get("order", "latest")
    q = request.args.get("q", "").strip()
    overridden = request.args.get("overridden")
    recent_only = request.args.get("recent") == "1"

    context = {
        "summary": query_master_summary(),
        "tab": tab,
        "order": order,
        "q": q,
        "overridden": overridden,
        "recent_only": recent_only,
        "pending": query_pending_records(limit=20),
        "message": message,
        "message_type": message_type,
    }

    if tab == "diagnostics":
        context["diagnostics"] = query_master_diagnostics()
    elif tab == "trends":
        context["daily_metrics"] = query_account_daily_metrics()
    elif tab == "users":
        context["users"] = query_account_user_daily()
    elif tab == "menu":
        context["menus"] = query_account_menu_stats()
    elif tab == "messages":
        context["messages"] = query_account_message_stats()
    else:
        context["articles"] = query_master_articles(
            q=q,
            order=order,
            overridden=overridden,
            recent_only=recent_only,
        )

    return render_template("master.html", **context)


@bp.route("/master")
def master_home():
    return _render_master_page()


@bp.route("/master/bootstrap", methods=["POST"])
def master_bootstrap():
    stats = bootstrap_master_from_analytics()
    message = (
        f"主档初始化完成：文章 {stats['articles']} 篇，"
        f"趋势 {stats['daily_metrics']} 条，用户 {stats['users']} 条，"
        f"消息 {stats['messages']} 条，菜单 {stats['menus']} 条。"
    )
    return _render_master_page(message=message, message_type="success")


@bp.route("/master/article/<int:article_id>", methods=["GET", "POST"])
def master_article_detail(article_id):
    message = None
    message_type = "success"
    if request.method == "POST":
        action = request.form.get("action", "save")
        field_name = (request.form.get("field_name") or "").strip()
        if action == "clear":
            clear_article_override(article_id, field_name)
            message = f"已恢复字段：{field_name}"
        else:
            value = request.form.get("value")
            reason = request.form.get("reason", "").strip()
            ok, error = save_article_override(article_id, field_name, value, reason)
            if ok:
                message = f"已保存字段：{field_name}"
            else:
                message = error
                message_type = "error"

    detail = query_master_article_detail(article_id)
    return render_template(
        "master_article_detail.html",
        detail=detail,
        editable_fields=sorted(EDITABLE_FIELDS),
        message=message,
        message_type=message_type,
    )


@bp.route("/master/pending/<int:pending_id>", methods=["POST"])
def master_pending_action(pending_id):
    action = request.form.get("action", "").strip()
    message = None
    message_type = "success"

    if action == "ignore":
        update_pending_status(pending_id, "ignored")
        message = f"已忽略待确认记录 #{pending_id}"
    elif action == "done":
        update_pending_status(pending_id, "resolved")
        message = f"已标记完成待确认记录 #{pending_id}"
    elif action == "associate":
        article_id = request.form.get("article_id", "").strip()
        if not article_id:
            message = "请填写要关联的文章 ID"
            message_type = "error"
        else:
            ok, error = resolve_pending_associate(pending_id, int(article_id))
            if ok:
                message = f"已把待确认记录 #{pending_id} 关联到文章 {article_id}"
            else:
                message = error
                message_type = "error"
    elif action == "create":
        title = request.form.get("title", "").strip()
        publish_date = request.form.get("publish_date", "").strip() or None
        ok, error = resolve_pending_create(pending_id, title, publish_date=publish_date)
        if ok:
            message = f"已从待确认记录 #{pending_id} 新建文章"
        else:
            message = error
            message_type = "error"
    else:
        pending = get_pending_record(pending_id)
        message = f"未知操作：{action}" if pending else "待确认记录不存在"
        message_type = "error"

    return _render_master_page(message=message, message_type=message_type)
