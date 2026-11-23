"""验证陪驾插件注册 RuleConfig 并预加载默认取消规则。"""
from __future__ import annotations

import pytest

from umcp_core.server import UMCPServer
from umcp_core.shared.rules.config import RuleConfig


@pytest.fixture
def server_with_escort() -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    return server


def test_rule_config_registered(server_with_escort: UMCPServer):
    """server.rule_config 应为 RuleConfig 实例。"""
    assert hasattr(server_with_escort, "rule_config")
    assert isinstance(server_with_escort.rule_config, RuleConfig)


def test_default_realtime_timeout_seconds(server_with_escort: UMCPServer):
    """默认实时单超时 120 秒。"""
    value = server_with_escort.rule_config.get("escort.cancel.realtime.timeout_seconds")
    assert value == 120


def test_default_realtime_radius_km(server_with_escort: UMCPServer):
    """默认实时单首轮推送半径 5 公里。"""
    value = server_with_escort.rule_config.get("escort.match.realtime.radius_km")
    assert value == 5.0


def test_default_realtime_expand_after_seconds(server_with_escort: UMCPServer):
    """默认实时单扩展搜索 30 秒。"""
    value = server_with_escort.rule_config.get("escort.cancel.realtime.expand_after_seconds")
    assert value == 30


def test_default_scheduled_penalty_tiers(server_with_escort: UMCPServer):
    """默认预约单罚分梯度。"""
    tiers = server_with_escort.rule_config.get("escort.cancel.scheduled.penalty_tiers")
    assert tiers == [
        {"hours_before": 24, "penalty": 0.2},
        {"hours_before": 12, "penalty": 0.5},
        {"hours_before": 4, "penalty": 1.0},
        {"hours_before": 0, "penalty": 2.0},
    ]


def test_rule_config_set_overrides_default(server_with_escort: UMCPServer):
    """set 后应覆盖默认值并刷新缓存。"""
    server_with_escort.rule_config.set(
        key="escort.cancel.realtime.timeout_seconds",
        value=120,
        updated_by="admin",
        category="escort.cancel",
        reason="运营调整",
    )
    assert server_with_escort.rule_config.get("escort.cancel.realtime.timeout_seconds") == 120
