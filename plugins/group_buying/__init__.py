"""集采服务行业插件包（占位，完整内容由任务 9 填充）。"""

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
    """插件自定义初始化钩子（占位，任务 9 填充完整实现）。"""
    # 占位：任务 9 会在此注入 ReverseAuction + TenderBidScorer + InstallmentPayment + TrustEngine
