"""微信支付 V3 Native 网关实现。

依赖：cryptography（RSA 签名/AES-GCM 解密）、httpx（HTTP 请求）

环境变量配置（通过 TransportConfig 传入）：
    WECHAT_APP_ID          — 微信开放平台 AppID（公众号/小程序/网站应用）
    WECHAT_MCH_ID          — 微信商户号
    WECHAT_API_V3_KEY      — APIv3 密钥（32 字节，用于回调解密）
    WECHAT_MCH_SERIAL_NO   — 商户证书序列号
    WECHAT_PRIVATE_KEY     — 商户私钥 PEM 文件路径
    WECHAT_NOTIFY_URL      — 支付回调通知地址（公网可访问 HTTPS）
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from umcp_core.shared.payment.base import (
    PaymentGateway,
    PaymentIntent,
    PaymentStatus,
    PaymentStatusEnum,
    PaymentType,
    RefundResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 微信支付 V3 API 地址
# ---------------------------------------------------------------------------
WECHAT_API_BASE = "https://api.mch.weixin.qq.com"

# 订单状态映射
_WECHAT_STATUS_MAP: dict[str, PaymentStatusEnum] = {
    "SUCCESS": PaymentStatusEnum.PAID,
    "REFUND": PaymentStatusEnum.REFUNDED,
    "NOTPAY": PaymentStatusEnum.PENDING,
    "CLOSED": PaymentStatusEnum.FAILED,
    "PAYERROR": PaymentStatusEnum.FAILED,
    "REVOKED": PaymentStatusEnum.FAILED,
}

# 回调重放攻击防御参数
_CALLBACK_TIMESTAMP_WINDOW = 300  # 5 分钟，允许的时间偏差
_CALLBACK_NONCE_CACHE_TTL = 600  # nonce 缓存过期时间（10 分钟）

_DESCRIPTION_MAP: dict[PaymentType, str] = {
    PaymentType.DEPOSIT: "陪驾定金",
    PaymentType.BALANCE: "陪驾尾款",
    PaymentType.FULL: "陪驾全额支付",
    PaymentType.REFUND: "陪驾退款",
}


class WechatPayGateway(PaymentGateway):
    """微信支付 V3 Native 网关。

    使用 Native 模式（扫码支付），前端展示 code_url 生成的二维码，
    用户用微信扫码完成支付，微信异步通知后端。
    """

    def __init__(
        self,
        app_id: str,
        mch_id: str,
        api_v3_key: str,
        mch_serial_no: str,
        private_key_path: str,
        notify_url: str = "",
        base_url: str = WECHAT_API_BASE,
    ) -> None:
        self._app_id = app_id
        self._mch_id = mch_id
        self._api_v3_key = api_v3_key.encode("utf-8")  # AES key bytes
        self._mch_serial_no = mch_serial_no
        self._notify_url = notify_url
        self._base_url = base_url.rstrip("/")

        # 加载商户私钥
        self._private_key = _load_private_key(private_key_path)

        # 缓存微信支付平台证书（用于回调签名验证）
        # 结构: {serial_no: (cert_obj, expires_at)}
        self._platform_certs: dict[str, tuple[Any, float]] = {}
        self._certs_last_fetch: float = 0
        self._certs_ttl: float = 7200  # 2 小时刷新一次

        # 重放攻击防御缓存：记录已使用的 nonce
        # 结构: {nonce: timestamp} 定时清理过期条目
        self._used_nonces: dict[str, float] = {}
        self._nonce_cache_lock = threading.Lock()

        logger.info(
            "[WECHAT] gateway initialized: app_id=%s mch_id=%s serial_no=%s",
            app_id, mch_id, mch_serial_no,
        )

    # ------------------------------------------------------------------
    # PaymentGateway 接口实现
    # ------------------------------------------------------------------

    def create_payment(
        self, deal_id: str, amount: float, payment_type: PaymentType
    ) -> PaymentIntent:
        """创建微信支付 Native 订单，返回 code_url（二维码链接）。"""
        payment_id = f"wx_{uuid.uuid4().hex[:20]}"
        description = _DESCRIPTION_MAP.get(payment_type, "通用支付")
        total_fen = _to_fen(amount)

        body = {
            "appid": self._app_id,
            "mchid": self._mch_id,
            "description": description,
            "out_trade_no": payment_id,
            "notify_url": self._notify_url,
            "amount": {
                "total": total_fen,
                "currency": "CNY",
            },
        }

        logger.info(
            "[WECHAT_CREATE] calling native API: payment_id=%s amount=%s total_fen=%s",
            payment_id, amount, total_fen,
        )

        try:
            resp = self._request("POST", "/v3/pay/transactions/native", body)
            code_url = resp.get("code_url", "")
            logger.info(
                "[WECHAT_CREATE] success: payment_id=%s code_url_len=%s",
                payment_id, len(code_url),
            )
        except Exception as e:
            logger.error("[WECHAT_CREATE] failed: payment_id=%s error=%s", payment_id, e)
            raise RuntimeError(f"微信支付创建订单失败: {e}") from e

        return PaymentIntent(
            payment_id=payment_id,
            deal_id=deal_id,
            amount=amount,
            payment_type=payment_type,
            code_url=code_url,
            client_secret="",  # Native 模式不需要 client_secret
        )

    def query_payment(self, payment_id: str) -> PaymentStatus:
        """查询订单支付状态。"""
        path = f"/v3/pay/transactions/out-trade-no/{payment_id}?mchid={self._mch_id}"
        logger.info("[WECHAT_QUERY] querying: payment_id=%s", payment_id)

        try:
            resp = self._request("GET", path)
            trade_state = resp.get("trade_state", "NOTPAY")
            status = _WECHAT_STATUS_MAP.get(trade_state, PaymentStatusEnum.PENDING)
            trade_no = resp.get("transaction_id", "")

            paid_at_str = resp.get("success_time")
            paid_at = None
            if paid_at_str:
                try:
                    paid_at = datetime.fromisoformat(paid_at_str.replace("Z", "+00:00"))
                except ValueError:
                    paid_at = datetime.utcnow()

            logger.info(
                "[WECHAT_QUERY] result: payment_id=%s trade_state=%s mapped=%s",
                payment_id, trade_state, status.value,
            )
            return PaymentStatus(
                payment_id=payment_id,
                status=status,
                trade_no=trade_no,
                paid_at=paid_at,
            )
        except Exception as e:
            logger.error("[WECHAT_QUERY] failed: payment_id=%s error=%s", payment_id, e)
            return PaymentStatus(
                payment_id=payment_id,
                status=PaymentStatusEnum.FAILED,
                trade_no="",
            )

    def refund(self, payment_id: str, amount: float, reason: str) -> RefundResult:
        """发起退款。"""
        total_fen = _to_fen(amount)
        refund_id = f"ref_{uuid.uuid4().hex[:16]}"

        body = {
            "out_trade_no": payment_id,
            "out_refund_no": refund_id,
            "reason": reason,
            "amount": {
                "refund": total_fen,
                "total": total_fen,
                "currency": "CNY",
            },
        }

        logger.info(
            "[WECHAT_REFUND] calling API: payment_id=%s amount=%s reason=%s refund_id=%s",
            payment_id, amount, reason, refund_id,
        )

        try:
            resp = self._request("POST", "/v3/refund/domestic/refunds", body)
            refund_status = resp.get("status", "")
            success = refund_status in ("SUCCESS", "PROCESSING")
            trade_no = resp.get("refund_id", "")

            logger.info(
                "[WECHAT_REFUND] result: payment_id=%s status=%s success=%s",
                payment_id, refund_status, success,
            )
            return RefundResult(
                payment_id=payment_id,
                success=success,
                refund_amount=amount,
                trade_no=trade_no,
                message=f"微信退款: {refund_status}",
            )
        except Exception as e:
            logger.error("[WECHAT_REFUND] failed: payment_id=%s error=%s", payment_id, e)
            return RefundResult(
                payment_id=payment_id,
                success=False,
                refund_amount=0.0,
                message=str(e),
            )

    def close_payment(self, payment_id: str) -> bool:
        """关闭微信支付订单（取消未支付的订单）。

        微信支付 V3 API: POST /v3/pay/transactions/out-trade-no/{out_trade_no}/close
        仅对 Native 扫码支付模式有效，已支付订单无法关闭。
        """
        path = f"/v3/pay/transactions/out-trade-no/{payment_id}/close"
        body = {"mchid": self._mch_id}

        logger.info("[WECHAT_CLOSE] closing: payment_id=%s", payment_id)
        try:
            self._request("POST", path, body)
            logger.info("[WECHAT_CLOSE] success: payment_id=%s", payment_id)
            return True
        except Exception as e:
            logger.error("[WECHAT_CLOSE] failed: payment_id=%s error=%s", payment_id, e)
            return False

    def handle_callback(self, raw_data: bytes) -> dict:
        """处理微信支付回调通知。

        验证签名 → 解密 resource → 返回支付结果。
        """
        try:
            body = json.loads(raw_data)
        except json.JSONDecodeError as e:
            logger.error("[WECHAT_CALLBACK] invalid JSON: %s", e)
            return {"status": "failed", "error": "invalid json"}

        event_type = body.get("event_type", "")
        resource = body.get("resource", {})

        # 解密 resource
        try:
            plaintext = self._decrypt_resource(resource)
        except Exception as e:
            logger.error("[WECHAT_CALLBACK] decrypt failed: %s", e)
            return {"status": "failed", "error": f"decrypt error: {e}"}

        payment_info = json.loads(plaintext)
        out_trade_no = payment_info.get("out_trade_no", "")
        trade_state = payment_info.get("trade_state", "")
        transaction_id = payment_info.get("transaction_id", "")
        success_time = payment_info.get("success_time", "")

        mapped_status = _WECHAT_STATUS_MAP.get(trade_state, PaymentStatusEnum.PENDING)
        logger.info(
            "[WECHAT_CALLBACK] received: event_type=%s out_trade_no=%s trade_state=%s",
            event_type, out_trade_no, trade_state,
        )

        return {
            "status": mapped_status.value,
            "payment_id": out_trade_no,
            "trade_no": transaction_id,
            "paid_at": success_time,
            "event_type": event_type,
            "raw": plaintext,
        }

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        """发起微信支付 API 请求（自动签名）。"""
        import httpx

        url = f"{self._base_url}{path}"
        body_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body else ""

        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex[:16]
        auth = self._build_auth(method, path, timestamp, nonce, body_bytes)

        headers = {
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "UMCP-Core/2.0 WechatPayGateway",
        }

        logger.debug("[WECHAT_REQ] %s %s body_len=%s", method, path, len(body_bytes))
        response = httpx.request(method, url, headers=headers, content=body_bytes, timeout=15.0)
        logger.debug("[WECHAT_RES] %s status=%s", path, response.status_code)

        if response.status_code in (200, 201, 204):
            return response.json() if response.text else {}

        # 错误处理
        try:
            err = response.json()
            code = err.get("code", "UNKNOWN")
            message = err.get("message", response.text)
        except Exception:
            code = "HTTP_ERROR"
            message = response.text

        logger.error("[WECHAT_ERR] %s %s: code=%s message=%s", method, path, code, message)
        raise RuntimeError(f"微信支付 API 错误 [{code}]: {message}")

    def _build_auth(
        self, method: str, path: str, timestamp: str, nonce: str, body: str
    ) -> str:
        """构建 WeChat Pay V3 Authorization header。

        签名方式：WECHATPAY2-SHA256-RSA2048
        """
        message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"
        signature = _rsa_sign(self._private_key, message)
        return (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{self._mch_id}",'
            f'nonce_str="{nonce}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self._mch_serial_no}",'
            f'signature="{signature}"'
        )

    def _decrypt_resource(self, resource: dict) -> str:
        """使用 APIv3 密钥解密 resource 中的 ciphertext (AEAD_AES_256_GCM)。"""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        ciphertext = resource.get("ciphertext", "")
        associated_data = resource.get("associated_data", "")
        nonce = resource.get("nonce", "")

        # 解码 base64
        import base64
        ct = base64.b64decode(ciphertext)
        n = base64.b64decode(nonce)
        ad = associated_data.encode("utf-8")

        aesgcm = AESGCM(self._api_v3_key)
        plaintext = aesgcm.decrypt(n, ct, ad)
        return plaintext.decode("utf-8")

    def ensure_platform_certs(self) -> None:
        """获取并缓存微信支付平台证书（回调验签用）。"""
        now = time.time()
        if now - self._certs_last_fetch < self._certs_ttl and self._platform_certs:
            return

        logger.info("[WECHAT_CERTS] fetching platform certificates")
        try:
            resp = self._request("GET", "/v3/certificates")
        except Exception as e:
            logger.warning("[WECHAT_CERTS] fetch failed (will retry): %s", e)
            return

        for data in resp.get("data", []):
            serial_no = data.get("serial_no", "")
            encrypt_cert = data.get("encrypt_certificate", {})
            try:
                plain = self._decrypt_resource(encrypt_cert)
                cert_obj = _load_certificate(plain)
                expire_time = data.get("expire_time", "")
                expires_at = 0.0
                if expire_time:
                    try:
                        dt = datetime.fromisoformat(expire_time.replace("Z", "+00:00"))
                        expires_at = dt.timestamp()
                    except ValueError:
                        expires_at = now + 86400 * 30  # 默认 30 天
                self._platform_certs[serial_no] = (cert_obj, expires_at)
                logger.info("[WECHAT_CERTS] cached cert: serial_no=%s expire=%s", serial_no, expire_time)
            except Exception as e:
                logger.warning("[WECHAT_CERTS] decrypt cert failed: serial_no=%s error=%s", serial_no, e)

        self._certs_last_fetch = now

    def verify_callback_signature(
        self, body: bytes, signature: str, timestamp: str, nonce: str, serial_no: str
    ) -> bool:
        """验证微信支付回调签名，防御重放攻击。

        防御策略：
          1. 时间戳窗口校验：回调时间戳必须在当前时间 ±5 分钟内
          2. Nonce 防重放：同一 nonce 只能使用一次，缓存 10 分钟
          3. 证书有效性校验：平台证书必须存在且未过期
          4. RSA-SHA256 签名验证：使用微信平台证书公钥验签
        """
        # 1. 时间戳窗口校验：防止重放攻击
        try:
            ts = int(timestamp)
        except (ValueError, TypeError):
            logger.warning("[WECHAT_VERIFY] invalid timestamp: %s", timestamp)
            return False
        now = time.time()
        if abs(now - ts) > _CALLBACK_TIMESTAMP_WINDOW:
            logger.warning(
                "[WECHAT_VERIFY] timestamp out of window: ts=%s now=%s diff=%ss window=%ss",
                ts, int(now), abs(now - ts), _CALLBACK_TIMESTAMP_WINDOW,
            )
            return False

        # 2. Nonce 防重放：同一 nonce 只能使用一次
        if self._is_nonce_replayed(nonce):
            logger.warning("[WECHAT_VERIFY] nonce replayed: nonce=%s", nonce)
            return False

        # 3. 加载平台证书
        self.ensure_platform_certs()
        cert_info = self._platform_certs.get(serial_no)
        if cert_info is None:
            logger.warning("[WECHAT_VERIFY] cert not found: serial_no=%s", serial_no)
            return False

        # 4. 证书有效期检查（仅警告，不拒绝）
        cert_obj, expires_at = cert_info
        if now > expires_at:
            logger.warning("[WECHAT_VERIFY] cert expired: serial_no=%s", serial_no)

        # 5. RSA-SHA256 签名验证
        message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n"
        try:
            _rsa_verify(cert_obj, message, signature)
            # 验签通过后标记 nonce 已使用
            self._mark_nonce_used(nonce)
            return True
        except Exception as e:
            logger.warning("[WECHAT_VERIFY] signature verification failed: %s", e)
            return False

    def _is_nonce_replayed(self, nonce: str) -> bool:
        """检查 nonce 是否已被使用过（线程安全）。

        首次看到 nonce 返回 False，之后相同 nonce 返回 True。
        同时清理过期 nonce 缓存。
        """
        now = time.time()
        with self._nonce_cache_lock:
            # 清理过期条目
            expired = [k for k, v in self._used_nonces.items() if now - v > _CALLBACK_NONCE_CACHE_TTL]
            for k in expired:
                del self._used_nonces[k]
            if nonce in self._used_nonces:
                return True
            return False

    def _mark_nonce_used(self, nonce: str) -> None:
        """标记 nonce 为已使用（线程安全）。"""
        with self._nonce_cache_lock:
            self._used_nonces[nonce] = time.time()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _to_fen(amount: float) -> int:
    """元转分（微信支付金额单位为分）。"""
    return int(round(amount * 100))


def _load_private_key(path: str) -> Any:
    """加载商户 RSA 私钥 PEM。"""
    from cryptography.hazmat.primitives import serialization

    key_path = Path(path)
    if not key_path.exists():
        raise FileNotFoundError(f"商户私钥文件不存在: {path}")

    with key_path.open("rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None,
        )
    return private_key


def _load_certificate(pem: str) -> Any:
    """加载 PEM 格式证书。"""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_pem_x509_certificate(pem.encode("utf-8"))
    return cert.public_key()


def _rsa_sign(private_key: Any, message: str) -> str:
    """RSA-SHA256 签名，返回 Base64 编码结果。"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    import base64
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _rsa_verify(public_key: Any, message: str, signature_b64: str) -> None:
    """RSA-SHA256 验签。"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    import base64
    signature = base64.b64decode(signature_b64)
    public_key.verify(
        signature,
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )