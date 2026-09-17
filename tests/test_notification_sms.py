"""测试 SMS 通知通道和模板模块。"""
from __future__ import annotations

from umcp_core.shared.notification import Notification, SmsChannel
from umcp_core.shared.notification.template import NotificationTemplate, TemplateRegistry


class TestSmsChannel:
    """测试短信通道开发模式（控制台输出）。"""

    def test_sms_channel_name(self):
        channel = SmsChannel()
        assert channel.name == "SMS"

    def test_sms_dev_mode_logs(self, caplog):
        """开发模式应输出日志，不报错。"""
        import logging
        caplog.set_level(logging.INFO)

        def resolver(uid: str) -> str:
            return "13800138000"

        channel = SmsChannel(phone_resolver=resolver)
        notification = Notification(
            user_id="u1",
            event_type="TEST",
            title="测试通知",
            body="这是一条测试短信",
            channels=["SMS"],
            params={"key": "value"},
        )
        # 开发模式不应抛出异常
        channel.send("u1", notification)

        # 应输出日志
        assert "[SMS][DEV]" in caplog.text
        assert "测试通知" in caplog.text

    def test_sms_with_phone_resolver(self, caplog):
        """配置 phone_resolver 后能正确解析手机号。"""
        import logging
        caplog.set_level(logging.INFO)

        def resolver(user_id: str) -> str:
            phones = {"u1": "13800138000", "u2": ""}
            return phones.get(user_id, "")

        channel = SmsChannel(phone_resolver=resolver)
        notification = Notification(
            user_id="u1",
            event_type="TEST",
            title="测试",
            body="body",
            channels=["SMS"],
        )
        channel.send("u1", notification)
        assert "13800138000" in caplog.text

        # 无法解析手机号应静默跳过
        caplog.clear()
        channel.send("u_unknown", notification)
        assert "cannot resolve phone" in caplog.text

    def test_sms_rate_limit(self, caplog):
        """同一手机号 60 秒内不应重复发送。"""
        import logging
        caplog.set_level(logging.WARNING)

        def resolver(user_id: str) -> str:
            return "13800138000"

        channel = SmsChannel(phone_resolver=resolver)
        notification = Notification(
            user_id="u1",
            event_type="TEST",
            title="test",
            body="test",
            channels=["SMS"],
        )

        channel.send("u1", notification)
        channel.send("u1", notification)
        assert "rate limited" in caplog.text

    def test_sms_production_mode_requires_credentials(self):
        """生产模式需要配置凭证。"""
        # 默认 provider=ihuyi，无凭证时应为开发模式
        channel = SmsChannel()
        assert channel._production is False

        # 互亿无线：有 api_id + api_key 时为生产模式
        channel_ihuyi = SmsChannel(
            provider="ihuyi",
            api_id="C12345678",
            api_key="abcdef1234567890",
        )
        assert channel_ihuyi._production is True

        # 互亿无线：缺少 api_key 时为开发模式
        channel_ihuyi_dev = SmsChannel(
            provider="ihuyi",
            api_id="C12345678",
        )
        assert channel_ihuyi_dev._production is False

        # 阿里云：有完整凭证时为生产模式
        channel_aliyun = SmsChannel(
            provider="aliyun",
            access_key_id="LTAI5t_xxx",
            access_key_secret="secret",
            sign_name="陪驾服务",
            template_code="SMS_123456789",
        )
        assert channel_aliyun._production is True

        # 阿里云：缺少模板时为开发模式
        channel_aliyun_dev = SmsChannel(
            provider="aliyun",
            access_key_id="LTAI5t_xxx",
            access_key_secret="secret",
        )
        assert channel_aliyun_dev._production is False

    def test_ihuyi_content_building(self):
        """互亿无线短信内容构建。"""
        def resolver(uid: str) -> str:
            return "13800138000"

        channel = SmsChannel(phone_resolver=resolver)
        notification = Notification(
            user_id="u1",
            event_type="TEST",
            title="新订单通知",
            body="学员张三已下单，订单编号：D001",
            channels=["SMS"],
            params={"deal_id": "D001"},
        )
        content = channel._build_ihuyi_content(notification, notification.params)
        assert "新订单通知" in content
        assert "学员张三已下单" in content
        assert "deal_id=D001" in content


class TestNotificationTemplate:
    """测试 Jinja2 通知模板渲染。"""

    def test_basic_render(self):
        tpl = NotificationTemplate(
            "订单 {{ deal_id }} 已确认",
            "学员 {{ student_name }} 已确认您的预约。",
        )
        title, body = tpl.render(deal_id="deal_001", student_name="张三")
        assert title == "订单 deal_001 已确认"
        assert body == "学员 张三 已确认您的预约。"

    def test_missing_variable_renders_empty(self):
        """未提供的变量应静默渲染为空，不抛出异常。"""
        tpl = NotificationTemplate(
            "{{ title }} 通知",
            "内容：{{ body }}",
        )
        title, body = tpl.render()
        assert title == " 通知"
        assert body == "内容："

    def test_unicode_content(self):
        tpl = NotificationTemplate(
            "陪驾通知",
            "您的订单 {{ deal_id }} 已退款 {{ amount }} 元。",
        )
        title, body = tpl.render(deal_id="D001", amount=100.50)
        assert title == "陪驾通知"
        assert body == "您的订单 D001 已退款 100.5 元。"


class TestTemplateRegistry:
    """测试模板注册表。"""

    def test_register_and_render(self):
        registry = TemplateRegistry()
        registry.register(
            "DEAL_CREATED",
            "新订单通知",
            "学员 {{ name }} 已下单，订单编号：{{ deal_id }}",
        )

        title, body = registry.render("DEAL_CREATED", name="李四", deal_id="deal_002")
        assert title == "新订单通知"
        assert body == "学员 李四 已下单，订单编号：deal_002"

    def test_unregistered_event_falls_back(self):
        """未注册的事件类型应返回原始内容。"""
        registry = TemplateRegistry()
        title, body = registry.render("UNKNOWN_EVENT", key="value")
        assert title == "UNKNOWN_EVENT"
        assert "key" in body

    def test_has_template(self):
        registry = TemplateRegistry()
        registry.register("TEST", "T", "B")
        assert registry.has_template("TEST") is True
        assert registry.has_template("NONEXIST") is False