"""L4 交易与支付层：定价、计费、分账、担保支付。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from umcp_core.core.deal import Deal
from umcp_core.core.task import Task


class PaymentStatus:
    """支付状态枚举。"""

    CREATED = "created"
    HELD = "held"          # 资金冻结
    CAPTURED = "captured"  # 扣款
    REFUNDED = "refunded"  # 退款
    FAILED = "failed"

    ALL: tuple[str, ...] = (CREATED, HELD, CAPTURED, REFUNDED, FAILED)


@dataclass
class PaymentOrder:
    """支付订单。"""

    order_id: str
    deal_id: str
    total_amount: float
    commission: float = 0.0           # 平台抽成
    supplier_amount: float = 0.0      # 供给方实际所得
    status: str = PaymentStatus.CREATED
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def settle_split(self) -> None:
        """根据抽成比例计算分账。"""
        self.supplier_amount = self.total_amount - self.commission


class CommissionRule(ABC):
    """抽成规则接口。"""

    @abstractmethod
    def calculate(self, task: Task, amount: float) -> float:
        """计算平台抽成金额。"""


class FlatCommissionRule(CommissionRule):
    """固定比例抽成。"""

    def __init__(self, rate: float = 0.20) -> None:
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"抽成比例必须在 [0, 1] 区间，得到: {rate}")
        self.rate: float = rate

    def calculate(self, task: Task, amount: float) -> float:
        return round(amount * self.rate, 2)


class RefundPolicy(ABC):
    """退款策略接口。"""

    @abstractmethod
    def is_eligible(self, deal: Deal) -> bool:
        """是否符合退款条件。"""

    @abstractmethod
    def calculate_refund_amount(self, deal: Deal) -> float:
        """计算退款金额。"""


class FullRefundPolicy(RefundPolicy):
    """全额退款策略。"""

    def is_eligible(self, deal: Deal) -> bool:
        return deal.status in ("disputed", "cancelled")

    def calculate_refund_amount(self, deal: Deal) -> float:
        return deal.final_amount or 0.0


class PaymentSchema(ABC):
    """支付模式接口。

    服务流：PAY.hold（冻结资金）→ PAY.capture（扣款）→ PAY.settle（分账）
    """

    @abstractmethod
    def calculate(self, task: Task, deal: Deal) -> PaymentOrder:
        """根据任务与交易计算支付订单。"""

    @abstractmethod
    def hold(self, order: PaymentOrder) -> None:
        """冻结资金。"""

    @abstractmethod
    def capture(self, order: PaymentOrder) -> None:
        """扣款并分账。"""

    @abstractmethod
    def refund(self, order: PaymentOrder) -> None:
        """退款。"""


class FixedPrice(PaymentSchema):
    """一口价模式（预置）。"""

    def __init__(
        self,
        commission_rule: CommissionRule | None = None,
        refund_policy: RefundPolicy | None = None,
    ) -> None:
        self.commission_rule: CommissionRule = commission_rule or FlatCommissionRule()
        self.refund_policy: RefundPolicy = refund_policy or FullRefundPolicy()

    def calculate(self, task: Task, deal: Deal) -> PaymentOrder:
        amount = deal.final_amount or float(task.custom_fields.get("price", 0.0))
        commission = self.commission_rule.calculate(task, amount)
        order = PaymentOrder(
            order_id=f"po_{deal.deal_id}",
            deal_id=deal.deal_id,
            total_amount=amount,
            commission=commission,
        )
        order.settle_split()
        return order

    def hold(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.HELD

    def capture(self, order: PaymentOrder) -> None:
        if order.status != PaymentStatus.HELD:
            raise RuntimeError(f"支付订单状态 {order.status} 不允许扣款")
        order.status = PaymentStatus.CAPTURED

    def refund(self, order: PaymentOrder) -> None:
        if order.status not in (PaymentStatus.HELD, PaymentStatus.CAPTURED):
            raise RuntimeError(f"支付订单状态 {order.status} 不允许退款")
        order.status = PaymentStatus.REFUNDED


class DynamicPricing(PaymentSchema):
    """动态计价模式（预置）。

    支持外部传入调价因子（来自 L6 实时供需预测）。
    """

    def __init__(
        self,
        commission_rule: CommissionRule | None = None,
        refund_policy: RefundPolicy | None = None,
        surge_factor: float = 1.0,
    ) -> None:
        self.commission_rule: CommissionRule = commission_rule or FlatCommissionRule()
        self.refund_policy: RefundPolicy = refund_policy or FullRefundPolicy()
        self.surge_factor: float = surge_factor

    def calculate(self, task: Task, deal: Deal) -> PaymentOrder:
        base = deal.final_amount or float(task.custom_fields.get("base_price", 0.0))
        amount = round(base * self.surge_factor, 2)
        commission = self.commission_rule.calculate(task, amount)
        order = PaymentOrder(
            order_id=f"po_{deal.deal_id}",
            deal_id=deal.deal_id,
            total_amount=amount,
            commission=commission,
            metadata={"base_price": base, "surge_factor": self.surge_factor},
        )
        order.settle_split()
        return order

    def hold(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.HELD

    def capture(self, order: PaymentOrder) -> None:
        if order.status != PaymentStatus.HELD:
            raise RuntimeError(f"支付订单状态 {order.status} 不允许扣款")
        order.status = PaymentStatus.CAPTURED

    def refund(self, order: PaymentOrder) -> None:
        if order.status not in (PaymentStatus.HELD, PaymentStatus.CAPTURED):
            raise RuntimeError(f"支付订单状态 {order.status} 不允许退款")
        order.status = PaymentStatus.REFUNDED


class Prepaid(PaymentSchema):
    """预付费模式（预置）。需方先付费，再服务。"""

    def __init__(self, commission_rule: CommissionRule | None = None) -> None:
        self.commission_rule: CommissionRule = commission_rule or FlatCommissionRule()

    def calculate(self, task: Task, deal: Deal) -> PaymentOrder:
        amount = deal.final_amount or float(task.custom_fields.get("price", 0.0))
        commission = self.commission_rule.calculate(task, amount)
        order = PaymentOrder(
            order_id=f"po_{deal.deal_id}",
            deal_id=deal.deal_id,
            total_amount=amount,
            commission=commission,
        )
        order.settle_split()
        return order

    def hold(self, order: PaymentOrder) -> None:
        # 预付费模式下 hold 等同于直接扣款
        order.status = PaymentStatus.CAPTURED

    def capture(self, order: PaymentOrder) -> None:
        if order.status != PaymentStatus.CAPTURED:
            raise RuntimeError("预付费模式应在 hold 阶段完成扣款")
        # 已扣款，无需重复

    def refund(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.REFUNDED


class Milestone(PaymentSchema):
    """里程碑分期模式（预置）。"""

    def __init__(self, commission_rule: CommissionRule | None = None) -> None:
        self.commission_rule: CommissionRule = commission_rule or FlatCommissionRule()

    def calculate(self, task: Task, deal: Deal) -> PaymentOrder:
        amount = deal.final_amount or float(task.custom_fields.get("total_price", 0.0))
        commission = self.commission_rule.calculate(task, amount)
        order = PaymentOrder(
            order_id=f"po_{deal.deal_id}",
            deal_id=deal.deal_id,
            total_amount=amount,
            commission=commission,
            metadata={"milestones": task.custom_fields.get("milestones", [])},
        )
        order.settle_split()
        return order

    def hold(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.HELD

    def capture(self, order: PaymentOrder) -> None:
        if order.status != PaymentStatus.HELD:
            raise RuntimeError(f"支付订单状态 {order.status} 不允许扣款")
        order.status = PaymentStatus.CAPTURED

    def refund(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.REFUNDED


class Hourly(PaymentSchema):
    """计时模式（预置）。按实际服务时长计费。"""

    def __init__(
        self,
        hourly_rate: float = 0.0,
        commission_rule: CommissionRule | None = None,
    ) -> None:
        self.hourly_rate: float = hourly_rate
        self.commission_rule: CommissionRule = commission_rule or FlatCommissionRule()

    def calculate(self, task: Task, deal: Deal) -> PaymentOrder:
        hours = float(task.custom_fields.get("actual_hours", 0.0))
        rate = self.hourly_rate or float(task.custom_fields.get("hourly_rate", 0.0))
        amount = round(hours * rate, 2)
        commission = self.commission_rule.calculate(task, amount)
        order = PaymentOrder(
            order_id=f"po_{deal.deal_id}",
            deal_id=deal.deal_id,
            total_amount=amount,
            commission=commission,
            metadata={"hours": hours, "rate": rate},
        )
        order.settle_split()
        return order

    def hold(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.HELD

    def capture(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.CAPTURED

    def refund(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.REFUNDED


class InstallmentPayment(PaymentSchema):
    """分期付款模式（预置）。

    支持订金+尾款两期结算：
    - calculate() 返回单个 PaymentOrder，total_amount = 全款
    - deposit_ratio 控制订金比例（如 0.3 = 30% 订金）
    - hold_deposit() 仅托管订金部分
    - capture_deposit() 扣订金
    - capture_balance() 扣尾款（履约完成后）

    PaymentOrder.metadata 扩展：
    - deposit_amount: 订金金额
    - balance_amount: 尾款金额
    - deposit_status: "none" / "held" / "captured"
    - balance_status: "none" / "captured"

    通用性：集采订金尾款、装修分期、外包里程碑付款都可复用。
    """

    def __init__(
        self,
        deposit_ratio: float = 0.3,
        commission_rule: CommissionRule | None = None,
    ) -> None:
        if not 0.0 <= deposit_ratio <= 1.0:
            raise ValueError(f"订金比例必须在 [0, 1] 区间，得到: {deposit_ratio}")
        self.deposit_ratio: float = deposit_ratio
        self.commission_rule: CommissionRule = commission_rule or FlatCommissionRule()

    def calculate(self, task: Task, deal: Deal) -> PaymentOrder:
        amount = deal.final_amount or float(task.custom_fields.get("total_price", 0.0))
        commission = self.commission_rule.calculate(task, amount)
        deposit_amount = round(amount * self.deposit_ratio, 2)
        balance_amount = round(amount - deposit_amount, 2)
        order = PaymentOrder(
            order_id=f"po_{deal.deal_id}",
            deal_id=deal.deal_id,
            total_amount=amount,
            commission=commission,
            metadata={
                "deposit_amount": deposit_amount,
                "balance_amount": balance_amount,
                "deposit_status": "none",
                "balance_status": "none",
            },
        )
        order.settle_split()
        return order

    def hold_deposit(self, order: PaymentOrder) -> None:
        if order.metadata.get("deposit_status") != "none":
            raise RuntimeError(f"订金状态 {order.metadata['deposit_status']} 不允许托管")
        order.metadata["deposit_status"] = "held"
        order.status = PaymentStatus.HELD

    def capture_deposit(self, order: PaymentOrder) -> None:
        if order.metadata.get("deposit_status") != "held":
            raise RuntimeError("订金未托管，无法扣款")
        order.metadata["deposit_status"] = "captured"
        # 订单整体仍保持 HELD，等尾款结算后才 CAPTURED

    def capture_balance(self, order: PaymentOrder) -> None:
        if order.metadata.get("deposit_status") != "captured":
            raise RuntimeError("订金未扣，无法扣尾款")
        if order.metadata.get("balance_status") != "none":
            raise RuntimeError(f"尾款状态 {order.metadata['balance_status']} 不允许扣款")
        order.metadata["balance_status"] = "captured"
        order.status = PaymentStatus.CAPTURED

    # ------------------------------------------------------------------
    # PaymentSchema 抽象方法实现（委托给分期方法）
    # ------------------------------------------------------------------

    def hold(self, order: PaymentOrder) -> None:
        self.hold_deposit(order)

    def capture(self, order: PaymentOrder) -> None:
        if order.metadata.get("deposit_status") == "none":
            self.hold_deposit(order)
        if order.metadata.get("deposit_status") == "held":
            self.capture_deposit(order)
        if order.metadata.get("balance_status") == "none":
            self.capture_balance(order)

    def refund(self, order: PaymentOrder) -> None:
        if order.status not in (PaymentStatus.HELD, PaymentStatus.CAPTURED):
            raise RuntimeError(f"支付订单状态 {order.status} 不允许退款")
        order.status = PaymentStatus.REFUNDED
        order.metadata["deposit_status"] = "refunded"
        order.metadata["balance_status"] = "refunded"
