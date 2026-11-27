#!/bin/bash
# =============================================================================
# /opt/umcp/deploy/verify.sh —— 部署后验证脚本
#
# 针对本轮架构整改（P0-1～P0-4、P1-5～P1-9、P2-10～P2-12）逐项验证：
#   A. 运行态接口（只读）：健康检查、就绪检查、OpenAPI 新增路由
#   B. 插件声明式装配：匹配/计价/信任/预约策略/路由/规则默认值/通知模板
#   C. 核心接线：ResourceRegistry、L6 推荐入口、L7 仲裁、复合任务/争议路由
#
# 用法（在服务器上执行）：
#   bash deploy/verify.sh                          # 默认 http://127.0.0.1:8000
#   bash deploy/verify.sh --base-url https://jishi100.online
#   bash deploy/verify.sh --skip-http              # 只做本地代码/装配检查
#   bash deploy/verify.sh --skip-runtime           # 只做 HTTP 检查
#   PYTHON=/opt/umcp/.venv/bin/python bash deploy/verify.sh
#
# 退出码：0 全部通过；1 存在失败项。脚本只读，不写业务数据。
# =============================================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SKIP_HTTP=0
SKIP_RUNTIME=0
CURL_TIMEOUT="${CURL_TIMEOUT:-10}"

while [ $# -gt 0 ]; do
    case "$1" in
        --base-url) BASE_URL="$2"; shift 2 ;;
        --skip-http) SKIP_HTTP=1; shift ;;
        --skip-runtime) SKIP_RUNTIME=1; shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "未知参数: $1（用 --help 查看用法）" >&2; exit 2 ;;
    esac
done

PASS=0
FAIL=0
SKIP=0

