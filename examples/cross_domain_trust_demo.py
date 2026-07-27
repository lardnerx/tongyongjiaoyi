"""跨域身份与信用 Demo。

演示：
1. 同一 UMCPServer 实例加载 ride + group_buying 两个 domain 的 TrustEngine
2. 同一用户在 ride 域打分 5.0、gb 域打分 3.0
3. 打印各域独立 trust_score（证明隔离）
4. 打印聚合 trust_score（证明聚合）
5. 演示 ride task 因 ride 域高分通过、gb task 因 gb 域低分被拒（同一用户两种结果）
"""
from __future__ import annotations

from umcp_core.core.base import User
from umcp_core.core.domain import Credential, DomainTag
from umcp_core.core.task import CustomTask
from umcp_core.layers.l5 import WeightedSumTrustEngine
from umcp_core.layers.l5.trust import Evaluation
from umcp_core.layers.l7 import ExpressionAccessRule
from umcp_core.server import UMCPServer


class _DemoUser(User):
    """User 是 ABC，demo 中需要具体子类。"""

    def authenticate(self, credential: Credential) -> bool:  # type: ignore[override]
        return True


def main() -> None:
    # 1. 创建 server，注册两个 domain 的 TrustEngine
    server = UMCPServer()
    ride_te = WeightedSumTrustEngine(dimensions=["overall"])
    gb_te = WeightedSumTrustEngine(dimensions=["overall"])
    server.register_trust_engine("ride", ride_te)
    server.register_trust_engine("group_buying", gb_te)

    # 按 domain 注册 access_rule：trustScore >= 4.0
    server.rule_engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 4.0"),
        domain="ride",
    )
    server.rule_engine.add_access_rule(
        ExpressionAccessRule("trustScore >= 4.0"),
        domain="group_buying",
    )

    # 2. 同一用户 alice 在两个 domain 分别打分
    alice = _DemoUser(user_id="alice", name="Alice")
    alice.metadata["trust_score"] = 1.0  # 故意设低，证明不被读到

    # ride 域：5.0（高分）
    ride_te.record_evaluation(
        Evaluation(
            evaluator_id="system",
            evaluatee_id="alice",
            task_id="ride-001",
            ratings={"overall": 5.0},
        )
    )
    # gb 域：3.0（低分）
    gb_te.record_evaluation(
        Evaluation(
            evaluator_id="system",
            evaluatee_id="alice",
            task_id="gb-001",
            ratings={"overall": 3.0},
        )
    )

    # 3. 打印各域独立 trust_score（证明隔离）
    ride_score = ride_te.evaluate("alice").overall_score
    gb_score = gb_te.evaluate("alice").overall_score
    print(f"[隔离] alice 在 ride 域 trust_score = {ride_score}")
    print(f"[隔离] alice 在 group_buying 域 trust_score = {gb_score}")
    print(f"[隔离] metadata['trust_score'] = {alice.metadata['trust_score']}（不被 access_rule 读取）")

    # 4. 打印聚合 trust_score（证明聚合）
    aggregated = server.aggregate_trust_score("alice")
    print(f"[聚合] alice 跨 domain 聚合 trust_score = {aggregated}（算术平均）")

    # 5. 演示同一用户在两个 domain 的 access_rule 结果不同
    ride_task = CustomTask(demander_id="alice", domain_tag=DomainTag.of("ride"))
    gb_task = CustomTask(demander_id="alice", domain_tag=DomainTag.of("group_buying"))

    ride_pass = server.rule_engine.check_access(alice, ride_task)
    gb_pass = server.rule_engine.check_access(alice, gb_task)

    print(f"[准入] alice 接 ride task: {'通过' if ride_pass else '拒绝'}（ride 域 5.0 >= 4.0）")
    print(f"[准入] alice 接 gb task: {'通过' if gb_pass else '拒绝'}（gb 域 3.0 < 4.0）")

    # 6. 演示自定义聚合策略
    from umcp_core.layers.l5 import TrustAggregator

    class MinTrustAggregator(TrustAggregator):
        """取最低分（防刷分策略）。"""
        def aggregate(self, user_id, engines):
            if not engines:
                return 0.0
            return min(e.evaluate(user_id).overall_score for e in engines.values())

    server.set_trust_aggregator(MinTrustAggregator())
    min_aggregated = server.aggregate_trust_score("alice")
    print(f"[自定义聚合] 切换为取最低分策略：alice 聚合 trust_score = {min_aggregated}（min(5.0, 3.0)）")


if __name__ == "__main__":
    main()
