"""微信支付 V3 Native 网关单元测试。

测试策略：
  - 使用临时 RSA 私钥和证书初始化 WechatPayGateway
  - 使用 unittest.mock 模拟 HTTP 请求，避免真实调用微信支付 API
  - 覆盖所有公开方法：create_payment / query_payment / refund / handle_callback / verify_callback_signature
  - 覆盖工具函数：_to_fen / _load_private_key / _load_certificate / _rsa_sign / _rsa_verify
  - 覆盖异常分支：无效 JSON / 解密失败 / 签名验证失败 / 时间戳越界 / nonce 重放
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.backends import default_backend


# ============================================================
# 辅助：生成临时 RSA 密钥对和自签名证书
# ============================================================

@pytest.fixture(scope="session")
def rsa_key_pair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    """会话级 RSA 密钥对。"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


@pytest.fixture(scope="session")
def rsa_private_key_path(rsa_key_pair, tmp_path_factory) -> Path:
    """写入临时 PEM 私钥文件。"""
    private_key, _ = rsa_key_pair
    path = tmp_path_factory.mktemp("keys") / "test_merchant_key.pem"
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    return path


@pytest.fixture(scope="session")
def platform_cert_pem(rsa_key_pair) -> str:
    """生成自签名 PEM 证书（模拟微信支付平台证书）。"""
    private_key, _ = rsa_key_pair
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "WechatPay Platform Cert"),
    ])
    import datetime
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256(), default_backend())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")


@pytest.fixture
def wechat_gateway(rsa_private_key_path) -> Generator["WechatPayGateway", None, None]:
    """WechatPayGateway 实例（仅测试用，不真实调用微信 API）。"""
    from umcp_core.shared.payment.wechat import WechatPayGateway as Cls

    gw = Cls(
        app_id="test_app_id",
        mch_id="test_mch_id",
        api_v3_key="test_api_v3_key_32bytes!!!!!!!!!",
        mch_serial_no="test_serial_no",
        private_key_path=str(rsa_private_key_path),
        notify_url="https://example.com/callback",
        base_url="https://api.mch.weixin.qq.com",
    )
    yield gw


# ============================================================
# 1. 工具函数测试
# ============================================================

class TestUtils:
    """_to_fen / _load_private_key / _load_certificate / _rsa_sign / _rsa_verify。"""

    def test_to_fen_converts_correctly(self):
        from umcp_core.shared.payment.wechat import _to_fen
        assert _to_fen(0.0) == 0
        assert _to_fen(1.0) == 100
        assert _to_fen(1.5) == 150
        assert _to_fen(0.01) == 1
        assert _to_fen(99.99) == 9999
        assert _to_fen(100.00) == 10000

    def test_to_fen_rounds_correctly(self):
        from umcp_core.shared.payment.wechat import _to_fen
        assert _to_fen(1.234) == 123
        assert _to_fen(1.235) == 124
        assert _to_fen(1.999) == 200

    def test_load_private_key_success(self, rsa_private_key_path):
        from umcp_core.shared.payment.wechat import _load_private_key
        key = _load_private_key(str(rsa_private_key_path))
        assert key is not None

    def test_load_private_key_file_not_found(self):
        from umcp_core.shared.payment.wechat import _load_private_key
        with pytest.raises(FileNotFoundError, match="商户私钥文件不存在"):
            _load_private_key("/nonexistent/path/key.pem")

    def test_load_certificate(self, platform_cert_pem):
        from umcp_core.shared.payment.wechat import _load_certificate
        pub_key = _load_certificate(platform_cert_pem)
        assert pub_key is not None

    def test_rsa_sign_and_verify(self, rsa_key_pair, rsa_private_key_path):
        from umcp_core.shared.payment.wechat import _load_private_key, _rsa_sign, _rsa_verify
        private_key = _load_private_key(str(rsa_private_key_path))
        message = "test_message_for_signing"
        signature = _rsa_sign(private_key, message)
        assert signature
        # 用同一密钥验证
        public_key = rsa_key_pair[1]
        _rsa_verify(public_key, message, signature)  # 不抛异常即验证通过

    def test_rsa_verify_wrong_message_raises(self, rsa_key_pair, rsa_private_key_path):
        from umcp_core.shared.payment.wechat import _load_private_key, _rsa_sign, _rsa_verify
        private_key = _load_private_key(str(rsa_private_key_path))
        signature = _rsa_sign(private_key, "original_message")
        public_key = rsa_key_pair[1]
        with pytest.raises(Exception):
            _rsa_verify(public_key, "wrong_message", signature)


