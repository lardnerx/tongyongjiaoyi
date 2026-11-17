#!/bin/bash
# =============================================================================
# /opt/umcp/deploy/backup.sh —— UMCP 每日备份（本地）
#
# 内容：PostgreSQL 全库 dump + /opt/umcp/.env 与 certs/ 打包
# 目录：/var/backups/umcp（700），默认保留 14 天
# 自检：dump 非空且 pg_restore --list 可读
# 成功：touch /var/backups/umcp/.last_success（供 healthwatch 判新鲜度）
# 失败：写 /var/log/umcp/healthwatch.log 并返回非 0
#
# 异地副本（COS/OSS）待对象存储开通后在本脚本末尾追加 rclone 上传。
#
# 恢复方式（dump 属 root 600，需 root 读文件、postgres 执行恢复）：
#   sudo -u postgres createdb umcp_restore_test
#   sudo -u postgres pg_restore -d umcp_restore_test --no-owner < /var/backups/umcp/umcp_XXXX.dump
# =============================================================================
set -uo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/umcp}"
DB_NAME="${DB_NAME:-umcp}"
KEEP_DAYS="${KEEP_DAYS:-14}"
LOG_FILE="${LOG_FILE:-/var/log/umcp/healthwatch.log}"
STAMP="$(date +%Y%m%d_%H%M)"
DUMP="$BACKUP_DIR/umcp_${STAMP}.dump"
SECRETS="$BACKUP_DIR/umcp_secrets_${STAMP}.tar.gz"

mkdir -p "$BACKUP_DIR" "$(dirname "$LOG_FILE")"
chmod 700 "$BACKUP_DIR"

fail() {
    printf '%s [ALERT] backup 失败: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG_FILE"
    rm -f "$DUMP" "$SECRETS"
    exit 1
}

# 1) 数据库全量导出（root 负责写文件，pg_dump 以 postgres 身份读取）
sudo -u postgres pg_dump -Fc -d "$DB_NAME" >"$DUMP" || fail "pg_dump 执行失败"
[ -s "$DUMP" ] || fail "dump 文件为空"
pg_restore --list "$DUMP" >/dev/null 2>&1 || fail "pg_restore --list 自检失败"
chmod 600 "$DUMP"

# 2) 配置与证书（含密钥，仅 root 可读）
if [ -f /opt/umcp/.env ]; then
    tar -czf "$SECRETS" -C /opt/umcp .env certs 2>/dev/null || fail "打包 .env/certs 失败"
    chmod 600 "$SECRETS"
fi

# 3) 清理过期备份
find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'umcp_*.dump' -o -name 'umcp_secrets_*.tar.gz' \) \
    -mtime +"$KEEP_DAYS" -delete

# 4) 成功标记（healthwatch 依据它的 mtime 判断备份是否过期）
touch "$BACKUP_DIR/.last_success"
printf '%s [INFO] backup 完成: %s (%s)\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" \
    "$(basename "$DUMP")" \
    "$(du -h "$DUMP" | cut -f1)" >>"$LOG_FILE"

exit 0
