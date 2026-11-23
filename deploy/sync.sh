#!/bin/bash
# =============================================================================
# /opt/umcp/sync.sh —— 服务器代码发布脚本
#
# 【作用】
#   服务器访问 GitHub 不通，所以不走 git pull。
#   本脚本按指定的 Git commit，从 jsDelivr CDN 拉取清单内的源码文件覆盖到
#   /opt/umcp，然后按需重启后端（systemd: umcp）或重建前端（pm2: web），
#   最后做健康检查，失败即报错退出。
#
# 【同步范围】
#   由仓库 deploy/sync-manifest.txt 决定，一行一个文件路径：
#     - web/ 开头的文件 → 触发前端 npm run build + pm2 restart web
#     - 其余文件        → 触发后端 systemctl restart umcp
#   不触碰 .env、数据库、Nginx 配置、证书、pm2/systemd 配置。
#
# 【用法】
#   cd /opt/umcp
#   ./sync.sh <commit SHA>          # 全量：后端 + 前端
#   ./sync.sh <commit SHA> api      # 只更新后端
#   ./sync.sh <commit SHA> web      # 只更新前端
#
# 【发布流程】
#   1) 本地改代码 → git push
#   2) 本地取 commit：git rev-parse HEAD
#   3) 服务器执行：./sync.sh <上面的 SHA>
#   4) 输出末尾出现「同步完成」，且 health=200 / login=200 即发布成功
#
# 【注意】
#   - 生产请用 commit SHA，不要用 main：jsDelivr 对分支有缓存，可能拉到旧文件
#   - 脚本不会自动更新自己，若 sync.sh 本身有改动，重新下载安装一次
#   - 新增要发布的文件，必须在 deploy/sync-manifest.txt 里加一行，否则不会同步
#
# 【失败排查】
#   - 后端失败：journalctl -u umcp -n 50 --no-pager
#   - 前端失败：pm2 logs web --lines 50
#   - 拉取失败：三个镜像 cdn/fastly/gcore 都超时的话，检查服务器出网
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
        # -g/--globoff：路径里含 [id] 这类方括号，必须关闭 curl 的通配符解析
        if curl -fsSL -g --retry 2 --max-time 30 "${base}/${path}" -o "$tmp"; then
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
