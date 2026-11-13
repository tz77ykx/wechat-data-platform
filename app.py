"""公众号管理平台 — Flask 入口"""
import json
from flask import Flask

from config import MAX_CONTENT_LENGTH, PORT
from core.master_db import init_master_db
from core.watcher import start_watcher
from core.scheduler import start_scheduler
from routes import register_blueprints
from routes.api_common import do_import

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Jinja2 自定义过滤器
app.jinja_env.filters["fromjson"] = json.loads
app.jinja_env.globals["max"] = max

init_master_db()
register_blueprints(app)

if __name__ == "__main__":
    start_watcher(do_import)
    start_scheduler()
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)
