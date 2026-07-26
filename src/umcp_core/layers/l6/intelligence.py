"""L6 数据与智能层：预测、推荐、异常检测。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from umcp_core.core.resource import Resource
from umcp_core.core.task import Task
from umcp_core.events.bus import Event


@dataclass
class Prediction:
    """预测结果。"""

    target: str  # 预测目标，如 "demand", "eta", "price"
    value: float
    confidence: float = 1.0  # 0.0 ~ 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionContext:
    """预测上下文。"""

    domain: str
    location: tuple[float, float] | None = None
    time_window: tuple[float, float] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnomalyReport:
    """异常报告。"""

    anomaly_type: str
    severity: str = "low"  # low, medium, high
    description: str = ""
    context: dict[str, Any] = field(default_factory=dict)


class ColdStartStrategy(ABC):
    """冷启动策略接口。"""

    @abstractmethod
    def default_value(self, target: str) -> float:
        """返回冷启动默认值。"""


class DefaultColdStartStrategy(ColdStartStrategy):
    """默认冷启动策略。"""

    def __init__(self, defaults: dict[str, float] | None = None) -> None:
        self.defaults: dict[str, float] = defaults or {"demand": 1.0, "price": 1.0, "eta": 600.0}

    def default_value(self, target: str) -> float:
        return self.defaults.get(target, 1.0)


class IntelligenceModule(ABC):
    """智能模块接口（行业可选项，非必选）。

    可选插件，非必选。例如网约车可接入热力图预测和 ETA 模型，
    设计服务可接入技能匹配模型。
    """

    @abstractmethod
    def predict(self, context: PredictionContext) -> Prediction:
        """根据上下文进行预测。"""

    @abstractmethod
    def recommend(self, task: Task, pool: list[Resource]) -> list[Resource]:
        """为任务推荐资源（按推荐度排序）。"""

    @abstractmethod
    def detect_anomaly(self, event: Event) -> AnomalyReport | None:
        """检测事件中的异常。"""


class NoopIntelligenceModule(IntelligenceModule):
    """空实现：不接入任何智能服务时的占位符。"""

    def __init__(self, cold_start: ColdStartStrategy | None = None) -> None:
        self.cold_start: ColdStartStrategy = cold_start or DefaultColdStartStrategy()

    def predict(self, context: PredictionContext) -> Prediction:
        return Prediction(
            target=context.domain,
            value=self.cold_start.default_value(context.domain),
            confidence=0.0,
            metadata={"cold_start": True},
        )

    def recommend(self, task: Task, pool: list[Resource]) -> list[Resource]:
        return list(pool)

    def detect_anomaly(self, event: Event) -> AnomalyReport | None:
        return None
