"""陪驾插件注册 ScheduledMatchStrategy 测试。"""
from __future__ import annotations


def test_server_supports_scheduled_match_strategy_registration():
    from umcp_core.server import UMCPServer
    from plugins.escort_driving.scheduled_match import ScheduledMatchStrategy
    server = UMCPServer()
    server.use_in_memory_repositories()
    strategy = ScheduledMatchStrategy(top_n=3)
    server.register_scheduled_match_strategy("escort", strategy)
    fetched = server.scheduled_match_strategy_for("escort")
    assert fetched is strategy


def test_server_returns_none_for_unregistered_scheduled_strategy():
    from umcp_core.server import UMCPServer
    server = UMCPServer()
    assert server.scheduled_match_strategy_for("unknown_domain") is None


def test_escort_plugin_registers_scheduled_match_strategy():
    """集成测试：陪驾插件初始化后，server 应能查到 ScheduledMatchStrategy。"""
    from umcp_core.server import UMCPServer
    from plugins.escort_driving import register_plugin
    server = UMCPServer()
    server.use_in_memory_repositories()
    register_plugin(server)
    strategy = server.scheduled_match_strategy_for("escort")
    assert strategy is not None
