import unittest
from unittest.mock import patch

from core.parser import ArticleDetailParser


class Sheet:
    def __init__(self, rows):
        self.rows = rows
        self.nrows = len(rows)

    def cell_value(self, row, column):
        return self.rows[row][column]


class ArticleDetailParserTests(unittest.TestCase):
    def parse_rows(self, rows):
        with patch("core.parser.xlrd.open_workbook") as open_workbook:
            open_workbook.return_value.sheet_by_index.return_value = Sheet(rows)
            return ArticleDetailParser().parse("detail.xls")

    def test_current_export_reads_followers_and_reading_trend(self):
        result = self.parse_rows([
            ["", "测试文章", "", "", ""],
            ["", "阅读(人)", 2203, "", ""],
            ["", "新增关注（人）", 42, "", ""],
            ["", "阅读数据趋势明细", "", "", ""],
            ["", "日期", "传播渠道", "阅读人数", "分享人数"],
            ["", "2026-10-09", "全部", 1774, 281],
            ["", "2026-10-09", "推荐", 79, 0],
        ])
        self.assertEqual(result["detail"]["follow_after_read"], 42)
        self.assertEqual(len(result["trend"]), 2)
        self.assertEqual(result["trend"][0]["share_user"], 281)
        self.assertEqual(result["trend"][1]["read_user"], 79)

    def test_legacy_export_still_reads_followers_and_trend(self):
        result = self.parse_rows([
            ["", "旧文章", "", "", ""],
            ["", "阅读后关注（人）", 9, "", ""],
            ["", "数据趋势明细", "", "", ""],
            ["", "日期", "渠道", "阅读", "分享"],
            ["", "2026-03-01", "全部", 100, 5],
        ])
        self.assertEqual(result["detail"]["follow_after_read"], 9)
        self.assertEqual(result["trend"][0]["read_user"], 100)

    def test_other_sections_are_not_interpreted_as_reading_trend(self):
        result = self.parse_rows([
            ["", "测试文章", "", "", ""],
            ["", "阅读数据趋势明细", "", "", ""],
            ["", "日期", "传播渠道", "阅读人数", "分享人数"],
            ["", "2026-10-09", "全部", 100, 5],
            ["", "新增关注数据趋势明细", "", "", ""],
            ["", "2026-10-09", "全部", 9, 0],
        ])
        self.assertEqual(len(result["trend"]), 1)


if __name__ == "__main__":
    unittest.main()
