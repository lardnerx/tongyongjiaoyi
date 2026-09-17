"""模拟支付超时流程：创建订单 → 支付 → 超时 → 验证状态回滚。

用法：
    python scripts/simulate_payment_timeout.py

预期输出：
    ✅ 每个步骤打印日志，验证 deal 和 task 的状态回滚。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# 将项目根目录和 plugins 目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "plugins"))

# 设置日志格式（与生产环境一致的日志前缀）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("simulate_payment_timeout")


def main():
    from umcp_core.core.domain import DomainTag
    from umcp_core.core.resource import Resource, ResourceStatus
    from umcp_core.layers.l1 import PhoneAuthProvider
    from umcp_core.server import UMCPServer
    from umcp_core.transport.app import create_app
    from umcp_core.transport.auth import JwtService, _ClaimsUser, _ClaimsDemander, _ClaimsSupplier
    from umcp_core.transport.config import TransportConfig
    from plugins.escort_driving import register_plugin
    from fastapi.testclient import TestClient

    logger.info("=" * 60)
    logger.info("支付超时模拟流程 - 开始")
    logger.info("=" * 60)

    # ---- 1. 初始化服务 ----
    class _Coach(Resource):
        def __init__(self):
            super().__init__(
                supplier_id="coach_1",
                domain_tag=DomainTag.of("escort"),
                resource_id="coach_1",
            )
            self.status = ResourceStatus.IDLE
            self.metadata["car_type"] = "manual"
            self.metadata["coach_level"] = "B"

        def resource_type(self) -> str:
            return "coach"

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_auth_provider(PhoneAuthProvider())
    register_plugin(server)
    server.resource_repo.save(_Coach())
    config = TransportConfig(jwt_secret="test-secret")
    client = TestClient(create_app(server, config))

    def auth_headers(user_id="u1", roles=None):
        jwt = JwtService("test-secret")
        user = _ClaimsUser(user_id=user_id, name="Test")
        user.add_role(_ClaimsDemander())
        if roles and "supplier" in roles:
            user.add_role(_ClaimsSupplier())
        if roles:
            user.switch_role(roles[0])
        tokens = jwt.issue(user)
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    # ---- 2. 创建预约单 ----
    logger.info("\n[步骤 1] 创建预约单...")
    resp = client.post(
        "/api/v1/escort/orders",
        json={
            "demander_id": "u1",
            "domain_tag": "escort",
            "origin_lat": 39.9, "origin_lng": 116.4,
            "car_type": "manual", "required_skills": [],
            "duration_hours": 2, "order_type": "SCHEDULED",
            "scheduled_at": "2026-08-10T10:00:00",
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 200, f"创建订单失败: {resp.text}"
    data = resp.json()["data"]
    task_id = data["task_id"]
    candidates = data["candidates"]
    logger.info(f"  ✅ 订单创建成功: task_id={task_id}, 候选教练={candidates}")

    # ---- 3. 选择教练 ----
    logger.info("\n[步骤 2] 选择教练...")
    resp2 = client.post(
        f"/api/v1/escort/orders/{task_id}/select-coach",
        json={"resource_id": candidates[0]},
        headers=auth_headers(),
    )
    assert resp2.status_code == 200, f"选择教练失败: {resp2.text}"
    data2 = resp2.json()["data"]
    deal_id = data2["deal_id"]
    deposit_amount = data2["deposit_amount"]
    logger.info(f"  ✅ 教练选择成功: deal_id={deal_id}, 定金={deposit_amount}")

    # ---- 4. Mock 支付 ----
    logger.info("\n[步骤 3] Mock 支付...")
    resp3 = client.post(
        "/api/v1/escort/payments/mock-pay",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=auth_headers(),
    )
    assert resp3.status_code == 200, f"支付失败: {resp3.text}"
    pay_data = resp3.json()["data"]
    logger.info(f"  ✅ 支付成功: payment_id={pay_data['payment_id']}, status={pay_data['status']}, amount={pay_data['amount']}")

    # ---- 5. 验证支付后状态 ----
    logger.info("\n[步骤 4] 验证支付后状态...")
    deal = server.deal_repo.find_by_id(deal_id)
    logger.info(f"  Deal 状态: {deal.status} (预期: pending)")
    assert deal.status == "pending", f"Deal 状态异常: {deal.status}"

    task = server.task_repo.find_by_id(task_id)
    logger.info(f"  Task 状态: {task.status} (预期: pending)")

    # ---- 6. 模拟支付超时 ----
    logger.info("\n[步骤 5] 模拟支付超时...")
    resp4 = client.post(
        f"/api/v1/escort/payments/{deal_id}/timeout",
        json={},
        headers=auth_headers("coach_1", roles=["supplier"]),
    )
    assert resp4.status_code == 200, f"超时取消失败: {resp4.text}"
    timeout_data = resp4.json()["data"]
    logger.info(f"  ✅ 超时处理完成: deal_status={timeout_data['deal_status']}, task_status={timeout_data['task_status']}")

    # ---- 7. 验证状态回滚 ----
    logger.info("\n[步骤 6] 验证状态回滚...")
    deal_after = server.deal_repo.find_by_id(deal_id)
    logger.info(f"  Deal 状态: {deal_after.status} (预期: cancelled)")
    assert deal_after.status == "cancelled", f"Deal 未正确回滚: {deal_after.status}"

    task_after = server.task_repo.find_by_id(task_id)
    logger.info(f"  Task 状态: {task_after.status} (预期: cancelled)")
    assert task_after.status == "cancelled", f"Task 未正确回滚: {task_after.status}"

    # 验证支付已退款
    payment_service = getattr(server, "payment_service", None)
    if payment_service is not None:
        records = payment_service.repo.find_by_deal(deal_id)
        for r in records:
            logger.info(f"  支付记录: payment_id={r['payment_id']}, status={r['status']} (预期: refunded)")
            assert r["status"] == "refunded", f"支付未退款: {r['payment_id']}"

    # ---- 8. 验证已取消的 deal 不可重复超时 ----
    logger.info("\n[步骤 7] 验证重复超时幂等性...")
    resp5 = client.post(
        f"/api/v1/escort/payments/{deal_id}/timeout",
        json={},
        headers=auth_headers("coach_1", roles=["supplier"]),
    )
    logger.info(f"  重复超时响应: status_code={resp5.status_code} (预期: 400/409)")
    assert resp5.status_code in (400, 409), f"重复超时应返回 400/409，实际: {resp5.status_code}"

    logger.info("\n" + "=" * 60)
    logger.info("支付超时模拟流程 - 全部通过 ✅")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())