#!/bin/bash
set -euo pipefail

REMOTE="${WECHAT_REMOTE:?请通过 WECHAT_REMOTE 设置 SSH 目标，例如 user@host}"
REMOTE_DIR="${WECHAT_REMOTE_DIR:-~/wechat_platform}"
PLATFORM_URL="${WECHAT_PLATFORM_URL:-http://127.0.0.1:5001}"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "同步 wechat_platform 到 Mac mini..."
rsync -avz \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='.pytest_cache/' \
  --exclude='.claude/' \
  --exclude='.superpowers/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='*.zip' \
  --exclude='对标账号/' \
  --exclude='backups/' \
  "$LOCAL_DIR/" "$REMOTE:$REMOTE_DIR/"

echo "远端安装依赖并重启服务..."
ssh "$REMOTE" "cd ~/wechat_platform && bash setup_mac.sh"

echo "验证远端服务..."
sleep 2
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$PLATFORM_URL/")
if [ "$STATUS" = "200" ]; then
  echo "部署成功 $PLATFORM_URL"
else
  echo \"异常，HTTP $STATUS\"
  exit 1
fi
