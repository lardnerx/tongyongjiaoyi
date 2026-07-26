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

    在 _apply_manifest 之后调用，用于创建需要构造参数的组件：
    - InstantMatch（需 scorer，覆盖 _apply_manifest 创建的无参实例）
    - Hourly（复用核心库通用支付策略，需 hourly_rate 和 commission_rule）
    - WeightedSumTrustEngine（需 dimensions）
    """
    from umcp_core.layers.l3 import CredentialFilter, InstantMatch
    from umcp_core.layers.l4 import FlatCommissionRule, Hourly
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from escort_driving.scoring import EscortMatchScorer

    # 覆盖 match_strategy：注入陪驾行业评分器和资质过滤器
    server.set_match_strategy(
        InstantMatch(
            scorer=EscortMatchScorer(),
            filters=[CredentialFilter(required_credentials=["coach_license"])],
        )
    )

    # 注入支付模式：按时长计费，20% 抽成
    server.set_payment_schema(
        Hourly(
            hourly_rate=PLUGIN_MANIFEST["hourly_rate"],
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        )
    )

    # 注入信任引擎：3 维评价
    server.set_trust_engine(
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"])
    )
