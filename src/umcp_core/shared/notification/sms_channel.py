"""短信通知渠道。

支持两种短信提供商：
  - ihuyi（互亿无线，默认）：HTTP POST + MD5 签名，完整内容直接发送
  - aliyun（阿里云）：HMAC-SHA1 签名，需预定义模板

生产环境通过短信 API 发送短信。
开发环境（无凭证）时降级到控制台输出。

依赖：
  - httpx：调用短信 API
  - phone_resolver：将 user_id 解析为手机号的函数

环境变量（通过 TransportConfig 传入）：
  互亿无线（默认）：
    - IHUYI_SMS_API_ID
    - IHUYI_SMS_API_KEY
    - IHUYI_SMS_SIGN（可选，短信签名名称）

  阿里云（备选）：
    - ALIYUN_SMS_ACCESS_KEY_ID
    - ALIYUN_SMS_ACCESS_KEY_SECRET
    - ALIYUN_SMS_SIGN_NAME
    - ALIYUN_SMS_TEMPLATE_CODE
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from typing import Any, Callable
from urllib.parse import quote

from umcp_core.shared.notification.base import NotificationChannel, Notification

logger = logging.getLogger(__name__)

# 互亿无线短信 API 地址
_IHUYI_SMS_ENDPOINT = "http://106.ihuyi.com/webservice/sms.php?method=Submit"

# 阿里云短信 API 地址
_ALIYUN_SMS_ENDPOINT = "https://dysmsapi.aliyuncs.com"

# 短信发送频率限制（同一手机号 60 秒内最多 1 条）
_SMS_RATE_LIMIT_WINDOW = 60
_SMS_MAX_PER_WINDOW = 1

# 支持的短信提供商
_PROVIDER_IHUYI = "ihuyi"
_PROVIDER_ALIYUN = "aliyun"


class SmsChannel(NotificationChannel):
    """短信通知渠道。

    支持互亿无线（ihuyi，默认）和阿里云（aliyun）两种短信提供商。
    生产模式需要配置对应提供商的凭证。

    Args:
        provider: 短信提供商，可选 "ihuyi"（默认）或 "aliyun"
        phone_resolver: 将 user_id 解析为手机号的函数，签名 (user_id) -> str
        api_id: 互亿无线 API ID（ihuyi 模式）
        api_key: 互亿无线 API KEY（ihuyi 模式）
        sign: 短信签名名称（ihuyi 模式，可选）
        access_key_id: 阿里云 AccessKey ID（aliyun 模式）
        access_key_secret: 阿里云 AccessKey Secret（aliyun 模式）
        sign_name: 阿里云短信签名（aliyun 模式）
        template_code: 阿里云短信模板 Code（aliyun 模式）
    """

    def __init__(
        self,
        provider: str = _PROVIDER_IHUYI,
        phone_resolver: Callable[[str], str] | None = None,
        # 互亿无线参数
        api_id: str = "",
        api_key: str = "",
        sign: str = "",
        # 阿里云参数（兼容旧版）
        access_key_id: str = "",
        access_key_secret: str = "",
        sign_name: str = "",
        template_code: str = "",
    ) -> None:
        self._provider = provider
        self._phone_resolver = phone_resolver

        # 互亿无线参数
        self._api_id = api_id
        self._api_key = api_key
        self._sign = sign

        # 阿里云参数
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self._sign_name = sign_name
        self._template_code = template_code

        # 判断是否为生产模式
        if provider == _PROVIDER_IHUYI:
            self._production = bool(api_id and api_key)
        else:
            self._production = bool(access_key_id and access_key_secret and sign_name and template_code)

        # 限流：记录每个手机号上次发送时间
        self._last_send: dict[str, float] = {}

        logger.info(
            "[SMS_CHANNEL] init: provider=%s production=%s",
            provider, self._production,
        )

    @property
    def name(self) -> str:
        return "SMS"

    def send(self, user_id: str, notification: Notification) -> None:
        """发送短信通知。

        需要 phone_resolver 将 user_id 解析为手机号。
        如果未配置 phone_resolver 或无法解析到手机号，静默跳过。
        """
        phone = self._resolve_phone(user_id)
        if not phone:
            logger.warning("[SMS] cannot resolve phone for user_id=%s, skip", user_id)
            return

        # 限流检查
        if not self._check_rate_limit(phone):
            logger.warning("[SMS] rate limited: phone=%s user_id=%s, skip", phone, user_id)
            return

        # 构造短信内容参数
        template_params = dict(notification.params)
        if "title" not in template_params:
            template_params["title"] = notification.title
        if "body" not in template_params:
            template_params["body"] = notification.body

        if self._production:
            if self._provider == _PROVIDER_IHUYI:
                self._send_via_ihuyi(phone, notification, template_params)
            else:
                self._send_via_aliyun(phone, template_params)
        else:
            self._send_via_console(phone, user_id, notification, template_params)

    def _resolve_phone(self, user_id: str) -> str:
        """将 user_id 解析为手机号。"""
        if self._phone_resolver is None:
            return ""
        try:
            phone = self._phone_resolver(user_id)
            return phone.strip() if phone else ""
        except Exception as e:
            logger.error("[SMS] phone resolver failed: user_id=%s error=%s", user_id, e)
            return ""

    def _check_rate_limit(self, phone: str) -> bool:
        """检查短信发送频率限制。"""
        now = time.time()
        last = self._last_send.get(phone, 0.0)
        if now - last < _SMS_RATE_LIMIT_WINDOW:
            return False
        self._last_send[phone] = now
        return True

    def _send_via_console(self, phone: str, user_id: str, notification: Notification, params: dict) -> None:
        """开发模式：控制台输出。"""
        logger.info(
            "[SMS][DEV] to=%s user=%s event=%s title=%s body=%s params=%s",
            phone, user_id, notification.event_type,
            notification.title, notification.body, params,
        )

    # ──────────────── 互亿无线通道 ────────────────

    def _build_ihuyi_content(self, notification: Notification, params: dict) -> str:
        """构建互亿无线短信完整内容。

        互亿无线支持直接发送完整内容，无需预定义模板。
        """
        parts = []
        if notification.title:
            parts.append(notification.title)
        if notification.body:
            parts.append(notification.body)
        content = " ".join(parts) if parts else ""

        # 附加参数信息
        extra = []
        for k, v in params.items():
            if k not in ("title", "body"):
                extra.append(f"{k}={v}")
        if extra:
            content += " " + " ".join(extra)

        return content.strip()

    def _send_via_ihuyi(self, phone: str, notification: Notification, params: dict) -> None:
        """生产模式：调用互亿无线短信 API。"""
        import httpx

        content = self._build_ihuyi_content(notification, params)

        data = {
            "account": self._api_id,
            "password": self._api_key,
            "mobile": phone,
            "content": content,
            "format": "json",
        }
        if self._sign:
            data["sign"] = self._sign

        try:
            response = httpx.post(
                _IHUYI_SMS_ENDPOINT,
                data=data,
                timeout=10.0,
            )
            result = response.json()
            code = result.get("code", -1)
            msg = result.get("msg", "")
            smsid = result.get("smsid", "")

            if code == 2:
                logger.info("[SMS] sent: phone=%s smsid=%s", phone, smsid)
            else:
                logger.error("[SMS] failed: phone=%s code=%s msg=%s", phone, code, msg)
        except Exception as e:
            logger.error("[SMS] request failed: phone=%s error=%s", phone, e)

    # ──────────────── 阿里云通道（备选） ────────────────

    def _send_via_aliyun(self, phone: str, template_params: dict) -> None:
        """生产模式：调用阿里云短信 API。"""
        import httpx

        params = self._build_request_params(phone, template_params)
        # 排序参数
        sorted_keys = sorted(params.keys())
        canonicalized_query = "&".join(
            f"{quote(k, safe='')}={quote(params[k], safe='')}" for k in sorted_keys
        )
        # 计算签名
        string_to_sign = f"GET&{quote('/', safe='')}&{quote(canonicalized_query, safe='')}"
        sign = self._sign_aliyun(string_to_sign)
        params["Signature"] = sign

        try:
            response = httpx.get(
                _ALIYUN_SMS_ENDPOINT,
                params=params,
                timeout=10.0,
            )
            result = response.json()
            code = result.get("Code", "")
            message = result.get("Message", "")
            biz_id = result.get("BizId", "")

            if code == "OK":
                logger.info("[SMS] sent: phone=%s biz_id=%s", phone, biz_id)
            else:
                logger.error("[SMS] failed: phone=%s code=%s message=%s", phone, code, message)
        except Exception as e:
            logger.error("[SMS] request failed: phone=%s error=%s", phone, e)

    def _build_request_params(self, phone: str, template_params: dict) -> dict[str, str]:
        """构建阿里云短信 API 请求参数。"""
        import json

        return {
            "AccessKeyId": self._access_key_id,
            "Action": "SendSms",
            "Format": "JSON",
            "PhoneNumbers": phone,
            "RegionId": "cn-hangzhou",
            "SignName": self._sign_name,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": uuid.uuid4().hex,
            "SignatureVersion": "1.0",
            "TemplateCode": self._template_code,
            "TemplateParam": json.dumps(template_params, ensure_ascii=False),
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Version": "2017-05-25",
        }

    def _sign_aliyun(self, string_to_sign: str) -> str:
        """HMAC-SHA1 签名。"""
        key = (self._access_key_secret + "&").encode("utf-8")
        h = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1)
        return quote(h.digest().decode("latin-1"), safe="")