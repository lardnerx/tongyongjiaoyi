"""网约车行业插件包。

通过 UMCPServer.load_plugin("ride_hailing") 加载。
plugin.json 中的声明性配置由 server._apply_manifest 处理（task_types、match_strategy、access_rule）。
需要构造参数的组件由 register_plugin 钩子手动创建并注入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from umcp_core.server import UMCPServer


# 与 plugin.json 内容一致，供模块路径方式加载使用
PLUGIN_MANIFEST = {
    "name": "ride-hailing",
    "version": "1.0.0",
    "domain": "ride",
    "task_types": ["ride_hailing.tasks.RideTask"],
    "resource_types": ["ride_hailing.resources.DriverResource"],
    "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
    "trust_dimensions": ["punctuality", "cleanliness", "driving_smoothness", "communication"],
    "commission_rate": 0.20,
    "access_rule_expression": "hasCredential('driver_license') && trustScore >= 4.0",
}


def register_plugin(server: "UMCPServer") -> None:
    """插件自定义初始化钩子。

    按 domain 注册策略组件，同时更新单值属性作为兜底。
    """
    domain = PLUGIN_MANIFEST["domain"]
    from umcp_core.layers.l3 import CredentialFilter, InstantMatch
    from umcp_core.layers.l4 import DynamicPricing, FlatCommissionRule
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from ride_hailing.scoring import RideMatchScorer

    server.register_match_strategy(
        domain,
        InstantMatch(
            scorer=RideMatchScorer(),
            filters=[CredentialFilter(required_credentials=["driver_license"])],
        ),
    )
    server.register_payment_schema(
        domain,
        DynamicPricing(
            surge_factor=1.0,
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        ),
    )
    server.register_trust_engine(
        domain,
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"]),
    )
