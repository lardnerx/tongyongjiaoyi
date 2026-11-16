#!/bin/bash
# =============================================================================
# 按 Git 引用从 jsDelivr 同步源码到服务器，并按需重启后端/前端
#
# 用法:
#   ./sync.sh <ref>            # 同步并重启（ref = commit SHA 或分支名）
#   ./sync.sh <ref> api        # 仅后端
#   ./sync.sh <ref> web        # 仅前端
#   ./sync.sh main             # 用分支最新（jsDelivr 对分支有缓存，生产建议用 SHA）
#
# 说明:
#   - 覆盖哪些文件由 deploy/sync-manifest.txt 决定，改文件清单请改该清单
#   - 不会触碰 .env；数据库、证书、pm2/systemd 配置均不在同步范围
#   - 任一健康检查失败会以非 0 退出，方便人工介入
# =============================================================================
set -euo pipefail

REPO="lardnerx/tongyongjiaoyi"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REF="${1:-main}"
SCOPE="${2:-all}"

case "$SCOPE" in
    all | api | web) ;;
    *)
        echo "用法: $0 <ref> [all|api|web]" >&2
        exit 2
        ;;
esac

MIRRORS=(
    "https://cdn.jsdelivr.net/gh/${REPO}@${REF}"
    "https://fastly.jsdelivr.net/gh/${REPO}@${REF}"
    "https://gcore.jsdelivr.net/gh/${REPO}@${REF}"
)

fetch() {
    local path="$1" dest="$2" tmp base
    mkdir -p "$(dirname "$dest")"
    tmp="$(mktemp)"
    for base in "${MIRRORS[@]}"; do
        if curl -fsSL --retry 2 --max-time 30 "${base}/${path}" -o "$tmp"; then
            mv "$tmp" "$dest"
            echo "  ok   ${path}"
            return 0
        fi
    done
    rm -f "$tmp"
    echo "  FAIL ${path}" >&2
    return 1
}

echo "[1/4] 拉取同步清单 ref=${REF}"
MANIFEST="/tmp/umcp-sync-manifest.$$"
fetch "deploy/sync-manifest.txt" "$MANIFEST"

mapfile -t FILES < <(grep -vE '^[[:space:]]*(#|$)' "$MANIFEST")
rm -f "$MANIFEST"
echo "      共 ${#FILES[@]} 个文件"

echo "[2/4] 同步文件到 ${ROOT}"
api_changed=0
web_changed=0
for f in "${FILES[@]}"; do
    case "$f" in
        web/*)
            [ "$SCOPE" = "api" ] && continue
            web_changed=1
            ;;
        *)
            [ "$SCOPE" = "web" ] && continue
            api_changed=1
            ;;
    esac
    fetch "$f" "${ROOT}/${f}"
done

if [ "$api_changed" -eq 1 ]; then
    echo "[3/4] 重启后端 umcp"
    systemctl restart umcp
    sleep 6
    code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/health || true)"
    echo "      health=${code}"
    if [ "$code" != "200" ]; then
        echo "后端健康检查失败，请执行: journalctl -u umcp -n 50 --no-pager" >&2
        exit 1
    fi
else
    echo "[3/4] 跳过后端重启（无后端文件或 scope=web）"
fi

if [ "$web_changed" -eq 1 ]; then
    echo "[4/4] 重建前端 web"
    cd "${ROOT}/web"
    npm run build
    pm2 restart web
    sleep 8
    code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/login || true)"
    echo "      login=${code}"
    if [ "$code" != "200" ]; then
        echo "前端健康检查失败，请执行: pm2 logs web --lines 50" >&2
        exit 1
    fi
else
    echo "[4/4] 跳过前端重建（无前端文件或 scope=api）"
fi

echo "同步完成 ref=${REF} scope=${SCOPE}"