# ============================================================
# 2. WechatPayGateway 初始化
# ============================================================

class TestInit:
    """构造函数与属性。"""

    def test_initialization_success(self, wechat_gateway):
        assert wechat_gateway._app_id == "test_app_id"
        assert wechat_gateway._mch_id == "test_mch_id"
        assert wechat_gateway._mch_serial_no == "test_serial_no"
        assert wechat_gateway._notify_url == "https://example.com/callback"
        assert wechat_gateway._base_url == "https://api.mch.weixin.qq.com"
        assert wechat_gateway._private_key is not None
        assert wechat_gateway._api_v3_key == b"test_api_v3_key_32bytes!!!!!!!!!"
        assert wechat_gateway._platform_certs == {}
        assert wechat_gateway._used_nonces == {}

    def test_initialization_invalid_private_key_path(self):
        from umcp_core.shared.payment.wechat import WechatPayGateway
        with pytest.raises(FileNotFoundError):
            WechatPayGateway(
                app_id="a", mch_id="b", api_v3_key="c" * 32,
                mch_serial_no="d", private_key_path="/nonexistent/key.pem",
            )


# ============================================================
# 3. create_payment 测试
# ============================================================

class TestCreatePayment:
    """WechatPayGateway.create_payment()"""

    @patch("httpx.request")
    def test_create_payment_success(self, mock_request, wechat_gateway):
        from umcp_core.shared.payment.base import PaymentType
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"code_url": "weixin://pay/test_url_123"}

        intent = wechat_gateway.create_payment("deal_1", 100.0, PaymentType.DEPOSIT)

        assert intent.payment_id.startswith("wx_")
        assert intent.deal_id == "deal_1"
        assert intent.amount == 100.0
        assert intent.payment_type == PaymentType.DEPOSIT
        assert intent.code_url == "weixin://pay/test_url_123"
        assert intent.client_secret == ""

        # 验证 HTTP 请求参数
        call_args = mock_request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://api.mch.weixin.qq.com/v3/pay/transactions/native"
        body = json.loads(call_args[1]["content"])
        assert body["appid"] == "test_app_id"
        assert body["mchid"] == "test_mch_id"
        assert body["description"] == "陪驾定金"
        assert body["amount"]["total"] == 10000
        assert body["amount"]["currency"] == "CNY"
        assert "Authorization" in call_args[1]["headers"]

    @patch("httpx.request")
    def test_create_payment_http_error_raises(self, mock_request, wechat_gateway):
        from umcp_core.shared.payment.base import PaymentType
        mock_request.return_value.status_code = 400
        mock_request.return_value.text = "bad request"
        mock_request.return_value.json.return_value = {"code": "PARAM_ERROR", "message": "参数错误"}

        with pytest.raises(RuntimeError, match="微信支付创建订单失败"):
            wechat_gateway.create_payment("deal_1", 100.0, PaymentType.DEPOSIT)

    @patch("httpx.request")
    def test_create_payment_empty_code_url(self, mock_request, wechat_gateway):
        from umcp_core.shared.payment.base import PaymentType
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {}

        intent = wechat_gateway.create_payment("deal_1", 100.0, PaymentType.DEPOSIT)
        assert intent.code_url == ""

    @patch("httpx.request")
    def test_create_payment_balance_type(self, mock_request, wechat_gateway):
        from umcp_core.shared.payment.base import PaymentType
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"code_url": "weixin://pay/balance"}

        intent = wechat_gateway.create_payment("deal_1", 200.0, PaymentType.BALANCE)
        body = json.loads(mock_request.call_args[1]["content"])
        assert body["description"] == "陪驾尾款"
        assert body["amount"]["total"] == 20000

    @patch("httpx.request")
    def test_create_payment_full_type(self, mock_request, wechat_gateway):
        from umcp_core.shared.payment.base import PaymentType
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"code_url": "weixin://pay/full"}

        intent = wechat_gateway.create_payment("deal_1", 500.0, PaymentType.FULL)
        body = json.loads(mock_request.call_args[1]["content"])
        assert body["description"] == "陪驾全额支付"
        assert body["amount"]["total"] == 50000


