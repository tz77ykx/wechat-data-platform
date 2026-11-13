"""
解析微信公众号后台导出的各类 xls 文件。

支持格式：
  - tendency_*.xls        真 XLS（xlrd）  数据趋势（三个并排子表）
  - user_analysis.xls     HTML 伪 XLS     用户增减
  - menu_analysis.xls     HTML 伪 XLS     菜单分析
  - message_analysis.xls  HTML 伪 XLS     消息发送
  - 数据明细_*.xls         真 XLS（xlrd）  单篇文章详情
"""

import re
import sys
from datetime import datetime, date
from pathlib import Path

import xlrd
from bs4 import BeautifulSoup


class TendencyFileParser:

    def parse(self, filepath: str) -> dict:
        wb = xlrd.open_workbook(filepath)
        sheet = wb.sheet_by_index(0)

        date_range = self._extract_date_range(sheet)
        daily_reads = self._parse_table1(sheet)
        daily_stats = self._parse_table2(sheet)
        article_sources = self._parse_table3(sheet)

        return {
            "date_range": date_range,
            "daily_reads": daily_reads,
            "daily_stats": daily_stats,
            "article_sources": article_sources,
        }

    # ── 辅助 ──────────────────────────────────────────────────────────────────

    def _extract_date_range(self, sheet) -> str:
        """从标题行提取日期范围字符串，如 '2026.02.05-2026.03.06'"""
        for row_idx in range(min(3, sheet.nrows)):
            for col_idx in range(sheet.ncols):
                cell_val = str(sheet.cell_value(row_idx, col_idx))
                m = re.search(r"\((\d{4}\.\d{2}\.\d{2}-\d{4}\.\d{2}\.\d{2})\)", cell_val)
                if m:
                    return m.group(1)
        return ""

    def _to_date_str(self, val) -> str:
        """将单元格值转为 YYYY-MM-DD 字符串；支持字符串和 xlrd 数值日期"""
        if isinstance(val, float):
            # xlrd 将日期存为数值
            try:
                t = xlrd.xldate_as_tuple(val, 0)
                return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"
            except Exception:
                pass
        s = str(val).strip()
        # 已经是 YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
        # YYYY/MM/DD
        m = re.match(r"^(\d{4})[/.](\d{2})[/.](\d{2})$", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return s

    def _to_int_date_str(self, val) -> str:
        """子表三日期：YYYYMMDD 整数 → YYYY-MM-DD"""
        try:
            s = str(int(float(val))).strip()
            if len(s) == 8:
                return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        except (ValueError, TypeError):
            pass
        return self._to_date_str(val)

    def _to_int(self, val) -> int:
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return 0

    def _to_float(self, val) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    # ── 子表解析 ──────────────────────────────────────────────────────────────

    def _parse_table1(self, sheet) -> list:
        """
        子表一（列 1-3）：每日阅读人数（按渠道）
        col 1: 日期, col 2: 渠道, col 3: 阅读人数
        """
        records = []
        for row_idx in range(3, sheet.nrows):
            date_val = sheet.cell_value(row_idx, 1)
            channel_val = sheet.cell_value(row_idx, 2)
            reads_val = sheet.cell_value(row_idx, 3)

            date_str = str(date_val).strip()
            channel_str = str(channel_val).strip()

            # 跳过空行、表头重复行
            if not date_str or date_str in ("日期", "nan", "0.0", "0"):
                continue
            if not channel_str or channel_str in ("渠道", "nan"):
                continue

            records.append({
                "stat_date": self._to_date_str(date_val),
                "channel": channel_str,
                "read_user": self._to_int(reads_val),
            })
        return records

    def _parse_table2(self, sheet) -> list:
        """
        子表二（列 5-9）：每日汇总指标
        col 5: 日期, col 6: 分享人数, col 7: 跳转阅读原文人数,
        col 8: 微信收藏人数, col 9: 发表篇数
        """
        records = []
        for row_idx in range(3, sheet.nrows):
            date_val = sheet.cell_value(row_idx, 5)
            date_str = str(date_val).strip()

            if not date_str or date_str in ("日期", "nan", "0.0", "0"):
                continue

            records.append({
                "stat_date": self._to_date_str(date_val),
                "share_user": self._to_int(sheet.cell_value(row_idx, 6)),
                "original_read_user": self._to_int(sheet.cell_value(row_idx, 7)),
                "fav_user": self._to_int(sheet.cell_value(row_idx, 8)),
                "article_count": self._to_int(sheet.cell_value(row_idx, 9)),
            })
        return records

    def _parse_table3(self, sheet) -> list:
        """
        子表三（列 11-15）：文章来源概况
        col 11: 传播渠道, col 12: 发表日期(YYYYMMDD整数),
        col 13: 内容标题, col 14: 阅读人数, col 15: 阅读人数占比
        """
        records = []
        for row_idx in range(3, sheet.nrows):
            if sheet.ncols <= 15:
                break

            channel_val = sheet.cell_value(row_idx, 11)
            date_val = sheet.cell_value(row_idx, 12)
            title_val = sheet.cell_value(row_idx, 13)
            reads_val = sheet.cell_value(row_idx, 14)
            ratio_val = sheet.cell_value(row_idx, 15)

            channel_str = str(channel_val).strip()
            title_str = str(title_val).strip()

            # 跳过空行、表头
            if not channel_str or channel_str in ("传播渠道", "nan"):
                continue
            if not title_str or title_str in ("内容标题", "nan"):
                continue
            # 跳过日期为空或0的行
            date_str = str(date_val).strip()
            if not date_str or date_str in ("0", "0.0", "nan", "发表日期"):
                continue

            records.append({
                "channel": channel_str,
                "publish_date": self._to_int_date_str(date_val),
                "title": title_str,
                "read_user": self._to_int(reads_val),
                "read_ratio": self._to_float(ratio_val),
            })
        return records


# ── HTML 伪 XLS 基类 ──────────────────────────────────────────────────────────

class BaseHTMLParser:
    """微信后台导出的 HTML-disguised-as-XLS 文件基类"""

    def _load_rows(self, filepath: str) -> list[list[str]]:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        result = []
        for tr in soup.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            result.append(cells)
        return result

    def _extract_date_range(self, rows: list) -> str:
        """从标题行提取日期范围，如 '2026-02-05至2026-03-07'"""
        for row in rows[:3]:
            for cell in row:
                m = re.search(r"(\d{4}-\d{2}-\d{2})至(\d{4}-\d{2}-\d{2})", cell)
                if m:
                    return f"{m.group(1)}~{m.group(2)}"
        return ""

    @staticmethod
    def _safe_int(v: str) -> int:
        try:
            return int(float(v.replace(",", "")))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(v: str) -> float:
        try:
            return float(v.replace(",", ""))
        except (ValueError, TypeError):
            return 0.0


# ── 用户增减解析器 ─────────────────────────────────────────────────────────────

class UserAnalysisParser(BaseHTMLParser):
    """
    user_analysis.xls（HTML格式）
    columns: 时间 | 新关注人数 | 取消关注人数 | 净增关注人数 | 累积关注人数
    """

    def parse(self, filepath: str) -> dict:
        rows = self._load_rows(filepath)
        date_range = self._extract_date_range(rows)
        records = []
        for row in rows:
            if len(row) < 5:
                continue
            # 日期列格式 YYYY-MM-DD
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", row[0]):
                continue
            records.append({
                "stat_date": row[0],
                "new_user":    self._safe_int(row[1]),
                "cancel_user": self._safe_int(row[2]),
                "net_user":    self._safe_int(row[3]),
                "total_user":  self._safe_int(row[4]),
            })
        return {"date_range": date_range, "records": records}


# ── 菜单分析解析器 ─────────────────────────────────────────────────────────────

class MenuAnalysisParser(BaseHTMLParser):
    """
    menu_analysis.xls（HTML格式）
    columns: 版本 | 一级菜单 | 二级菜单 | 菜单点击次数 | 菜单点击人数 | 人均点击次数
    """

    def parse(self, filepath: str) -> dict:
        rows = self._load_rows(filepath)
        date_range = self._extract_date_range(rows)
        records = []
        for row in rows:
            if len(row) < 6:
                continue
            # 版本列是纯数字字符串（如 2026030601）
            if not re.match(r"^\d{8,10}$", row[0]):
                continue
            records.append({
                "menu_version": row[0],
                "menu_level1":  row[1],
                "menu_level2":  row[2],
                "click_count":  self._safe_int(row[3]),
                "click_user":   self._safe_int(row[4]),
                "avg_click":    self._safe_float(row[5]),
            })
        return {"date_range": date_range, "records": records}


# ── 消息分析解析器 ─────────────────────────────────────────────────────────────

class MessageAnalysisParser(BaseHTMLParser):
    """
    message_analysis.xls（HTML格式）
    columns: 时间 | 消息发送人数 | 消息发送次数 | 人均发送次数
    注意：未开通客服的账号数据全为 '-'
    """

    def parse(self, filepath: str) -> dict:
        rows = self._load_rows(filepath)
        date_range = self._extract_date_range(rows)
        records = []
        for row in rows:
            if len(row) < 4:
                continue
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", row[0]):
                continue
            records.append({
                "stat_date": row[0],
                "msg_user":  self._safe_int(row[1]),
                "msg_count": self._safe_int(row[2]),
                "avg_msg":   self._safe_float(row[3]),
            })
        return {"date_range": date_range, "records": records}


# ── 单篇文章详情解析器 ─────────────────────────────────────────────────────────

class ArticleDetailParser:
    """
    数据明细_*.xls（真 XLS，xlrd）
    数据结构：
      row0  col1 = 文章标题
      row4  col1='阅读(人)'           col2=值
      row5  col1='平均停留时长(秒)'   col2=值
      ...（固定行位置）
      row23 开始：数据趋势明细（日期/渠道/阅读/分享）
    """

    _SUMMARY_FIELDS = {
        "阅读(人)":           "read_user",
        "平均停留时长(秒)":   "avg_read_time",
        "完读率":             "complete_rate",
        "阅读后关注（人）":   "follow_after_read",
        "新增关注（人）":     "follow_after_read",
        "分享(人)":           "share_user",
        "在看(人)":           "like_user",
        "点赞(人)":           "thumbup_user",
        "收藏(人)":           "fav_user",
        "赞赏(分)":           "reward",
        "评论（条）":         "comment_count",
        "送达人数":           "deliver_user",
        "公众号消息阅读人数": "msg_read_user",
        "首次分享人数":       "first_share_user",
        "总分享人数":         "total_share_user",
        "分享产生的阅读人数": "share_read_user",
    }

    def parse(self, filepath: str) -> dict:
        wb = xlrd.open_workbook(filepath)
        sh = wb.sheet_by_index(0)

        title = str(sh.cell_value(0, 1)).strip()
        detail = {"title": title}

        # 扫描键值行
        for r in range(sh.nrows):
            key = str(sh.cell_value(r, 1)).strip()
            if key in self._SUMMARY_FIELDS:
                raw = sh.cell_value(r, 2)
                field = self._SUMMARY_FIELDS[key]
                if field == "complete_rate":
                    detail[field] = float(raw) if raw else 0.0
                else:
                    try:
                        detail[field] = int(float(raw)) if raw else 0
                    except (ValueError, TypeError):
                        detail[field] = 0

        # 数据趋势明细（日期/渠道/阅读/分享）
        trend = []
        in_trend = False
        for r in range(sh.nrows):
            label = str(sh.cell_value(r, 1)).strip()
            if label in {"数据趋势明细", "阅读数据趋势明细"}:
                in_trend = True
                continue
            if in_trend and label == "日期":
                continue  # 跳过表头
            if in_trend and label and not re.match(r"^\d{4}-\d{2}-\d{2}$", label):
                in_trend = False  # 后续分布或其他指标表不属于阅读趋势
            if in_trend and re.match(r"^\d{4}-\d{2}-\d{2}$", label):
                trend.append({
                    "stat_date": label,
                    "channel":   str(sh.cell_value(r, 2)).strip(),
                    "read_user": int(float(sh.cell_value(r, 3) or 0)),
                    "share_user": int(float(sh.cell_value(r, 4) or 0)),
                })

        return {"detail": detail, "trend": trend}


# ── 统一调度入口 ───────────────────────────────────────────────────────────────

def parse_any(filepath: str) -> dict:
    """
    根据文件名自动选择解析器，返回 {type, data} 字典。
    type: 'tendency' | 'user' | 'menu' | 'msg' | 'article_detail'
    """
    name = Path(filepath).name.lower()

    if name.startswith("tendency_"):
        return {"type": "tendency", "data": TendencyFileParser().parse(filepath)}

    # HTML 伪 XLS：读前几字节判断
    with open(filepath, "rb") as f:
        header = f.read(6)
    is_html = header[:5] == b"<html"

    if is_html:
        if "user" in name:
            return {"type": "user", "data": UserAnalysisParser().parse(filepath)}
        if "menu" in name:
            return {"type": "menu", "data": MenuAnalysisParser().parse(filepath)}
        if "message" in name or "msg" in name:
            return {"type": "msg", "data": MessageAnalysisParser().parse(filepath)}

    # 真 XLS：单篇详情
    return {"type": "article_detail", "data": ArticleDetailParser().parse(filepath)}


# ── CLI 测试入口 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_file = Path(__file__).parent.parent.parent / "tendency_1770301045_1772806645.xls"
    if not test_file.exists():
        # 也接受命令行参数
        if len(sys.argv) > 1:
            test_file = Path(sys.argv[1])
        else:
            print(f"测试文件不存在：{test_file}")
            sys.exit(1)

    parser = TendencyFileParser()
    result = parser.parse(str(test_file))

    print(f"日期范围: {result['date_range']}")
    print(f"子表一（每日阅读，按渠道）: {len(result['daily_reads'])} 行")
    if result["daily_reads"]:
        print("  样本:", result["daily_reads"][:3])
    print(f"子表二（每日汇总）: {len(result['daily_stats'])} 行")
    if result["daily_stats"]:
        print("  样本:", result["daily_stats"][:3])
    print(f"子表三（文章来源）: {len(result['article_sources'])} 行")
    if result["article_sources"]:
        print("  样本:", result["article_sources"][:3])
