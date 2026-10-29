#!/usr/bin/env bash
# 在目标服务器上执行：把法规检索页挂到 nginx 的 /law/ 子路径。
#
#   bash deploy-law-site.sh                    # 从 GitHub raw 拉取
#   bash deploy-law-site.sh <地址或本地文件>
#
# 设计约束：
#   1. 绝不改动 nav-site 的既有 location，只在 listen 80 的 server 块里插一行 include
#   2. 改配置前先备份，nginx -t 失败自动回滚 —— 不允许把线上站点搞挂
#   3. 幂等：重复执行只覆盖 index.html，不会重复插入 include
set -euo pipefail

DEFAULT_SRC="https://raw.githubusercontent.com/6June6/bidding-law-library/main/index.html"
FALLBACK_SRC="https://bidding-law-search.app.workbuddy.host/"
SRC="${1:-$DEFAULT_SRC}"
TARGET_DIR="/srv/law"
TARGET="$TARGET_DIR/index.html"
STAMP="$(date +%Y%m%d-%H%M%S)"

log() { printf '\033[36m[law]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[law] 失败：\033[0m%s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "需要 root 执行（云助手默认就是 root）"

# ---------- 1) 取文件 ----------
mkdir -p "$TARGET_DIR"
log "获取检索页：$SRC"
if [ -f "$SRC" ]; then
  cp -f "$SRC" "$TARGET"
else
  curl -fsSL --max-time 300 -o "$TARGET.part" "$SRC" || {
    log "主源失败，改用托管地址"
    curl -fsSL --max-time 300 -o "$TARGET.part" "$FALLBACK_SRC"
  }
  mv -f "$TARGET.part" "$TARGET"
fi
chmod 644 "$TARGET"

SIZE=$(stat -c%s "$TARGET" 2>/dev/null || echo 0)
log "文件大小：$((SIZE/1024/1024)) MB"
[ "$SIZE" -gt 5000000 ] || die "文件过小（${SIZE} 字节），下载不完整"
grep -q 'id="blob"' "$TARGET" || die "内容不像检索页（缺少 blob 脚本），拒绝部署"

# 预压缩一份：2 核机器上不建议每次现压 7.8MB，gzip_static 直接发这个文件
gzip -9 -c "$TARGET" > "$TARGET.gz"
log "预压缩：$(( $(stat -c%s "$TARGET.gz") / 1024 )) KB（原 $((SIZE/1024/1024)) MB）"

# ---------- 2) 定位 nginx ----------
NGINX_BIN=$(command -v nginx || echo /usr/sbin/nginx)
[ -x "$NGINX_BIN" ] || die "未找到 nginx"

SNIPPET="/etc/nginx/law-snippets/law.conf"
mkdir -p "$(dirname "$SNIPPET")"
cat > "$SNIPPET" <<'NGX'
# 由 deploy-law-site.sh 生成：招投标法律法规离线检索页（单文件、无后端）
location = /law { return 301 /law/; }
location /law/ {
    alias /srv/law/;
    index index.html;
    # 预压缩文件直接发，不必每次现压 7.8MB（2 核机器上有实际收益）
    gzip_static on;
    gzip on;
    add_header Cache-Control "public, max-age=3600";
}
NGX

# ---------- 3) 在 listen 80 的 server 块里挂上 include ----------
CONF_MOD=""
if "$NGINX_BIN" -T 2>/dev/null | grep -q "include $SNIPPET;"; then
  log "include 已存在，跳过配置注入"
  CONF_MOD=$(for f in /etc/nginx/nginx.conf /etc/nginx/conf.d/*.conf; do
               grep -l "include $SNIPPET;" "$f" 2>/dev/null && break; done | head -1)
else
  # 必须插进「真正 listen 80」的块：若插到 443 的块，/law/ 就挂在不通的端口上。
  CONF_MOD=$(python3 - "$SNIPPET" "$NGINX_BIN" "$STAMP" <<'PY'
import re, subprocess, sys, shutil

snippet, nbin, stamp = sys.argv[1], sys.argv[2], sys.argv[3]
dump = subprocess.run([nbin, "-T"], capture_output=True, text=True)
parts = re.split(r"^# configuration file (\S+):$", dump.stdout or "", flags=re.M)
files = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
if not files:                       # -T 不可用时只看主配置
    p = "/etc/nginx/nginx.conf"
    files = [(p, open(p).read())]

def server_blocks(src):
    """server 块不会嵌套，按行首匹配 + 括号配平取整块"""
    lines, out, i = src.split("\n"), [], 0
    while i < len(lines):
        if re.match(r"\s*server\s*\{", lines[i].split("#")[0]):
            d, j, header = 0, i, ""
            while j < len(lines):
                s = lines[j].split("#")[0]
                d += s.count("{") - s.count("}")
                header += s + "\n"
                if d <= 0:
                    break
                j += 1
            out.append((i, header))
            i = j + 1
            continue
        i += 1
    return out

target = None
for path, content in files:
    for start, header in server_blocks(content):
        has80 = re.search(r"listen\s+(?:[^\s;]*:)?80\b", header)
        plain = re.search(r"\blisten\b", header) and "ssl" not in header and "443" not in header
        if has80 or plain:
            target = (path, content, start)
            break
    if target:
        break

if not target:
    sys.stderr.write("没有找到监听 80 的 server 块\n")
    sys.exit(1)

path, content, start = target
lines = content.split("\n")
if "{" not in lines[start]:          # 只支持「server {」单行开头，避免插错层
    sys.stderr.write("server 块起始行不是单行 server { 形式，放弃注入\n")
    sys.exit(1)

shutil.copy2(path, "%s.bak-%s" % (path, stamp))
lines.insert(start + 1, "    include %s;" % snippet)
open(path, "w").write("\n".join(lines))
sys.stderr.write("[law] 已备份并注入：%s（第 %d 行 server 块）\n" % (path, start + 1))
print(path)
PY
) || die "配置注入失败，未做任何改动"
  log "注入目标：$CONF_MOD"
fi

# ---------- 4) 语法校验，失败回滚 ----------
if ! "$NGINX_BIN" -t 2>/tmp/nginx-t.log; then
  cat /tmp/nginx-t.log >&2
  if [ -n "$CONF_MOD" ] && [ -f "$CONF_MOD.bak-$STAMP" ]; then
    cp -a "$CONF_MOD.bak-$STAMP" "$CONF_MOD"
    log "已从备份回滚：$CONF_MOD.bak-$STAMP"
  elif [ -n "$CONF_MOD" ]; then
    sed -i "\|include $SNIPPET;|d" "$CONF_MOD"
    log "已移除注入行"
  fi
  die "nginx -t 未通过，配置已还原"
fi
log "nginx -t 通过"

# ---------- 5) reload 并自检 ----------
"$NGINX_BIN" -s reload 2>/dev/null || systemctl reload nginx
sleep 1

CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1/law/ || echo 000)
log "本机自检 http://127.0.0.1/law/ → HTTP $CODE"

# 注意：不要写成 `curl ... | head -c 300 | grep -q`。set -o pipefail 下 head 提前关闭
# 管道会让 curl 收到 SIGPIPE 返回非零，整条管道假失败——曾因此误报「内容异常」。
# 先落文件再检查，判据才可靠。
SELF=/tmp/law-self-check.html
if curl -s --max-time 15 -o "$SELF" http://127.0.0.1/law/ && grep -qi '<title>' "$SELF"; then
  GOT=$(( $(stat -c%s "$SELF") / 1024 / 1024 ))
  log "内容校验通过（${GOT} MB，标题正常）"
  rm -f "$SELF"
else
  log "警告：返回内容异常，请检查 alias 路径与 selinux"
fi

# 校验预压缩是否真的生效
CE=$(curl -s -o /dev/null -D - -H 'Accept-Encoding: gzip' --max-time 10 \
       http://127.0.0.1/law/ | grep -ic 'content-encoding: gzip' || true)
[ "$CE" -ge 1 ] && log "gzip 生效（预压缩文件已命中）" || log "提示：gzip 未生效，检查 gzip_static 模块"

NAV=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1/ || echo 000)
log "导航站自检 http://127.0.0.1/ → HTTP $NAV（200 表示未受影响）"

cat <<EOF

完成。外部地址：http://43.142.60.131/law/

回滚：
  sed -i "\\|include $SNIPPET;|d" ${CONF_MOD:-<注入的配置文件>}
  $NGINX_BIN -t && $NGINX_BIN -s reload
EOF