# ============================================================
# 4. query_payment 测试
# ============================================================

class TestQueryPayment:
    """WechatPayGateway.query_payment()"""

    @patch("httpx.request")
    def test_query_payment_paid(self, mock_request, wechat_gateway):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "trade_state": "SUCCESS",
            "transaction_id": "wx_trade_001",
            "success_time": "2026-08-15T10:00:00+08:00",
        }

        status = wechat_gateway.query_payment("wx_test_001")
        assert status.status.value == "paid"
        assert status.trade_no == "wx_trade_001"
        assert status.paid_at is not None

    @patch("httpx.request")
    def test_query_payment_pending(self, mock_request, wechat_gateway):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "trade_state": "NOTPAY",
            "transaction_id": "",
        }

        status = wechat_gateway.query_payment("wx_test_001")
        assert status.status.value == "pending"
        assert status.trade_no == ""

    @patch("httpx.request")
    def test_query_payment_closed(self, mock_request, wechat_gateway):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "trade_state": "CLOSED",
            "transaction_id": "",
        }

        status = wechat_gateway.query_payment("wx_test_001")
        assert status.status.value == "failed"

    @patch("httpx.request")
    def test_query_payment_pay_error(self, mock_request, wechat_gateway):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "trade_state": "PAYERROR",
            "transaction_id": "",
        }

        status = wechat_gateway.query_payment("wx_test_001")
        assert status.status.value == "failed"

    @patch("httpx.request")
    def test_query_payment_revoked(self, mock_request, wechat_gateway):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "trade_state": "REVOKED",
            "transaction_id": "",
        }

        status = wechat_gateway.query_payment("wx_test_001")
        assert status.status.value == "failed"

    @patch("httpx.request")
    def test_query_payment_http_error_returns_failed(self, mock_request, wechat_gateway):
        mock_request.side_effect = RuntimeError("connection error")

        status = wechat_gateway.query_payment("wx_test_001")
        assert status.status.value == "failed"
        assert status.trade_no == ""


# ============================================================
# 5. refund 测试
# ============================================================

class TestRefund:
    """WechatPayGateway.refund()"""

    @patch("httpx.request")
    def test_refund_success(self, mock_request, wechat_gateway):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "status": "SUCCESS",
            "refund_id": "refund_trade_001",
        }

        result = wechat_gateway.refund("wx_test_001", 50.0, "测试退款")
        assert result.success is True
        assert result.refund_amount == 50.0
        assert result.trade_no == "refund_trade_001"
        assert "SUCCESS" in result.message

    @patch("httpx.request")
    def test_refund_processing(self, mock_request, wechat_gateway):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "status": "PROCESSING",
            "refund_id": "refund_trade_002",
        }

        result = wechat_gateway.refund("wx_test_001", 30.0, "部分退款")
        assert result.success is True

    @patch("httpx.request")
    def test_refund_failed(self, mock_request, wechat_gateway):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "status": "FAILED",
            "refund_id": "",
        }

        result = wechat_gateway.refund("wx_test_001", 50.0, "退款失败")
        assert result.success is False

    @patch("httpx.request")
    def test_refund_http_error_returns_failed(self, mock_request, wechat_gateway):
        mock_request.side_effect = RuntimeError("connection error")

        result = wechat_gateway.refund("wx_test_001", 50.0, "error")
        assert result.success is False
        assert result.refund_amount == 0.0


# ============================================================
# 6. handle_callback 测试
# ============================================================

class TestHandleCallback:
    """WechatPayGateway.handle_callback()"""

    def test_handle_callback_invalid_json(self, wechat_gateway):
        result = wechat_gateway.handle_callback(b"not json")
        assert result["status"] == "failed"
        assert "invalid json" in result["error"]

    def test_handle_callback_decrypt_failure(self, wechat_gateway):
        callback_data = json.dumps({
            "event_type": "TRANSACTION.SUCCESS",
            "resource": {
                "algorithm": "AEAD_AES_256_GCM",
                "ciphertext": "invalid_base64",
                "associated_data": "transaction",
                "nonce": "invalid_nonce",
            },
        }).encode("utf-8")

        result = wechat_gateway.handle_callback(callback_data)
        assert result["status"] == "failed"
        assert "decrypt error" in result["error"]

    def test_handle_callback_empty_body(self, wechat_gateway):
        result = wechat_gateway.handle_callback(b"")
        assert result["status"] == "failed"
        assert "invalid json" in result["error"]


