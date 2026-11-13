"""Downloads 文件夹监控（后台线程）（从 web_app.py 提取）"""

import time
import threading
from pathlib import Path

from config import DOWNLOADS_DIR, UPLOAD_DIR

# key=(filename, mtime_int)
_seen: dict = {}

WATCHED_PATTERNS = [
    "tendency_*.xls",
    "user_analysis.xls",
    "menu_analysis.xls",
    "message_analysis.xls",
    "数据明细*.xls",
]


def _watcher_loop(do_import_fn):
    """Every 20s scan Downloads folder. do_import_fn is the import callback."""
    for pat in WATCHED_PATTERNS:
        for f in DOWNLOADS_DIR.glob(pat):
            _seen[f.name] = int(f.stat().st_mtime)

    while True:
        time.sleep(20)
        try:
            for pat in WATCHED_PATTERNS:
                for f in DOWNLOADS_DIR.glob(pat):
                    mtime = int(f.stat().st_mtime)
                    if _seen.get(f.name) != mtime:
                        _seen[f.name] = mtime
                        dest = UPLOAD_DIR / f.name
                        dest.write_bytes(f.read_bytes())
                        result = do_import_fn(dest)
                        print(f"[watcher] {result['message']}")
        except Exception as e:
            print(f"[watcher] 扫描出错: {e}")


def start_watcher(do_import_fn):
    t = threading.Thread(target=_watcher_loop, args=(do_import_fn,), daemon=True)
    t.start()


def scan_now(do_import_fn) -> list:
    """Immediately scan and import all matching files."""
    results = []
    for pat in WATCHED_PATTERNS:
        for f in DOWNLOADS_DIR.glob(pat):
            dest = UPLOAD_DIR / f.name
            dest.write_bytes(f.read_bytes())
            result = do_import_fn(dest)
            _seen[f.name] = int(f.stat().st_mtime)
            results.append({"file": f.name, "ok": result["ok"], "message": result["message"]})
    return results