ok()   { PASS=$((PASS + 1)); printf '  \033[32m✅\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  \033[31m❌\033[0m %s\n' "$1"; }
skip() { SKIP=$((SKIP + 1)); printf '  \033[33m⏭\033[0m %s\n' "$1"; }
title(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
# A. 运行态接口（只读）
# ---------------------------------------------------------------------------
http_get() {
    curl -sS -m "$CURL_TIMEOUT" "$1" 2>/dev/null || true
}

check_http() {
    title "A. 运行态接口（$BASE_URL）"

    local body code
    body="$(curl -sS -m "$CURL_TIMEOUT" -w '\n%{http_code}' "$BASE_URL/api/v1/health" 2>/dev/null || true)"
    code="$(printf '%s' "$body" | tail -n1)"
    if [ "$code" = "200" ] && printf '%s' "$body" | grep -q '"status":"ok"'; then
        ok "GET /api/v1/health 200 且 status=ok"
    else
        bad "GET /api/v1/health 异常（http=${code:-N/A}）"
    fi

    body="$(curl -sS -m "$CURL_TIMEOUT" -w '\n%{http_code}' "$BASE_URL/api/v1/health/ready" 2>/dev/null || true)"
    code="$(printf '%s' "$body" | tail -n1)"
    if [ "$code" = "200" ] && printf '%s' "$body" | grep -q '"ready":true'; then
        ok "GET /api/v1/health/ready 200 且 ready=true"
    else
        bad "GET /api/v1/health/ready 异常（http=${code:-N/A}）"
    fi

    local spec
    spec="$(http_get "$BASE_URL/openapi.json")"
    if [ -z "$spec" ]; then
        bad "GET /openapi.json 无响应，无法核对路由"
        return
    fi
    local path
    for path in \
        "/api/v1/lbs/nearby" \
        "/api/v1/lbs/resources/{resource_id}/location" \
        "/api/v1/tasks/composite" \
        "/api/v1/deals/{deal_id}/dispute" \
        "/api/v1/deals/{deal_id}/arbitrate" \
        "/api/v1/trust/profiles/{user_id}/aggregate"
    do
        if printf '%s' "$spec" | grep -q "\"${path}\""; then
            ok "OpenAPI 已注册 ${path}"
        else
            bad "OpenAPI 缺少 ${path}（对应文件未同步或服务未重启）"
        fi
    done
}

# ---------------------------------------------------------------------------
# B/C. 本地代码与装配检查（调用服务同款 Python 解释器）
# ---------------------------------------------------------------------------
detect_python() {
    local candidate
    for candidate in "${PYTHON:-}" "$ROOT/.venv/bin/python" "$ROOT/venv/bin/python" python3 python; do
        [ -z "$candidate" ] && continue
        if command -v "$candidate" >/dev/null 2>&1 \
            && PYTHONPATH="$ROOT/src:$ROOT/plugins:$ROOT" "$candidate" -c "import umcp_core.server" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

check_runtime() {
    title "B/C. 代码与装配检查（$ROOT）"

    local py
    if ! py="$(detect_python)"; then
        skip "未找到可导入 umcp_core 的 Python（可用 PYTHON=/path/to/python 指定）"
        return
    fi

    UMCP_ROOT="$ROOT" PYTHONPATH="$ROOT/src:$ROOT/plugins:$ROOT" "$py" - <<'PY'
import importlib
import json
import os
import sys
import traceback
from pathlib import Path

root = Path(os.environ["UMCP_ROOT"])
fails = []


def check(name, fn):
    try:
        detail = fn()
        print(f"  \033[32m✅\033[0m {name}" + (f"（{detail}）" if detail else ""))
    except Exception as exc:  # noqa: BLE001 - 验证脚本需要展示任意失败原因
        fails.append(name)
        print(f"  \033[31m❌\033[0m {name}: {exc}")
        if os.environ.get("VERIFY_DEBUG"):
            traceback.print_exc()


# ---- 1. 关键文件 ----
def files_present():
    required = [
        "plugins/escort_driving/plugin.json",
        "plugins/escort_driving/components.py",
        "plugins/escort_driving/workers/realtime_cancel.py",
        "src/umcp_core/layers/l2/abstraction.py",
    ]
    missing = [p for p in required if not (root / p).exists()]
    assert not missing, f"缺少文件: {missing}"
    return f"{len(required)} 个"


check("关键整改文件齐全", files_present)


# ---- 2. 插件清单声明完整 ----
def manifest_declared():
    data = json.loads((root / "plugins/escort_driving/plugin.json").read_text(encoding="utf-8"))
    required = [
        "match_strategy",
        "payment_schema",
        "trust_engine",
        "scheduled_match_strategy",
        "routers",
        "rule_defaults",
        "notification_templates",
        "access_rule_expression",
    ]
    missing = [k for k in required if k not in data]
    assert not missing, f"清单缺少声明: {missing}"
    return "match/payment/trust/scheduled/routers/rule_defaults/templates"


check("plugin.json 声明式配置完整", manifest_declared)


# ---- 3. 装配结果 ----
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import StandardTask
from umcp_core.layers.l2 import RepositoryResourceRegistry
from umcp_core.server import UMCPServer


def build_server():
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    return server


server = None
try:
    server = build_server()
    print("  \033[32m✅\033[0m 插件 escort_driving 加载成功")
except Exception as exc:  # noqa: BLE001
    fails.append("插件加载")
    print(f"  \033[31m❌\033[0m 插件 escort_driving 加载失败: {exc}")
    traceback.print_exc()

if server is not None:
    def strategy_registered():
        assert server.match_strategy_for("escort") is not None
        assert server.payment_schema_for("escort") is not None
        assert server.trust_engine_for("escort") is not None
        assert server.scheduled_match_strategy_for("escort") is not None
        return type(server.payment_schema_for("escort")).__name__

    check("匹配/计价/信任/预约策略已装配", strategy_registered)

    def rule_defaults_loaded():
        value = server.rule_config.get("escort.pricing.deposit_ratio", default=None)
        assert value == 0.3, f"deposit_ratio={value}"
        return "deposit_ratio=0.3"

    check("规则默认值已写入 RuleConfig", rule_defaults_loaded)

    def templates_loaded():
        assert "DEAL_CREATED" in server.notification_templates
        return f"{len(server.notification_templates)} 个模板"

    check("通知模板已声明", templates_loaded)

    def workers_loaded():
        names = [getattr(w, "name", type(w).__name__) for w in server.scheduler_workers]
        assert "escort_realtime_cancel" in names, names
        return ",".join(names)

    check("实时单超时 Worker 已注册", workers_loaded)

    def exempt_loaded():
        paths = server.rate_limit_exempt_paths
        assert "/api/v1/escort/payments/callback" in paths, paths
        return f"{len(paths)} 条"

    check("支付回调限流豁免已注册", exempt_loaded)

    def registry_wired():
        assert isinstance(server.resource_registry, RepositoryResourceRegistry)
        return type(server.resource_registry).__name__

    check("ResourceRegistry 自动装配", registry_wired)

    def candidates_callable():
        task = StandardTask(demander_id="verify", domain_tag=DomainTag.of("escort"))
        assert isinstance(server.match_candidates(task), list)
        return "空候选也可调用"

    check("match_candidates（L2→L6）可用", candidates_callable)

    def idempotent_manifest():
        from escort_driving import PLUGIN_MANIFEST

        before = len(server.plugin_routers)
        server.apply_manifest(PLUGIN_MANIFEST)
        after = len(server.plugin_routers)
        assert before == after, f"重复装配: {before} -> {after}"
        return f"路由 {after} 组未重复"

    check("apply_manifest 幂等", idempotent_manifest)


# ---- 4. L7 仲裁 ----
from umcp_core.layers.l7 import ArbitrationPolicy, ArbitrationResult, Dispute


def _dispute() -> "Dispute":
    return Dispute(
        dispute_id="dispute_verify",
        deal_id="deal_verify",
        initiator_id="u1",
        respondent_id="u2",
        reason="verify",
    )


def default_arbitration():
    from umcp_core.layers.l7 import RuleEngine

    result = RuleEngine().arbitrate(_dispute())
    assert result.outcome == "cancelled", result.outcome
    return f"outcome={result.outcome}"


check("L7 默认仲裁策略可执行", default_arbitration)


def custom_arbitration():
    class _Policy(ArbitrationPolicy):
        def arbitrate(self, dispute):
            return ArbitrationResult(
                dispute_id=dispute.dispute_id,
                outcome="completed",
                refund_amount=0.0,
                penalty=1.0,
                reason="verify",
            )

    from umcp_core.layers.l7 import RuleEngine

    engine = RuleEngine()
    engine.set_arbitration_policy(_Policy())
    result = engine.arbitrate(_dispute())
    assert result.outcome == "completed", result.outcome
    return "自定义策略已生效"


check("L7 仲裁策略可替换", custom_arbitration)


# ---- 5. 新增路由已注册到 router 对象 ----
def routes_registered():
    expected = {
        "umcp_core.transport.routers.tasks": [("/composite", "POST")],
        "umcp_core.transport.routers.deals": [
            ("/{deal_id}/dispute", "POST"),
            ("/{deal_id}/arbitrate", "POST"),
        ],
        "umcp_core.transport.routers.trust": [
            ("/profiles/{user_id}/aggregate", "GET")
        ],
        "umcp_core.transport.routers.lbs": [
            ("/api/v1/lbs/nearby", "GET"),
            ("/api/v1/lbs/resources/{resource_id}/location", "GET"),
        ],
    }
    missing = []
    for module_name, routes in expected.items():
        module = importlib.import_module(module_name)
        existing = {
            (getattr(r, "path", ""), m)
            for r in module.router.routes
            for m in getattr(r, "methods", set())
        }
        for route in routes:
            if route not in existing:
                missing.append(f"{module_name}:{route[0]}")
    assert not missing, f"未注册: {missing}"
    return "6 条路由"


check("LBS/复合任务/争议仲裁路由已注册", routes_registered)

sys.exit(1 if fails else 0)
PY
    local rc=$?
    if [ $rc -eq 0 ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf '  \033[31m❌\033[0m 代码/装配检查存在失败项\n'
    fi
}

# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
printf '\033[1mUMCP 部署后验证\033[0m\n'
printf '  仓库根:%s\n  接口地址:%s\n' "$ROOT" "$BASE_URL"

[ "$SKIP_HTTP" -eq 0 ] && check_http
[ "$SKIP_RUNTIME" -eq 0 ] && check_runtime

title "结果汇总"
printf '  通过 %d 组，失败 %d 组，跳过 %d 组\n' "$PASS" "$FAIL" "$SKIP"
if [ "$FAIL" -gt 0 ]; then
    printf '\033[31m验证未通过\033[0m，排查：journalctl -u umcp -n 50 --no-pager\n'
    exit 1
fi
printf '\033[32m部署验证通过\033[0m\n'