# ============================================================
# 7. verify_callback_signature 测试
# ============================================================

class TestVerifyCallbackSignature:
    """WechatPayGateway.verify_callback_signature()"""

    def test_verify_invalid_timestamp(self, wechat_gateway):
        """无效时间戳 → False。"""
        result = wechat_gateway.verify_callback_signature(
            body=b"{}",
            signature="sig",
            timestamp="not_a_number",
            nonce="nonce_1",
            serial_no="serial_1",
        )
        assert result is False

    def test_verify_timestamp_out_of_window(self, wechat_gateway):
        """时间戳超出窗口 → False。"""
        old_ts = str(int(time.time()) - 3600)  # 1 小时前
        result = wechat_gateway.verify_callback_signature(
            body=b"{}",
            signature="sig",
            timestamp=old_ts,
            nonce="nonce_2",
            serial_no="serial_2",
        )
        assert result is False

    def test_verify_nonce_replay_detected(self, wechat_gateway):
        """同一 nonce 重复使用 → False。"""
        # 先标记 nonce 为已使用
        wechat_gateway._mark_nonce_used("replayed_nonce")
        result = wechat_gateway.verify_callback_signature(
            body=b"{}",
            signature="sig",
            timestamp=str(int(time.time())),
            nonce="replayed_nonce",
            serial_no="serial_3",
        )
        assert result is False

    def test_verify_cert_not_found(self, wechat_gateway):
        """证书序列号不存在 → False。"""
        result = wechat_gateway.verify_callback_signature(
            body=b"{}",
            signature="sig",
            timestamp=str(int(time.time())),
            nonce="fresh_nonce_1",
            serial_no="nonexistent_serial",
        )
        assert result is False

    def test_verify_signature_mismatch(self, wechat_gateway, platform_cert_pem):
        """签名不匹配 → False。"""
        # 手动注入一个平台证书
        from umcp_core.shared.payment.wechat import _load_certificate
        pub_key = _load_certificate(platform_cert_pem)
        wechat_gateway._platform_certs["test_serial"] = (pub_key, time.time() + 86400)

        result = wechat_gateway.verify_callback_signature(
            body=b"{}",
            signature="wrong_signature",
            timestamp=str(int(time.time())),
            nonce="fresh_nonce_2",
            serial_no="test_serial",
        )
        assert result is False

    def test_verify_signature_success(self, wechat_gateway, rsa_key_pair, platform_cert_pem):
        """完整验签成功 → True。"""
        from umcp_core.shared.payment.wechat import _load_certificate, _rsa_sign

        # 注入平台证书
        pub_key = _load_certificate(platform_cert_pem)
        wechat_gateway._platform_certs["test_serial"] = (pub_key, time.time() + 86400)

        # 使用平台私钥（与证书匹配）构造合法的签名
        body = b'{"test": "data"}'
        timestamp = str(int(time.time()))
        nonce = "fresh_nonce_3"
        message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n"
        valid_signature = _rsa_sign(rsa_key_pair[0], message)

        result = wechat_gateway.verify_callback_signature(
            body=body,
            signature=valid_signature,
            timestamp=timestamp,
            nonce=nonce,
            serial_no="test_serial",
        )
        assert result is True

    def test_verify_nonce_replay_after_success(self, wechat_gateway, rsa_key_pair, platform_cert_pem):
        """验签成功后，相同 nonce 再次使用 → False。"""
        from umcp_core.shared.payment.wechat import _load_certificate, _rsa_sign

        pub_key = _load_certificate(platform_cert_pem)
        wechat_gateway._platform_certs["test_serial"] = (pub_key, time.time() + 86400)

        body = b"test"
        timestamp = str(int(time.time()))
        nonce = "nonce_for_replay_test"
        message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n"
        signature = _rsa_sign(rsa_key_pair[0], message)

        # 第一次验签 → 成功
        first = wechat_gateway.verify_callback_signature(
            body=body, signature=signature,
            timestamp=timestamp, nonce=nonce, serial_no="test_serial",
        )
        assert first is True

        # 第二次使用相同 nonce → 失败（重放）
        second = wechat_gateway.verify_callback_signature(
            body=body, signature=signature,
            timestamp=timestamp, nonce=nonce, serial_no="test_serial",
        )
        assert second is False


