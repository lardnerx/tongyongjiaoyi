#!/bin/bash
# =============================================================================
# /opt/umcp/deploy/healthwatch.sh —— UMCP 健康巡检
#
# 由 systemd timer 每分钟触发（umcp-healthwatch.timer）。
# 检查项：后端健康接口、公网健康接口、近 5 分钟 5xx、PostgreSQL 连接数、
#         根分区磁盘使用率、备份目录新鲜度（可选）。
#
# 告警只写本地日志（默认 /var/log/umcp/healthwatch.log），同一检查项仅在
# 状态变化（OK→FAIL / FAIL→OK）时记录，避免每分钟刷屏。
#
# 用法：
#   ./healthwatch.sh          # 静默巡检，仅状态变化写日志
#   ./healthwatch.sh -v       # 打印每项检查结果到终端（排障用）
#
# 可用环境变量覆盖：
#   HEALTH_URL_LOCAL     默认 http://127.0.0.1:8000/api/v1/health
#   HEALTH_URL_PUBLIC    默认 https://jishi100.online/api/v1/health
#   DB_CONN_THRESHOLD    默认 80（连接数上限告警阈值）
#   DISK_THRESHOLD       默认 85（根分区使用率百分比）
#   BACKUP_DIR           备份目录；为空则跳过备份新鲜度检查
#   BACKUP_MAX_AGE_HOURS 默认 26
#   LOG_FILE             默认 /var/log/umcp/healthwatch.log
# =============================================================================
set -u

HEALTH_URL_LOCAL="${HEALTH_URL_LOCAL:-http://127.0.0.1:8000/api/v1/health}"
HEALTH_URL_PUBLIC="${HEALTH_URL_PUBLIC:-https://jishi100.online/api/v1/health}"
DB_CONN_THRESHOLD="${DB_CONN_THRESHOLD:-80}"
DISK_THRESHOLD="${DISK_THRESHOLD:-85}"
BACKUP_DIR="${BACKUP_DIR:-}"
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-26}"
LOG_FILE="${LOG_FILE:-/var/log/umcp/healthwatch.log}"
STATE_DIR="${STATE_DIR:-/run/umcp-healthwatch}"
VERBOSE=0
[ "${1:-}" = "-v" ] && VERBOSE=1

mkdir -p "$(dirname "$LOG_FILE")" "$STATE_DIR"

log() {
    local level="$1" msg="$2"
    printf '%s [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$msg" >>"$LOG_FILE"
    [ "$VERBOSE" -eq 1 ] && printf '[%s] %s\n' "$level" "$msg"
}

# report <检查项> <ok|fail> <详情>
# 仅在状态变化时写日志（首次失败也写）
report() {
    local name="$1" status="$2" detail="$3"
    local state_file="$STATE_DIR/$name"
    local prev="unknown"
    [ -f "$state_file" ] && prev="$(cat "$state_file" 2>/dev/null || echo unknown)"

    if [ "$VERBOSE" -eq 1 ]; then
        printf '  %-12s %-4s %s\n' "$name" "$status" "$detail"
    fi

    if [ "$status" = "fail" ] && [ "$prev" != "fail" ]; then
        log "ALERT" "$name 异常: $detail"
    elif [ "$status" = "ok" ] && [ "$prev" = "fail" ]; then
        log "RECOVER" "$name 已恢复: $detail"
    fi
    printf '%s' "$status" >"$state_file"
}

# 1) 后端本地健康接口
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$HEALTH_URL_LOCAL" 2>/dev/null || echo "000")
if [ "$code" = "200" ]; then
    report backend ok "HTTP 200"
else
    report backend fail "HTTP $code ($HEALTH_URL_LOCAL)"
fi

# 2) 公网健康接口（覆盖 nginx / 证书 / 后端链路）
code=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$HEALTH_URL_PUBLIC" 2>/dev/null || echo "000")
if [ "$code" = "200" ]; then
    report public ok "HTTP 200"
else
    report public fail "HTTP $code ($HEALTH_URL_PUBLIC)"
fi

# 3) 近 5 分钟后端 5xx 数量
count=$(journalctl -u umcp --since "-5 min" --no-pager 2>/dev/null \
    | grep -E '" (500|502|503|504) ' | wc -l | tr -d ' ')
if [ "${count:-0}" -eq 0 ]; then
    report http5xx ok "近5分钟 0 条"
else
    report http5xx fail "近5分钟 ${count} 条 5xx"
fi

# 4) PostgreSQL 当前库连接数
conns=$(sudo -u postgres psql -d umcp -tAc \
    "select count(*) from pg_stat_activity where datname='umcp'" 2>/dev/null | tr -d ' ')
if [ -z "${conns:-}" ]; then
    report db fail "无法查询 pg_stat_activity"
elif [ "$conns" -ge "$DB_CONN_THRESHOLD" ]; then
    report db fail "连接数 ${conns} >= ${DB_CONN_THRESHOLD}"
else
    report db ok "连接数 ${conns}"
fi

# 5) 根分区磁盘使用率
used=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
if [ -z "${used:-}" ]; then
    report disk fail "无法读取 df"
elif [ "$used" -ge "$DISK_THRESHOLD" ]; then
    report disk fail "根分区已用 ${used}% >= ${DISK_THRESHOLD}%"
else
    report disk ok "根分区已用 ${used}%"
fi

# 6) 备份新鲜度（未配置 BACKUP_DIR 则跳过）
if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    newest=$(find "$BACKUP_DIR" -maxdepth 1 -type f -printf '%T@\n' 2>/dev/null | sort -n | tail -1)
    if [ -z "${newest:-}" ]; then
        report backup fail "备份目录为空: $BACKUP_DIR"
    else
        now=$(date +%s)
        age_h=$(( (now - ${newest%.*}) / 3600 ))
        if [ "$age_h" -ge "$BACKUP_MAX_AGE_HOURS" ]; then
            report backup fail "最新备份已 ${age_h} 小时前（阈值 ${BACKUP_MAX_AGE_HOURS}h）"
        else
            report backup ok "最新备份 ${age_h} 小时前"
        fi
    fi
fi

exit 0
