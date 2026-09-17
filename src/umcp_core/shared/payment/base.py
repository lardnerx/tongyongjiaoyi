"""支付网关抽象接口与数据模型。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PaymentType(str, Enum):
    """支付类型。"""

    DEPOSIT = "deposit"  # 定金
    BALANCE = "balance"  # 尾款
    FULL = "full"  # 全额
    REFUND = "refund"  # 退款


class PaymentStatusEnum(str, Enum):
    """支付状态。"""

    PENDING = "pending"
    PAID = "paid"
    REFUNDED = "refunded"
    FAILED = "failed"


@dataclass
class PaymentIntent:
    """支付意图（创建支付后返回，前端凭此发起支付）。"""

    payment_id: str
    deal_id: str
    amount: float
    payment_type: PaymentType
    currency: str = "CNY"
    client_secret: str = ""
    code_url: str = ""  # 微信支付 Native 二维码 URL
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PaymentStatus:
    """支付状态查询结果。"""

    payment_id: str
    status: PaymentStatusEnum
    trade_no: str
    paid_at: datetime | None = None


@dataclass
class RefundResult:
    """退款结果。"""

    payment_id: str
    success: bool
    refund_amount: float
    trade_no: str = ""
    message: str = ""


class PaymentGateway(ABC):
    """支付网关抽象基类。

    实现方需提供：AlipayGateway / WechatPayGateway / MockGateway。
    """

    @abstractmethod
    def create_payment(
        self, deal_id: str, amount: float, payment_type: PaymentType
    ) -> PaymentIntent:
        """创建支付意图。"""

    @abstractmethod
    def query_payment(self, payment_id: str) -> PaymentStatus:
        """查询支付状态。"""

    @abstractmethod
    def refund(self, payment_id: str, amount: float, reason: str) -> RefundResult:
        """退款。"""

    @abstractmethod
    def handle_callback(self, raw_data: bytes) -> dict:
        """处理第三方回调。"""

    @abstractmethod
    def close_payment(self, payment_id: str) -> bool:
        """关闭订单（取消未支付的订单）。"""