# ============================================================
# 8. _decrypt_resource 测试
# ============================================================

class TestDecryptResource:
    """WechatPayGateway._decrypt_resource()"""

    def test_decrypt_success(self, wechat_gateway):
        """使用正确的 APIv3 密钥加密和解密。"""
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        api_v3_key = wechat_gateway._api_v3_key  # 32 bytes
        aesgcm = AESGCM(api_v3_key)
        nonce = b"unique_nonce_12"  # 12 bytes
        plaintext = b'{"out_trade_no":"wx_test","trade_state":"SUCCESS"}'
        aad = b"transaction"

        ct = aesgcm.encrypt(nonce, plaintext, aad)

        resource = {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": base64.b64encode(ct).decode("utf-8"),
            "associated_data": aad.decode("utf-8"),
            "nonce": base64.b64encode(nonce).decode("utf-8"),
        }

        result = wechat_gateway._decrypt_resource(resource)
        assert result == plaintext.decode("utf-8")

    def test_decrypt_wrong_key_fails(self, wechat_gateway):
        """使用错误的密钥解密 → 应失败。"""
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        # 用不同密钥加密
        wrong_key = b"0" * 32
        aesgcm = AESGCM(wrong_key)
        nonce = b"unique_nonce_12"
        ct = aesgcm.encrypt(nonce, b"test_data", b"aad")

        resource = {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": base64.b64encode(ct).decode("utf-8"),
            "associated_data": "aad",
            "nonce": base64.b64encode(nonce).decode("utf-8"),
        }

        with pytest.raises(Exception):
            wechat_gateway._decrypt_resource(resource)

    def test_decrypt_invalid_base64_raises(self, wechat_gateway):
        resource = {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": "!!!invalid_base64",
            "associated_data": "aad",
            "nonce": "YWJjZGVmZw==",
        }
        with pytest.raises(Exception):
            wechat_gateway._decrypt_resource(resource)


# ============================================================
# 9. _build_auth 测试
# ============================================================

class TestBuildAuth:
    """WechatPayGateway._build_auth()"""

    def test_build_auth_contains_required_fields(self, wechat_gateway):
        auth = wechat_gateway._build_auth("POST", "/v3/pay/transactions/native", "1234567890", "test_nonce", '{"a":1}')
        assert auth.startswith("WECHATPAY2-SHA256-RSA2048")
        assert 'mchid="test_mch_id"' in auth
        assert 'nonce_str="test_nonce"' in auth
        assert 'timestamp="1234567890"' in auth
        assert 'serial_no="test_serial_no"' in auth
        assert 'signature="' in auth

    def test_build_auth_empty_body(self, wechat_gateway):
        auth = wechat_gateway._build_auth("GET", "/v3/certificates", "1234567890", "n", "")
        assert auth.startswith("WECHATPAY2-SHA256-RSA2048")

    def test_build_auth_different_methods_produce_different_signatures(self, wechat_gateway):
        auth1 = wechat_gateway._build_auth("GET", "/v3/test", "123", "n1", "")
        auth2 = wechat_gateway._build_auth("POST", "/v3/test", "123", "n1", "")
        assert auth1 != auth2


# ============================================================
# 10. ensure_platform_certs 测试
# ============================================================

class TestEnsurePlatformCerts:
    """WechatPayGateway.ensure_platform_certs()"""

    @patch("httpx.request")
    def test_fetch_certs_success(self, mock_request, wechat_gateway, platform_cert_pem):
        """正常获取平台证书。"""
        # 模拟证书列表 API 返回
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "data": [
                {
                    "serial_no": "cert_serial_001",
                    "expire_time": "2027-08-15T10:00:00+08:00",
                    "encrypt_certificate": {
                        "algorithm": "AEAD_AES_256_GCM",
                        "ciphertext": "dummy_ciphertext",
                        "associated_data": "certificate",
                        "nonce": "dummy_nonce",
                    },
                }
            ]
        }

        # 注入 _decrypt_resource 方法返回正确的 PEM
        original_decrypt = wechat_gateway._decrypt_resource

        def mock_decrypt(resource):
            return platform_cert_pem

        wechat_gateway._decrypt_resource = mock_decrypt

        try:
            wechat_gateway.ensure_platform_certs()
            assert "cert_serial_001" in wechat_gateway._platform_certs
        finally:
            wechat_gateway._decrypt_resource = original_decrypt

    @patch("httpx.request")
    def test_fetch_certs_http_error_does_not_raise(self, mock_request, wechat_gateway):
        """证书获取失败不应抛异常，仅记录日志。"""
        mock_request.side_effect = RuntimeError("network error")
        # 不应抛出异常
        wechat_gateway.ensure_platform_certs()
        assert wechat_gateway._platform_certs == {}

    def test_certs_cache_hit(self, wechat_gateway):
        """缓存未过期时不应重复请求。"""
        wechat_gateway._certs_last_fetch = time.time()
        wechat_gateway._platform_certs["cached"] = ("dummy", time.time() + 86400)

        with patch("httpx.request") as mock_request:
            wechat_gateway.ensure_platform_certs()
            mock_request.assert_not_called()


