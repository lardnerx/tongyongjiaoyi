"""集采服务行业插件包。

通过 UMCPServer.load_plugin("group_buying") 加载。
plugin.json 中的声明性配置由 server._apply_manifest 处理（task_types、match_strategy、access_rule）。
需要构造参数的组件由 register_plugin 钩子手动创建并注入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from umcp_core.server import UMCPServer


# 与 plugin.json 内容一致，供模块路径方式加载使用
PLUGIN_MANIFEST = {
    "name": "group-buying",
    "version": "1.0.0",
    "task_types": [
        "group_buying.tasks.BuyerTask",
        "group_buying.tasks.TenderTask",
    ],
    "resource_types": ["group_buying.resources.SupplierResource"],
    "match_strategy": "umcp_core.layers.l3.matching.ReverseAuction",
    "trust_dimensions": ["delivery", "quality", "service", "cost_performance"],
    "commission_rate": 0.05,
    "deposit_ratio": 0.3,
    "access_rule_expression": "hasCredential('business_license') && trustScore >= 3.0",
}


def register_plugin(server: "UMCPServer") -> None:
    """插件自定义初始化钩子。

    在 _apply_manifest 之后调用，用于创建需要构造参数的组件：
    - ReverseAuction（需 scorer，覆盖 _apply_manifest 创建的无参实例）
    - InstallmentPayment（需 deposit_ratio 和 commission_rule）
    - WeightedSumTrustEngine（需 dimensions）
    """
    from umcp_core.layers.l3 import CredentialFilter, ReverseAuction
    from umcp_core.layers.l4 import FlatCommissionRule, InstallmentPayment
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from group_buying.scoring import TenderBidScorer

    # 覆盖 match_strategy：注入集采行业评分器和资质过滤器
    server.set_match_strategy(
        ReverseAuction(
            scorer=TenderBidScorer(),
            filters=[CredentialFilter(required_credentials=["business_license"])],
        )
    )

    # 注入支付模式：分期付款（30% 订金），5% 抽成
    server.set_payment_schema(
        InstallmentPayment(
            deposit_ratio=PLUGIN_MANIFEST["deposit_ratio"],
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        )
    )

    # 注入信任引擎：4 维评价
    server.set_trust_engine(
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"])
    )
