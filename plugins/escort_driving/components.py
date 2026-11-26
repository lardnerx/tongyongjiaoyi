"""陪驾插件组件工厂。

plugin.json 通过 {"factory": "escort_driving.components.build_xxx"} 声明组件，
由 UMCPServer._apply_manifest 在加载时调用。工厂签名统一为
``factory(server, **params)``，用于需要运行时注入（如读取 rule_config）的组件。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from umcp_core.server import UMCPServer


def build_match_strategy(server: "UMCPServer") -> Any:
    """实时单匹配策略：车型/技能评分 + 教练资质预过滤。"""
    from umcp_core.layers.l3 import CredentialFilter, InstantMatch

    from .scoring import EscortMatchScorer

    return InstantMatch(
        scorer=EscortMatchScorer(),
        filters=[CredentialFilter(required_credentials=["coach_license"])],
    )


def build_payment_schema(server: "UMCPServer") -> Any:
    """陪驾计价模式：单价与佣金从 RuleConfig 读取，运营可在线调价。"""
    from .pricing import EscortPaymentSchema

    return EscortPaymentSchema(
        config_provider=lambda: getattr(server, "rule_config", None),
    )
