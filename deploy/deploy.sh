#!/bin/bash
# =============================================================================
# UMCP 一键部署脚本
# 使用方法: ./deploy.sh /path/to/repo YOUR_DOMAIN
# =============================================================================

set -e

if [ $# -ne 2 ]; then
    echo "用法: ./deploy.sh <项目路径> <你的域名>"
    echo "示例: ./deploy.sh /opt/umcp api.your-domain.com"
    exit 1
fi

PROJECT_DIR="$1"
DOMAIN="$2"

echo "=================================================="
echo "UMCP 部署脚本"
echo "项目路径: $PROJECT_DIR"
echo "域名: $DOMAIN"
echo "=================================================="
echo

# 检查依赖
echo "[1/7] 检查系统依赖..."
command -v docker >/dev/null 2>&1 || { echo "❌ docker 未安装，请先安装 docker"; exit 1; }
command -v docker-compose >/dev/null 2>&1 || command -v docker compose >/dev/null 2>&1 || { echo "❌ docker-compose 未安装，请先安装"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "❌ git 未安装，请先安装"; exit 1; }

# 使用 docker 或 docker-compose
if command -v docker compose >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

# 拉取最新代码
echo
echo "[2/7] 拉取最新代码..."
cd "$PROJECT_DIR"
git pull

# 检查 .env 文件
echo
echo "[3/7] 检查配置文件..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/deploy/.env.production" "$PROJECT_DIR/.env"
    echo "⚠️  .env 文件已创建，请现在手动编辑 $PROJECT_DIR/.env 填写所有必填项"
    echo "编辑完成后按回车继续..."
    read -r
fi

# 生成 Nginx 配置
echo
echo "[4/7] 生成 Nginx 配置..."
sed "s/YOUR_DOMAIN/$DOMAIN/g" "$PROJECT_DIR/deploy/nginx-umcp.conf" > /tmp/umcp.conf
echo "请将以下内容复制到 /etc/nginx/sites-available/$DOMAIN:"
echo "--------------------------------------------------"
cat /tmp/umcp.conf
echo "--------------------------------------------------"
echo
echo "是否已经复制完成？[y/N]"
read -r answer
if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
    echo "部署中止，请复制后重试"
    exit 0
fi

# 启用 Nginx 配置
echo
echo "[5/7] 启用 Nginx 配置..."
mkdir -p /etc/nginx/sites-available
mkdir -p /etc/nginx/sites-enabled
cp /tmp/umcp.conf "/etc/nginx/sites-available/$DOMAIN"
ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
nginx -t && systemctl reload nginx || {
    echo "⚠️  Nginx 配置测试失败，请检查后手动执行 nginx -t 修复"
}

# 申请 SSL 证书
echo
echo "[6/7] 申请 SSL 证书..."
if command -v certbot >/dev/null 2>&1; then
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@"$DOMAIN"
else
    echo "⚠️  certbot 未安装，请手动安装后执行: certbot --nginx -d $DOMAIN"
fi

# 启动服务
echo
echo "[7/7] 启动服务..."
cd "$PROJECT_DIR"
$DOCKER_COMPOSE -f docker-compose.prod.yml pull
$DOCKER_COMPOSE -f docker-compose.prod.yml build
$DOCKER_COMPOSE -f docker-compose.prod.yml up -d

echo
echo "=================================================="
echo "✅ 部署完成！"
echo
echo "服务地址: https://$DOMAIN"
echo "健康检查: https://$DOMAIN/api/v1/health"
echo
echo "查看日志: $DOCKER_COMPOSE -f docker-compose.prod.yml logs -f app"
echo "重启服务: $DOCKER_COMPOSE -f docker-compose.prod.yml restart app"
echo "=================================================="
