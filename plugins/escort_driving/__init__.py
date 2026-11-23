"""陪驾服务行业插件包。

通过 UMCPServer.load_plugin("escort_driving") 加载。
plugin.json 中的声明性配置由 server._apply_manifest 处理（task_types、match_strategy、access_rule）。
需要构造参数的组件由 register_plugin 钩子手动创建并注入。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# 业务通知渠道：站内消息（由 NotificationCenter 落库）+ WebSocket 实时推送。
# 短信仅保留渠道实现供后续验证码等场景使用，业务通知不再走短信。
_NOTIFY_CHANNELS = ["IN_APP", "WS_PUSH"]

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
    # 注册支付服务（根据配置选择 WeChatPayGateway 或 MockGateway）
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    from umcp_core.shared.payment.service import PaymentService

    gateway_config = getattr(server, "payment_gateway_config", {})
    if gateway_config and gateway_config.get("app_id"):
        # 生产环境：微信支付 V3
        from umcp_core.shared.payment.wechat import WechatPayGateway

        gateway = WechatPayGateway(
            app_id=gateway_config["app_id"],
            mch_id=gateway_config["mch_id"],
            api_v3_key=gateway_config["api_v3_key"],
            mch_serial_no=gateway_config["mch_serial_no"],
            private_key_path=gateway_config["private_key_path"],
            notify_url=gateway_config.get("notify_url", ""),
        )
        logger.info("支付网关: 微信支付 V3 (Native)")
    else:
        # 开发/测试环境：Mock 网关
        from umcp_core.shared.payment.mock import MockGateway

        gateway = MockGateway()
        logger.info("支付网关: Mock（开发模式）")

    server.payment_service = PaymentService(
        gateway=gateway,
        # 生产环境使用 server 注入的持久化仓储；未注入时回退内存实现
        repo=getattr(server, "payment_repo", None) or InMemoryPaymentRepository(),
        event_bus=server.event_bus,
    )
    logger.info("支付仓储: %s", type(server.payment_service.repo).__name__)
    # 注册规则配置中心（持久化仓储 + 默认值预加载，挂载到 server.rule_config）
    from umcp_core.shared.rules.config import RuleConfig
    from umcp_core.shared.rules.repository import InMemoryRuleRepository

    # 生产环境使用 server 注入的持久化仓储；未注入时回退内存实现
    rule_config = RuleConfig(repo=getattr(server, "rule_repo", None) or InMemoryRuleRepository())
    logger.info("规则仓储: %s", type(rule_config._repo).__name__)
    rule_config.set_defaults(
        {
            "escort.cancel.realtime.timeout_seconds": 120,
            "escort.cancel.realtime.expand_after_seconds": 30,
            "escort.match.realtime.radius_km": 5.0,   # 实时单首轮推送半径（<=0 不限）
            "escort.cancel.scheduled.penalty_tiers": [
                {"hours_before": 24, "penalty": 0.2},
                {"hours_before": 12, "penalty": 0.5},
                {"hours_before": 4, "penalty": 1.0},
                {"hours_before": 0, "penalty": 2.0},
            ],
            "payment.timeout_seconds": 1800,      # 30 分钟未支付自动关闭
            "payment.cleanup_interval": 60,        # 清理 Worker 扫描间隔（秒）
        }
    )
    server.rule_config = rule_config

    # ================================================================
    # 通知中心初始化
    # ================================================================
    _setup_notification_center(server)


def _setup_notification_center(server: "UMCPServer") -> None:
    """初始化通知中心，注册渠道、模板和事件监听器。

    在 register_plugin 末尾调用，确保 server 上所有组件已就绪。
    """
    from umcp_core.events.bus import Event
    from umcp_core.events.types import EventType
    from umcp_core.shared.notification.center import NotificationCenter
    from umcp_core.shared.notification.ws_channel import WSNotificationChannel

    # 1. 创建通知中心（站内消息落库用 server 注入的仓储）
    notify_repo = getattr(server, "notification_repo", None)
    center = NotificationCenter(store=notify_repo)
    server.notification_center = center
    logger.info("[NOTIFY] 站内消息仓储: %s", type(notify_repo).__name__ if notify_repo else "未注册")

    # 2. 注册 WS 推送渠道
    from umcp_core.transport.ws import ConnectionManager

    ws_manager = getattr(server, "ws_manager", None)
    if ws_manager:
        center.register_channel("WS_PUSH", WSNotificationChannel(ws_manager))
        logger.info("[NOTIFY] WS 通知渠道已注册")

    # 3. 注册短信渠道
    _setup_sms_channel(server, center)

    # 4. 注册通知模板
    _register_templates(center)

    # 5. 注册事件监听器
    _register_event_listeners(server, center)

    logger.info("[NOTIFY] 通知中心初始化完成")


def _setup_sms_channel(server: "UMCPServer", center: "NotificationCenter") -> None:
    """注册短信渠道（根据环境变量决定生产/开发模式）。"""
    from umcp_core.shared.notification.sms_channel import SmsChannel

    # 从 server 配置读取短信参数
    gateway_config = getattr(server, "payment_gateway_config", {})
    # 互亿无线（优先）
    api_id = gateway_config.get("sms_api_id", "")
    api_key = gateway_config.get("sms_api_key", "")
    sign = gateway_config.get("sms_sign", "")
    # 阿里云（备选）
    aliyun_key_id = gateway_config.get("sms_access_key_id", "")
    aliyun_key_secret = gateway_config.get("sms_access_key_secret", "")
    aliyun_sign_name = gateway_config.get("sms_sign_name", "")
    aliyun_template_code = gateway_config.get("sms_template_code", "")

    # 判断使用哪个提供商
    if api_id:
        provider = "ihuyi"
        sms_channel = SmsChannel(
            provider=provider,
            api_id=api_id,
            api_key=api_key,
            sign=sign,
            phone_resolver=_make_phone_resolver(server),
        )
    elif aliyun_key_id:
        provider = "aliyun"
        sms_channel = SmsChannel(
            provider=provider,
            access_key_id=aliyun_key_id,
            access_key_secret=aliyun_key_secret,
            sign_name=aliyun_sign_name,
            template_code=aliyun_template_code,
            phone_resolver=_make_phone_resolver(server),
        )
    else:
        provider = "ihuyi"
        sms_channel = SmsChannel(
            provider=provider,
            phone_resolver=_make_phone_resolver(server),
        )

    center.register_channel("SMS", sms_channel)
    mode = "production" if sms_channel._production else "console(dev)"
    logger.info(
        "[NOTIFY] SMS 渠道已注册（业务通知已改为站内消息，仅保留供验证码等场景）: provider=%s mode=%s",
        provider,
        mode,
    )


def _make_phone_resolver(server: "UMCPServer"):
    """创建手机号解析器。

    通过 server.credential_repo 或 user_repo 查找用户手机号。
    兜底返回空字符串。
    """

    def resolve(user_id: str) -> str:
        """根据 user_id 查找手机号。"""
        # 尝试从 credential 仓库查找
        try:
            cred_repo = getattr(server, "credential_repo", None)
            if cred_repo:
                creds = cred_repo.find_by_user(user_id)
                for cred in creds:
                    if cred.type == "phone":
                        return cred.value
        except Exception:
            pass
        # 尝试从 user_repo 查找（手机号存储在 metadata["phone"] 中）
        try:
            user_repo = getattr(server, "user_repo", None)
            if user_repo:
                user = user_repo.find_by_id(user_id)
                if user and user.metadata:
                    phone = user.metadata.get("phone", "")
                    if phone:
                        return phone
        except Exception:
            pass
        # 尝试从 auth_provider 缓存查找（内存模式）
        try:
            auth_provider = getattr(server, "auth_provider", None)
            if auth_provider and hasattr(auth_provider, "_users"):
                for phone, user in auth_provider._users.items():
                    if user.user_id == user_id:
                        return phone
        except Exception:
            pass
        return ""

    return resolve


def _register_templates(center: "NotificationCenter") -> None:
    """注册陪驾业务通知模板。"""
    templates = {
        # 订单创建 → 通知教练
        "DEAL_CREATED": {
            "title": "新订单通知",
            "body": "学员 {{ demander_name }} 已下单，请及时确认。订单编号：{{ deal_id }}",
        },
        # 教练确认 → 通知学员
        "DEAL_CONFIRMED": {
            "title": "订单已确认",
            "body": "教练 {{ coach_name }} 已确认您的订单（{{ deal_id }}），请按时参加陪驾。",
        },
        # 教练拒绝 → 通知学员
        "DEAL_REJECTED": {
            "title": "订单被拒绝",
            "body": "教练 {{ coach_name }} 拒绝了您的订单（{{ deal_id }}），原因：{{ reason }}。",
        },
        # 支付成功 → 通知学员
        "PAYMENT_PAID": {
            "title": "支付成功",
            "body": "您的订单 {{ deal_id }} 已支付成功，金额 {{ amount }} 元。",
        },
        # 服务完成 → 通知双方
        "DEAL_COMPLETED": {
            "title": "服务已完成",
            "body": "陪驾服务 {{ deal_id }} 已完成，请为对方评价。",
        },
        # 订单取消 → 通知双方
        "DEAL_CANCELLED": {
            "title": "订单已取消",
            "body": "订单 {{ deal_id }} 已取消。",
        },
        # 退款 → 通知学员
        "PAYMENT_REFUNDED": {
            "title": "退款通知",
            "body": "您的订单 {{ deal_id }} 已退款 {{ refund_amount }} 元。",
        },
    }
    for event_type, tpl in templates.items():
        center.register_template(event_type, tpl["title"], tpl["body"])
    logger.info("[NOTIFY] 已注册 %d 个通知模板", len(templates))


def _register_event_listeners(server: "UMCPServer", center: "NotificationCenter") -> None:
    """注册事件监听器，将业务事件转换为通知分发。"""
    from umcp_core.events.bus import Event
    from umcp_core.events.types import EventType

    event_bus = server.event_bus

    # ── DEAL_CREATED → 通知教练（站内 + WS） ──
    def on_deal_created(event: Event) -> None:
        payload = event.payload or {}
        supplier_id = payload.get("supplier_id", "")
        if not supplier_id:
            return
        center.notify(
            user_id=supplier_id,
            event_type="DEAL_CREATED",
            channels=_NOTIFY_CHANNELS,
            params={
                "deal_id": payload.get("deal_id", ""),
                "demander_name": payload.get("demander_id", "学员"),
            },
        )

    event_bus.subscribe(EventType.DEAL_CREATED, on_deal_created)

    # ── DEAL_PAID (deal.activate) → 通知学员（站内 + WS） ──
    def on_deal_paid(event: Event) -> None:
        payload = event.payload or {}
        demander_id = payload.get("demander_id", "")
        if not demander_id:
            return
        center.notify(
            user_id=demander_id,
            event_type="DEAL_CONFIRMED",
            channels=_NOTIFY_CHANNELS,
            params={
                "deal_id": payload.get("deal_id", ""),
                "coach_name": payload.get("supplier_id", "教练"),
            },
        )

    event_bus.subscribe(EventType.DEAL_PAID, on_deal_paid)

    # ── DEAL_CANCELLED → 通知双方（站内 + WS） ──
    def on_deal_cancelled(event: Event) -> None:
        payload = event.payload or {}
        demander_id = payload.get("demander_id", "")
        supplier_id = payload.get("supplier_id", "")
        for user_id in (demander_id, supplier_id):
            if user_id:
                center.notify(
                    user_id=user_id,
                    event_type="DEAL_CANCELLED",
                    channels=_NOTIFY_CHANNELS,
                    params={"deal_id": payload.get("deal_id", "")},
                )

    event_bus.subscribe(EventType.DEAL_CANCELLED, on_deal_cancelled)

    # ── PAYMENT_PAID → 通知学员（站内 + WS） ──
    def on_payment_paid(event: Event) -> None:
        payload = event.payload or {}
        user_id = payload.get("user_id", "")
        if not user_id:
            user_id = payload.get("demander_id", "")
        if not user_id:
            return
        center.notify(
            user_id=user_id,
            event_type="PAYMENT_PAID",
            channels=_NOTIFY_CHANNELS,
            params={
                "deal_id": payload.get("deal_id", ""),
                "amount": payload.get("amount", 0),
            },
        )

    event_bus.subscribe(EventType.PAYMENT_PAID, on_payment_paid)

    # ── PAYMENT_REFUNDED → 通知学员（站内 + WS） ──
    def on_payment_refunded(event: Event) -> None:
        payload = event.payload or {}
        user_id = payload.get("user_id", "")
        if not user_id:
            # 从 payment repo 反查
            payment_id = payload.get("payment_id", "")
            if payment_id:
                try:
                    rec = server.payment_service.repo.find_by_id(payment_id)
                    if rec:
                        user_id = rec.get("user_id", "")
                except Exception:
                    pass
        if not user_id:
            return
        center.notify(
            user_id=user_id,
            event_type="PAYMENT_REFUNDED",
            channels=_NOTIFY_CHANNELS,
            params={
                "deal_id": payload.get("deal_id", ""),
                "refund_amount": payload.get("refund_amount", 0),
            },
        )

    event_bus.subscribe(EventType.PAYMENT_REFUNDED, on_payment_refunded)

    # ── DEAL_COMPLETED → 通知双方（站内 + WS） ──
    def on_deal_completed(event: Event) -> None:
        payload = event.payload or {}
        demander_id = payload.get("demander_id", "")
        supplier_id = payload.get("supplier_id", "")
        for user_id in (demander_id, supplier_id):
            if user_id:
                center.notify(
                    user_id=user_id,
                    event_type="DEAL_COMPLETED",
                    channels=_NOTIFY_CHANNELS,
                    params={"deal_id": payload.get("deal_id", "")},
                )

    event_bus.subscribe(EventType.DEAL_COMPLETED, on_deal_completed)

    logger.info("[NOTIFY] 已注册 %d 个事件监听器", 6)
