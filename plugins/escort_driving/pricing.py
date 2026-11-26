"""陪驾行业计价规则。

核心库只提供 ``PaymentSchema`` / ``CommissionRule`` 抽象，具体「车型单价 × 时长、
定金比例、佣金比例」属于行业逻辑，因此放在插件内实现，参数统一从 RuleConfig 读取，
运营可在后台改价而无需改代码。

规则键：
    escort.pricing.car_type_hourly    各车型每小时单价
    escort.pricing.default_hourly_rate 车型缺失时的兜底单价
    escort.pricing.deposit_ratio      定金比例
    escort.pricing.commission_rate    平台佣金比例
"""
from __future__ import annotations

from typing import Any, Callable

from umcp_core.core.deal import Deal
from umcp_core.core.task import Task
from umcp_core.layers.l4.transaction import (
    CommissionRule,
    FlatCommissionRule,
    PaymentOrder,
    PaymentSchema,
    PaymentStatus,
)

DEFAULT_CAR_TYPE_HOURLY: dict[str, float] = {
    "economy": 100.0,
    "professional": 200.0,
    "luxury": 500.0,
    "business": 400.0,
}
DEFAULT_HOURLY_RATE = 80.0
DEFAULT_DEPOSIT_RATIO = 0.3
DEFAULT_COMMISSION_RATE = 0.2


class EscortPaymentSchema(PaymentSchema):
    """陪驾计价：车型单价 × 预定时长，定金与佣金由 RuleConfig 驱动。

    价格在匹配/抢单时一次性锁定到 ``Deal.final_amount``，后续结算复用该金额，
    避免运营改价影响已成交订单。
    """

    def __init__(
        self,
        config_provider: Callable[[], Any] | None = None,
        hourly_rate: float = DEFAULT_HOURLY_RATE,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        deposit_ratio: float = DEFAULT_DEPOSIT_RATIO,
        car_type_rates: dict[str, float] | None = None,
    ) -> None:
        self._config_provider = config_provider
        self._default_hourly_rate = hourly_rate
        self._default_commission_rate = commission_rate
        self._default_deposit_ratio = deposit_ratio
        self._default_car_type_rates = dict(car_type_rates or DEFAULT_CAR_TYPE_HOURLY)

    # ------------------------------------------------------------------
    # 规则读取
    # ------------------------------------------------------------------

    def _config(self) -> Any:
        return self._config_provider() if self._config_provider is not None else None

    def _cfg(self, key: str, default: Any) -> Any:
        config = self._config()
        if config is None:
            return default
        value = config.get(key, default=default)
        return default if value is None else value

    def _commission_rule(self) -> CommissionRule:
        rate = float(
            self._cfg("escort.pricing.commission_rate", self._default_commission_rate)
        )
        return FlatCommissionRule(rate=rate)

    def _resolve_rate(self, task: Task) -> tuple[str, float]:
        """返回 (车型, 每小时单价)。"""
        car_type = str(
            task.structured_fields.get("car_type")
            or task.custom_fields.get("car_type")
            or ""
        )
        rates = self._cfg("escort.pricing.car_type_hourly", self._default_car_type_rates)
        if not isinstance(rates, dict):
            rates = self._default_car_type_rates
        rate = rates.get(car_type)
        if rate is None:
            rate = self._cfg(
                "escort.pricing.default_hourly_rate", self._default_hourly_rate
            )
        return car_type, float(rate)

    @staticmethod
    def _resolve_hours(task: Task) -> float:
        raw = task.structured_fields.get("duration_hours")
        if raw is None:
            raw = task.custom_fields.get("actual_hours", 0.0)
        try:
            return float(raw or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # ------------------------------------------------------------------
    # PaymentSchema
    # ------------------------------------------------------------------

    def calculate(self, task: Task, deal: Deal) -> PaymentOrder:
        car_type, rate = self._resolve_rate(task)
        hours = self._resolve_hours(task)
        amount = (
            round(float(deal.final_amount), 2)
            if deal.final_amount
            else round(rate * hours, 2)
        )
        commission = self._commission_rule().calculate(task, amount)
        deposit_ratio = float(
            self._cfg("escort.pricing.deposit_ratio", self._default_deposit_ratio)
        )
        deposit_amount = round(amount * deposit_ratio, 2)

        order = PaymentOrder(
            order_id=f"po_{deal.deal_id}",
            deal_id=deal.deal_id,
            total_amount=amount,
            commission=commission,
            metadata={
                "pricing": "car_type_hourly",
                "car_type": car_type,
                "rate": rate,
                "hours": hours,
                "deposit_ratio": deposit_ratio,
                "deposit_amount": deposit_amount,
                "balance_amount": round(amount - deposit_amount, 2),
            },
        )
        order.settle_split()
        return order

    def hold(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.HELD

    def capture(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.CAPTURED

    def refund(self, order: PaymentOrder) -> None:
        order.status = PaymentStatus.REFUNDED
