"""陪驾插件注册 ScheduledMatchStrategy 测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def server_with_escort():
    """带陪驾插件注册的 UMCPServer（内存仓储）。"""
    from umcp_core.server import UMCPServer
    from plugins.escort_driving import register_plugin
    server = UMCPServer()
    server.use_in_memory_repositories()
    register_plugin(server)
    return server


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


def test_payment_service_registered(server_with_escort):
    """register_plugin 应将 PaymentService 挂载到 server.payment_service。"""
    from umcp_core.shared.payment.service import PaymentService
    assert hasattr(server_with_escort, "payment_service")
    assert isinstance(server_with_escort.payment_service, PaymentService)


def test_payment_service_uses_injected_repository():
    """register_plugin 应优先使用 server 注入的支付仓储（生产为 PG 实现）。"""
    from umcp_core.server import UMCPServer
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    from plugins.escort_driving import register_plugin

    server = UMCPServer()
    server.use_in_memory_repositories()
    injected = InMemoryPaymentRepository()
    server.payment_repo = injected
    register_plugin(server)

    assert server.payment_service.repo is injected


def test_payment_service_uses_event_bus(server_with_escort):
    """PaymentService 应共享 server.event_bus，事件能被订阅者收到。"""
    received = []
    server_with_escort.event_bus.subscribe_all(lambda e: received.append(e))

    from umcp_core.shared.payment.base import PaymentType
    server_with_escort.payment_service.create_payment(
        deal_id="deal_test", user_id="u1", amount=48.0, payment_type=PaymentType.DEPOSIT
    )
    server_with_escort.payment_service.confirm_payment(
        payment_id=server_with_escort.payment_service.repo.find_by_deal("deal_test")[0]["payment_id"]
    )

    types = [e.type.value for e in received]
    assert "payment.paid" in types


def test_payment_service_uses_wechat_gateway_when_configured(monkeypatch):
    """配置了完整微信参数时，register_plugin 应选择 WechatPayGateway。"""
    from umcp_core.server import UMCPServer
    from plugins.escort_driving import register_plugin
    import umcp_core.shared.payment.wechat as wechat_module

    captured: dict[str, object] = {}

    class FakeWechatPayGateway:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(wechat_module, "WechatPayGateway", FakeWechatPayGateway)

    server = UMCPServer()
    server.use_in_memory_repositories()
    server.payment_gateway_config = {
        "app_id": "wx_test_app",
        "mch_id": "1900000000",
        "api_v3_key": "k" * 32,
        "mch_serial_no": "SERIAL",
        "private_key_path": "/tmp/apiclient_key.pem",
        "notify_url": "https://example.com/api/v1/escort/payments/callback",
    }
    register_plugin(server)

    assert captured["app_id"] == "wx_test_app"
    assert isinstance(server.payment_service._gateway, FakeWechatPayGateway)
