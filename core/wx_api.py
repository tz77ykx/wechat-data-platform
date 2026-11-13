from __future__ import annotations

"""微信后台 API 工具函数（从 web_app.py 提取）"""

import json
import ssl
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

try:
    import certifi
except ImportError:  # pragma: no cover - fallback for incomplete envs
    class _CertifiFallback:
        @staticmethod
        def where():
            return None

    certifi = _CertifiFallback()

BASE = "https://mp.weixin.qq.com"


def build_download_url(data_type: str, token: str) -> str | None:
    """
    根据真实 URL 样本构造各类数据的下载链接。
    - tendency / menu / user / msg：最近 30 天
    """
    end_dt   = datetime.now()
    begin_dt = end_dt - timedelta(days=30)
    end_date   = end_dt.strftime("%Y-%m-%d")
    begin_date = begin_dt.strftime("%Y-%m-%d")
    end_ts   = int(end_dt.timestamp())
    begin_ts = int(begin_dt.timestamp())

    if data_type == "tendency":
        # /misc/appmsganalysis?action=download_summary_tendency&begin_timestamp=…&end_timestamp=…
        return (
            f"{BASE}/misc/appmsganalysis"
            f"?action=download_summary_tendency"
            f"&begin_timestamp={begin_ts}&end_timestamp={end_ts}"
            f"&token={token}&lang=zh_CN"
        )
    if data_type == "user":
        # /misc/useranalysis?&download=1&begin_date=…&end_date=…&source=99999999
        return (
            f"{BASE}/misc/useranalysis"
            f"?&download=1"
            f"&begin_date={begin_date}&end_date={end_date}"
            f"&source=99999999&token={token}"
        )
    if data_type == "menu":
        # /misc/menuanalysis?&download=1&begin_date=…&end_date=…
        return (
            f"{BASE}/misc/menuanalysis"
            f"?&download=1"
            f"&begin_date={begin_date}&end_date={end_date}"
            f"&token={token}&lang=zh_CN"
        )
    if data_type == "msg":
        # /misc/messageanalysis?begin_date=…&end_date=…&type=daily&download=1
        return (
            f"{BASE}/misc/messageanalysis"
            f"?begin_date={begin_date}&end_date={end_date}"
            f"&type=daily&download=1"
            f"&token={token}&lang=zh_CN"
        )
    return None


def wx_get(path: str, cookies: str, token: str, fingerprint: str) -> dict:
    """
    用 Python 模拟 Chrome 调用微信后台 JSON 接口（仅用于拉取 msgid 列表）。
    path 示例：/misc/appmsganalysis?action=get_article_list&...
    """
    url = "https://mp.weixin.qq.com" + path
    req = urllib.request.Request(url)
    req.add_header("Cookie", cookies)
    req.add_header("User-Agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")
    req.add_header("Referer",
        f"https://mp.weixin.qq.com/misc/appmsganalysis?action=report&type=daily_v2&token={token}&lang=zh_CN")
    req.add_header("X-Requested-With", "XMLHttpRequest")
    req.add_header("Accept", "*/*")
    cafile = certifi.where()
    context = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=15, context=context) as resp:
        return json.loads(resp.read().decode("utf-8"))
