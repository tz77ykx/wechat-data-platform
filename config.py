"""公众号管理平台配置常量"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
MASTER_DB_PATH = Path(os.environ.get("MASTER_DB_PATH", str(BASE_DIR / "wechat_master.db")))
DB_PATH = Path(os.environ.get("DB_PATH", str(MASTER_DB_PATH)))
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

_default_dl = Path.home() / "Downloads" / "Chrome_Downloads"
DOWNLOADS_DIR = Path(os.environ.get("DOWNLOADS_DIR", str(_default_dl)))

MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
PORT = 5001
