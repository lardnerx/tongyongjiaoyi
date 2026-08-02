"""陪驾服务行业插件包。

通过 UMCPServer.load_plugin("escort_driving") 加载。
plugin.json 中的声明性配置由 server._apply_manifest 处理（task_types、match_strategy、access_rule）。
需要构造参数的组件由 register_plugin 钩子手动创建并注入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from umcp_core.server import UMCPServer


# 与 plugin.json 内容一致，供模块路径方式加载使用
PLUGIN_MANIFEST = {
    "name": "escort-driving",
    "version": "1.0.0",
    "domain": "escort",
    "task_types": ["escort_driving.tasks.EscortTask"],
    "resource_types": ["escort_driving.resources.CoachResource"],
    "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
    "trust_dimensions": ["teaching_ability", "patience", "safety_record"],
    "commission_rate": 0.20,
    "hourly_rate": 80.0,
    "access_rule_expression": "hasCredential('coach_license') && trustScore >= 4.0",
}


def register_plugin(server: "UMCPServer") -> None:
    """插件自定义初始化钩子。

    按 domain 注册策略组件，同时更新单值属性作为兜底。
    """
    domain = PLUGIN_MANIFEST["domain"]
    from umcp_core.layers.l3 import CredentialFilter, InstantMatch
    from umcp_core.layers.l4 import FlatCommissionRule, Hourly
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from escort_driving.scoring import EscortMatchScorer
    from escort_driving.scheduled_match import ScheduledMatchStrategy

    server.register_match_strategy(
        domain,
        InstantMatch(
            scorer=EscortMatchScorer(),
            filters=[CredentialFilter(required_credentials=["coach_license"])],
        ),
    )
    server.register_payment_schema(
        domain,
        Hourly(
            hourly_rate=PLUGIN_MANIFEST["hourly_rate"],
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        ),
    )
    server.register_trust_engine(
        domain,
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"]),
    )
    # 预约单 Top N 推荐策略（与实时单 InstantMatch 区分，供 router 调用）
    server.register_scheduled_match_strategy(
        domain,
        ScheduledMatchStrategy(top_n=3),
    )
    # 注册支付服务（MockGateway + 内存仓储，挂载到 server.payment_service）
    from umcp_core.shared.payment.mock import MockGateway
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    from umcp_core.shared.payment.service import PaymentService

    server.payment_service = PaymentService(
        gateway=MockGateway(),
        repo=InMemoryPaymentRepository(),
        event_bus=server.event_bus,
    )
