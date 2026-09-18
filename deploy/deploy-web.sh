#!/usr/bin/env bash
# 前端一键部署脚本：git pull → 安装依赖 → 生产构建 → 产物校验
# 用法：在服务器仓库根目录执行  bash deploy/deploy-web.sh
# 说明：构建完成后，根据服务器上的实际运行方式发布 web/.next 产物
#       （pm2/systemd 跑 next start，或拷贝到 nginx 静态托管目录）
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/4] 拉取最新代码..."
git pull

echo "[2/4] 安装前端依赖..."
cd web
npm ci

echo "[3/4] 生产构建前端（自动烧录 /api/v1 相对路径，与站点同源）..."
npm run build

echo "[4/4] 校验产物无 localhost 残留..."
if grep -rl "localhost:8000" .next/static 2>/dev/null; then
  echo "!! 产物仍残留 localhost:8000，请检查 web/.env.local 与 web/.env.production"
  exit 1
fi

echo "构建完成，产物目录：$(pwd)/.next"
echo "下一步：按服务器实际运行方式发布产物并重启 web 进程（pm2/systemd/静态托管）。"
