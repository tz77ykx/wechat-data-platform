"""批量分析所有对标账号的爆文（跳过已分析的）。"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.database import get_conn, query_baseline_summary, save_viral_analysis
from core.competitor_ai import analyze_competitor_article


def get_viral_articles():
    """返回所有待分析的爆文列表。"""
    conn = get_conn()
    accounts = conn.execute("""
        SELECT ca.id, ca.nickname, AVG(a.read_num) as avg_reads
        FROM competitor_articles a
        JOIN competitor_accounts ca ON ca.id = a.account_id
        GROUP BY a.account_id
    """).fetchall()

    articles = []
    for acc in accounts:
        threshold = (acc["avg_reads"] or 0) * 1.5
        rows = conn.execute("""
            SELECT * FROM competitor_articles
            WHERE account_id = ? AND read_num > ? AND viral_analysis IS NULL
            ORDER BY read_num DESC
        """, (acc["id"], threshold)).fetchall()
        for r in rows:
            articles.append({"article": dict(r), "nickname": acc["nickname"]})

    conn.close()
    return articles


def analyze_one(item, baseline):
    """分析单篇文章，返回 (article_id, nickname, title, ok, error_or_none)。"""
    art = item["article"]
    aid = art["id"]
    title = art["title"][:30]
    nickname = item["nickname"]
    try:
        result = analyze_competitor_article(art, baseline)
        if result["ok"]:
            save_viral_analysis(aid, json.dumps(result["analysis"], ensure_ascii=False))
            return (aid, nickname, title, True, None)
        else:
            return (aid, nickname, title, False, result.get("error", "unknown"))
    except Exception as e:
        return (aid, nickname, title, False, str(e))


def main():
    baseline = query_baseline_summary()
    articles = get_viral_articles()
    total = len(articles)

    if total == 0:
        print("没有待分析的爆文。")
        return

    print(f"共 {total} 篇爆文待分析，开始批量处理...\n")

    done = 0
    ok_count = 0
    fail_count = 0
    start = time.time()

    # 3 并发（避免 API 限频）
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(analyze_one, item, baseline): item for item in articles}
        for future in as_completed(futures):
            done += 1
            aid, nickname, title, success, err = future.result()
            elapsed = time.time() - start
            rate = done / elapsed * 60 if elapsed > 0 else 0

            if success:
                ok_count += 1
                status = "OK"
            else:
                fail_count += 1
                status = f"FAIL: {err}"

            print(f"[{done}/{total}] {nickname} | {title} | {status}  ({rate:.0f}篇/分钟)")
            sys.stdout.flush()

    elapsed = time.time() - start
    print(f"\n完成！成功 {ok_count}，失败 {fail_count}，耗时 {elapsed:.0f} 秒")


if __name__ == "__main__":
    main()
