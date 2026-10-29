#!/usr/bin/env bash
# 本地执行：把刚生成的 index.html 推到服务器并挂到 /law/
#
#   bash tools/push-to-server.sh            # 用 ~/.ssh/config 里的 nav
#   bash tools/push-to-server.sh nav4       # 换成别的 Host（如 IPv4 入口）
#
# 前提：ssh 该 Host 能免密登录且 sudo 免密（ops 账号 + wheel 组）。
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${1:-nav}"
IDX="index.html"
REMOTE=/tmp/index.html

[ -f "$IDX" ] || { echo "缺少 $IDX，先跑 python3 tools/render.py" >&2; exit 1; }
SIZE=$(wc -c < "$IDX")
[ "$SIZE" -gt 5000000 ] || { echo "$IDX 只有 $SIZE 字节，像是没生成完整" >&2; exit 1; }
grep -q 'id="blob"' "$IDX" || { echo "$IDX 缺少 blob 脚本，拒绝上传" >&2; exit 1; }

echo "▸ 上传 $(printf '%.1f' "$(echo "$SIZE/1048576" | bc -l)") MB 到 $HOST"
scp -q "$IDX" "$HOST:$REMOTE"
scp -q tools/deploy-law-site.sh "$HOST:/tmp/deploy-law-site.sh"

echo "▸ 远端部署"
ssh "$HOST" "sudo bash /tmp/deploy-law-site.sh $REMOTE && sudo cp -f /tmp/deploy-law-site.sh /srv/law/ && rm -f $REMOTE"

echo
echo "在线地址：http://43.142.60.131/law/"