# ============================================================
# 11. nonce 防重放缓存测试
# ============================================================

class TestNonceReplayCache:
    """_is_nonce_replayed / _mark_nonce_used 行为。"""

    def test_fresh_nonce_returns_false(self, wechat_gateway):
        assert wechat_gateway._is_nonce_replayed("fresh_nonce") is False

    def test_marked_nonce_returns_true(self, wechat_gateway):
        wechat_gateway._mark_nonce_used("used_nonce")
        assert wechat_gateway._is_nonce_replayed("used_nonce") is True

    def test_multiple_nonces_independent(self, wechat_gateway):
        wechat_gateway._mark_nonce_used("nonce_a")
        assert wechat_gateway._is_nonce_replayed("nonce_a") is True
        assert wechat_gateway._is_nonce_replayed("nonce_b") is False

    def test_expired_nonce_is_cleaned(self, wechat_gateway):
        """过期 nonce 在检查时被清理。"""
        from umcp_core.shared.payment.wechat import _CALLBACK_NONCE_CACHE_TTL
        old_time = time.time() - _CALLBACK_NONCE_CACHE_TTL - 60
        wechat_gateway._used_nonces["expired_nonce"] = old_time
        # 检查时同时清理过期条目
        assert wechat_gateway._is_nonce_replayed("expired_nonce") is False
        assert "expired_nonce" not in wechat_gateway._used_nonces


# ============================================================
# 12. 状态映射常量测试
# ============================================================

class TestStatusMapping:
    """_WECHAT_STATUS_MAP 覆盖所有微信支付状态。"""

    def test_all_wechat_states_mapped(self):
        from umcp_core.shared.payment.base import PaymentStatusEnum
        from umcp_core.shared.payment.wechat import _WECHAT_STATUS_MAP
        assert _WECHAT_STATUS_MAP["SUCCESS"] == PaymentStatusEnum.PAID
        assert _WECHAT_STATUS_MAP["REFUND"] == PaymentStatusEnum.REFUNDED
        assert _WECHAT_STATUS_MAP["NOTPAY"] == PaymentStatusEnum.PENDING
        assert _WECHAT_STATUS_MAP["CLOSED"] == PaymentStatusEnum.FAILED
        assert _WECHAT_STATUS_MAP["PAYERROR"] == PaymentStatusEnum.FAILED
        assert _WECHAT_STATUS_MAP["REVOKED"] == PaymentStatusEnum.FAILED

    def test_unknown_state_defaults_to_pending(self):
        from umcp_core.shared.payment.base import PaymentStatusEnum
        from umcp_core.shared.payment.wechat import _WECHAT_STATUS_MAP
        assert _WECHAT_STATUS_MAP.get("UNKNOWN_STATE", PaymentStatusEnum.PENDING) == PaymentStatusEnum.PENDING


# ============================================================
# 13. 描述映射常量测试
# ============================================================

class TestDescriptionMapping:
    """_DESCRIPTION_MAP 覆盖所有支付类型。"""

    def test_all_payment_types_have_description(self):
        from umcp_core.shared.payment.base import PaymentType
        from umcp_core.shared.payment.wechat import _DESCRIPTION_MAP
        for pt in PaymentType:
            desc = _DESCRIPTION_MAP.get(pt)
            assert desc, f"PaymentType.{pt.name} 缺少描述"
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_unknown_type_falls_back(self):
        from umcp_core.shared.payment.base import PaymentType
        from umcp_core.shared.payment.wechat import _DESCRIPTION_MAP
        fallback = _DESCRIPTION_MAP.get(PaymentType.REFUND, "通用支付")
        assert fallback == "陪驾退款"


