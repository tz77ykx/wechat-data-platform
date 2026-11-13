"""对标账号爆文移植分析（Claude API）"""

import os
import json
import urllib.request


def analyze_competitor_article(article: dict, my_baseline: dict) -> dict:
    """
    分析对标账号文章的爆点，评估移植可行性，生成改写建议。
    article: {title, read_num, like_num, share_num, comment_count, publish_time, content_text}
    my_baseline: {avg_reads, max_reads, avg_rec_ratio, avg_complete_rate, avg_comments}
    返回: {ok, analysis} 或 {ok, error}
    """
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or
               os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if not api_key:
        return {"ok": False, "error": "请先设置环境变量 ANTHROPIC_API_KEY"}

    my_avg = int(my_baseline.get("avg_reads") or 0)
    my_threshold = int(my_avg * 1.5)
    my_max = int(my_baseline.get("max_reads") or 0)

    content_section = ""
    if article.get("content_text"):
        # 截取前1500字防止超token
        content_section = f"\n\n【文章正文节选（前1500字）】\n{article['content_text'][:1500]}"

    engagement_rate = 0
    if article.get("read_num"):
        total_engage = (article.get("like_num") or 0) + (article.get("share_num") or 0) + (article.get("comment_count") or 0)
        engagement_rate = round(total_engage / article["read_num"] * 100, 2)

    prompt = f"""你是一位微信公众号内容分析师，专注于高校校园类账号。

【对标账号文章数据】
标题：{article['title']}
发布时间：{article.get('publish_time', '未知')}
阅读量：{article.get('read_num', 0):,}
点赞：{article.get('like_num', 0)}，分享：{article.get('share_num', 0)}，留言：{article.get('comment_count', 0)}
互动率：{engagement_rate}%{content_section}

【我的账号基准（大连理工大学校园号）】
历史平均阅读：{my_avg:,}
历史最高阅读：{my_max:,}
爆文门槛（均值×1.5）：{my_threshold:,}
平均完读率：{int((my_baseline.get('avg_complete_rate') or 0)*100)}%
平均推荐占比：{int((my_baseline.get('avg_rec_ratio') or 0)*100)}%

【分析任务】
这篇文章在对标账号表现{"优秀（超过其均值）" if article.get('read_num', 0) > 4500 else "一般"}。
请分析后，严格按以下JSON格式返回（只返回JSON，不要任何其他内容）：

{{
  "topic_type": "选题类型（如：福利活动/学业信息/娱乐互动/刚需资讯/情感共鸣等）",
  "viral_hooks": ["爆点1（15字内）", "爆点2（15字内）"],
  "title_technique": "标题技巧分析（30字内）",
  "compatibility": 75,
  "compatibility_reason": "与我账号的兼容性说明（2句话，说明为什么能/不能移植）",
  "adapted_titles": [
    "改写标题1（加入大工语境）",
    "改写标题2（换角度切入）",
    "改写标题3（强化刚需/悬念）"
  ],
  "predicted_reads": "发类似文章预测我账号阅读区间（如 1500~2500）",
  "key_advice": "最关键的一条改写建议（40字内）"
}}"""

    try:
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        req = urllib.request.Request(
            f"{base_url}/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        raw = result["content"][0]["text"].strip()
        # 提取 JSON（有时模型会加 ```json 包裹）
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        analysis = json.loads(raw)
        return {"ok": True, "analysis": analysis}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"JSON解析失败: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
