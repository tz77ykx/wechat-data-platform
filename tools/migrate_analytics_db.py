#!/usr/bin/env python3
"""一次性迁移工具：把旧 analytics 库导入新的 master 库。"""
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = (
    Path.home()
    / "Documents"
    / "公众号后台助手"
    / "projects"
    / "wechat_analytics"
    / "wechat_analytics.db"
)
DEFAULT_DST = ROOT / "wechat_master.db"


def main():
    src = Path(os.environ.get("LEGACY_DB_PATH", str(DEFAULT_SRC))).expanduser()
    dst = Path(os.environ.get("MASTER_DB_PATH", str(DEFAULT_DST))).expanduser()

    if not src.exists():
        print(f"❌ 旧数据库不存在：{src}")
        return

    if dst.exists():
        ans = input(f"⚠️  目标主库已存在（{dst.stat().st_size / 1024 / 1024:.1f} MB），覆盖重建？[y/N] ")
        if ans.strip().lower() != "y":
            print("取消。")
            return
        dst.unlink()

    os.environ["DB_PATH"] = str(src)
    os.environ["MASTER_DB_PATH"] = str(dst)
    sys.path.insert(0, str(ROOT))

    from core.master_db import bootstrap_master_from_analytics  # noqa: PLC0415

    summary = bootstrap_master_from_analytics()
    print(f"✅ 迁移完成：{src.name} -> {dst}")
    print(
        "   文章 {articles} 篇，日趋势 {daily_metrics} 条，用户 {users} 条，消息 {messages} 条，菜单 {menus} 条".format(
            **summary
        )
    )


if __name__ == "__main__":
    main()