# ============================================================
# 14. close_payment 测试
# ============================================================

class TestClosePayment:
    """WechatPayGateway.close_payment()"""

    @patch("httpx.request")
    def test_close_payment_success(self, mock_request, wechat_gateway):
        """关闭订单成功 → True。"""
        mock_request.return_value.status_code = 204
        mock_request.return_value.text = ""

        result = wechat_gateway.close_payment("wx_test_001")
        assert result is True

        # 验证 HTTP 请求参数
        call_args = mock_request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://api.mch.weixin.qq.com/v3/pay/transactions/out-trade-no/wx_test_001/close"
        body = json.loads(call_args[1]["content"])
        assert body["mchid"] == "test_mch_id"

    @patch("httpx.request")
    def test_close_payment_http_error_returns_false(self, mock_request, wechat_gateway):
        """HTTP 请求异常 → False。"""
        mock_request.side_effect = RuntimeError("connection error")

        result = wechat_gateway.close_payment("wx_test_001")
        assert result is False

    @patch("httpx.request")
    def test_close_payment_400_response_returns_false(self, mock_request, wechat_gateway):
        """微信 API 返回错误 → False。"""
        mock_request.return_value.status_code = 400
        mock_request.return_value.text = "bad request"
        mock_request.return_value.json.return_value = {"code": "PARAM_ERROR", "message": "参数错误"}

        result = wechat_gateway.close_payment("wx_test_001")
        assert result is False


# ============================================================
# 15. MockGateway.close_payment 测试
# ============================================================

class TestMockClosePayment:
    """MockGateway.close_payment()"""

    def test_close_existing_payment_returns_true(self):
        from umcp_core.shared.payment.mock import MockGateway
        from umcp_core.shared.payment.base import PaymentType

        gw = MockGateway()
        gw.create_payment("deal_1", 100.0, PaymentType.DEPOSIT)

        # 通过 _trade_nos 获取 payment_id
        payment_id = list(gw._trade_nos.keys())[0]
        assert gw.close_payment(payment_id) is True

    def test_close_nonexistent_payment_returns_false(self):
        from umcp_core.shared.payment.mock import MockGateway
        gw = MockGateway()
        assert gw.close_payment("nonexistent") is False


# ============================================================
# 16. PaymentTimeoutWorker 测试
# ============================================================

class TestPaymentTimeoutWorker:
    """PaymentTimeoutWorker 超时自动清理逻辑。"""

    @pytest.fixture
    def worker(self):
        from umcp_core.transport.workers.payment_timeout_worker import PaymentTimeoutWorker
        w = PaymentTimeoutWorker()
        w._last_cleanup_ts = 0.0  # 确保首次运行立即执行
        return w

    @pytest.fixture
    def mock_server(self):
        """创建模拟的 server 对象。"""
        from unittest.mock import MagicMock
        from datetime import datetime, timedelta

        # 创建模拟规则配置
        rule_config = MagicMock()
        rule_config.get.side_effect = lambda key, default=None: {
            "payment.timeout_seconds": 300,  # 5 分钟超时
            "payment.cleanup_interval": 10,
        }.get(key, default)

        # 创建模拟支付服务
        payment_service = MagicMock()
        repo = MagicMock()
        gateway = MagicMock()
        payment_service.repo = repo
        payment_service._gateway = gateway

        # 创建模拟 deal
        deal = MagicMock()
        deal.status = "pending"
        deal.task_id = "task_001"

        # 创建模拟 task
        task = MagicMock()
        task.status = "published"

        # 创建 server
        server = MagicMock()
        server.rule_config = rule_config
        server.payment_service = payment_service
        server.deal_repo = MagicMock()
        server.task_repo = MagicMock()
        server.event_bus = MagicMock()

        server.deal_repo.find_by_id.return_value = deal
        server.task_repo.find_by_id.return_value = task

        return server

    def test_skip_when_no_server(self, worker):
        """无 server 时直接跳过。"""
        import asyncio
        asyncio.run(worker.run(None))  # 不应抛异常

    def test_skip_when_no_rule_config(self, worker, mock_server):
        """无规则配置时直接跳过。"""
        mock_server.rule_config = None
        import asyncio
        asyncio.run(worker.run({"server": mock_server}))  # 不应抛异常

    def test_skip_when_no_payment_service(self, worker, mock_server):
        """无支付服务时直接跳过。"""
        mock_server.payment_service = None
        import asyncio
        asyncio.run(worker.run({"server": mock_server}))  # 不应抛异常

    def test_pending_payment_within_timeout_not_closed(self, worker, mock_server):
        """未超时的 PENDING 支付不应被关闭。"""
        import asyncio
        from datetime import datetime, timedelta
        from umcp_core.shared.payment.base import PaymentStatusEnum

        created_at = datetime.utcnow() - timedelta(seconds=60)  # 仅等待 1 分钟
        mock_server.payment_service.repo.find_by_status.return_value = [
            {"payment_id": "pay_001", "deal_id": "deal_001", "created_at": created_at},
        ]

        asyncio.run(worker.run({"server": mock_server}))

        # 未超时，不应调用 close_payment
        mock_server.payment_service._gateway.close_payment.assert_not_called()

    def test_pending_payment_exceeded_timeout_closes(self, worker, mock_server):
        """超时的 PENDING 支付应被关闭并取消 deal/task。"""
        import asyncio
        from datetime import datetime, timedelta

        created_at = datetime.utcnow() - timedelta(seconds=600)  # 超过 5 分钟
        mock_server.payment_service.repo.find_by_status.return_value = [
            {"payment_id": "pay_001", "deal_id": "deal_001", "created_at": created_at},
        ]

        asyncio.run(worker.run({"server": mock_server}))

        # 应调用 close_payment
        mock_server.payment_service._gateway.close_payment.assert_called_once_with("pay_001")
        # 应更新状态为 FAILED
        from umcp_core.shared.payment.base import PaymentStatusEnum
        mock_server.payment_service.repo.update_status.assert_called_once_with(
            "pay_001", PaymentStatusEnum.FAILED
        )
        # 应取消 deal
        mock_server.deal_repo.find_by_id.assert_called_with("deal_001")
        mock_server.deal_repo.save.assert_called_once()

    def test_multiple_pending_payments_selective_cleanup(self, worker, mock_server):
        """多个 PENDING 支付中，仅超时的被关闭。"""
        import asyncio
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        mock_server.payment_service.repo.find_by_status.return_value = [
            {"payment_id": "pay_001", "deal_id": "deal_001", "created_at": now - timedelta(seconds=600)},  # 超时
            {"payment_id": "pay_002", "deal_id": "deal_002", "created_at": now - timedelta(seconds=60)},   # 未超时
            {"payment_id": "pay_003", "deal_id": "deal_003", "created_at": now - timedelta(seconds=900)},  # 超时
        ]

        # 模拟 deal 状态
        def deal_find_by_id(deal_id):
            from unittest.mock import MagicMock
            deal = MagicMock()
            deal.status = "pending"
            deal.task_id = f"task_{deal_id}"
            return deal
        mock_server.deal_repo.find_by_id.side_effect = deal_find_by_id

        asyncio.run(worker.run({"server": mock_server}))

        # 应只关闭超时的支付
        assert mock_server.payment_service._gateway.close_payment.call_count == 2
        call_args_list = mock_server.payment_service._gateway.close_payment.call_args_list
        called_ids = [call[0][0] for call in call_args_list]
        assert "pay_001" in called_ids
        assert "pay_003" in called_ids
        assert "pay_002" not in called_ids

    def test_skip_deal_not_in_pending(self, worker, mock_server):
        """deal 不在 PENDING 状态时，不应取消 deal。"""
        import asyncio
        from datetime import datetime, timedelta

        created_at = datetime.utcnow() - timedelta(seconds=600)
        mock_server.payment_service.repo.find_by_status.return_value = [
            {"payment_id": "pay_001", "deal_id": "deal_001", "created_at": created_at},
        ]

        # deal 状态为 active
        mock_server.deal_repo.find_by_id.return_value.status = "active"

        asyncio.run(worker.run({"server": mock_server}))

        # 支付应关闭
        mock_server.payment_service._gateway.close_payment.assert_called_once()
        # deal 不应被取消（非 PENDING 状态）
        mock_server.deal_repo.save.assert_not_called()