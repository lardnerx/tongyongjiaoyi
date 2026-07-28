"""测试 L6 数据与智能层：预测、推荐、异常检测。

覆盖 src/umcp_core/layers/l6/intelligence.py 的：
- NoopIntelligenceModule（predict/recommend/detect_anomaly）
- DefaultColdStartStrategy（default_value）
- Prediction / PredictionContext / AnomalyReport 数据类
"""

from __future__ import annotations

from umcp_core.core import DomainTag, Resource, StandardTask
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.layers.l6.intelligence import (
    AnomalyReport,
    ColdStartStrategy,
    DefaultColdStartStrategy,
    IntelligenceModule,
    NoopIntelligenceModule,
    Prediction,
    PredictionContext,
)


# ----------------------------------------------------------------------
# 桩类
# ----------------------------------------------------------------------


class _Task(StandardTask):
    def task_type(self) -> str:
        return "test_standard"


class _Resource(Resource):
    def resource_type(self) -> str:
        return "test_resource"


# ----------------------------------------------------------------------
# Prediction dataclass
# ----------------------------------------------------------------------


class TestPrediction:
    def test_construction_with_required_fields(self):
        pred = Prediction(target="demand", value=10.5)
        assert pred.target == "demand"
        assert pred.value == 10.5
        assert pred.confidence == 1.0  # 默认值
        assert pred.metadata == {}

    def test_construction_with_all_fields(self):
        pred = Prediction(
            target="eta",
            value=300.0,
            confidence=0.85,
            metadata={"model": "xgboost"},
        )
        assert pred.target == "eta"
        assert pred.value == 300.0
        assert pred.confidence == 0.85
        assert pred.metadata == {"model": "xgboost"}

    def test_metadata_defaults_to_empty_dict_per_instance(self):
        """metadata 默认值不应在实例间共享（field(default_factory=dict)。"""
        p1 = Prediction(target="a", value=1.0)
        p2 = Prediction(target="b", value=2.0)
        p1.metadata["k"] = "v"
        assert p2.metadata == {}


# ----------------------------------------------------------------------
# PredictionContext dataclass
# ----------------------------------------------------------------------


class TestPredictionContext:
    def test_construction_with_only_domain(self):
        ctx = PredictionContext(domain="ride")
        assert ctx.domain == "ride"
        assert ctx.location is None
        assert ctx.time_window is None
        assert ctx.extra == {}

    def test_construction_with_all_fields(self):
        ctx = PredictionContext(
            domain="ride",
            location=(39.9, 116.4),
            time_window=(100.0, 200.0),
            extra={"weather": "sunny"},
        )
        assert ctx.domain == "ride"
        assert ctx.location == (39.9, 116.4)
        assert ctx.time_window == (100.0, 200.0)
        assert ctx.extra == {"weather": "sunny"}

    def test_extra_defaults_to_empty_dict_per_instance(self):
        c1 = PredictionContext(domain="a")
        c2 = PredictionContext(domain="b")
        c1.extra["k"] = "v"
        assert c2.extra == {}


# ----------------------------------------------------------------------
# AnomalyReport dataclass
# ----------------------------------------------------------------------


class TestAnomalyReport:
    def test_construction_with_required_fields(self):
        report = AnomalyReport(anomaly_type="price_spike")
        assert report.anomaly_type == "price_spike"
        assert report.severity == "low"  # 默认值
        assert report.description == ""
        assert report.context == {}

    def test_construction_with_all_fields(self):
        report = AnomalyReport(
            anomaly_type="cancellation_burst",
            severity="high",
            description="5 分钟内取消率突增",
            context={"rate": 0.8},
        )
        assert report.anomaly_type == "cancellation_burst"
        assert report.severity == "high"
        assert report.description == "5 分钟内取消率突增"
        assert report.context == {"rate": 0.8}

    def test_context_defaults_to_empty_dict_per_instance(self):
        r1 = AnomalyReport(anomaly_type="a")
        r2 = AnomalyReport(anomaly_type="b")
        r1.context["k"] = "v"
        assert r2.context == {}


# ----------------------------------------------------------------------
# DefaultColdStartStrategy
# ----------------------------------------------------------------------


class TestDefaultColdStartStrategy:
    def test_default_value_for_known_targets(self):
        strategy = DefaultColdStartStrategy()
        assert strategy.default_value("demand") == 1.0
        assert strategy.default_value("price") == 1.0
        assert strategy.default_value("eta") == 600.0

    def test_default_value_for_unknown_target_returns_one(self):
        strategy = DefaultColdStartStrategy()
        assert strategy.default_value("unknown_target") == 1.0

    def test_custom_defaults_override_defaults(self):
        strategy = DefaultColdStartStrategy(defaults={"demand": 5.5, "eta": 100.0})
        assert strategy.default_value("demand") == 5.5
        assert strategy.default_value("eta") == 100.0
        # 自定义 defaults 中未提供的 target 仍回退到 1.0
        assert strategy.default_value("price") == 1.0

    def test_empty_defaults_falls_back_to_one(self):
        strategy = DefaultColdStartStrategy(defaults={})
        assert strategy.default_value("demand") == 1.0
        assert strategy.default_value("anything") == 1.0

    def test_is_cold_start_strategy_subclass(self):
        strategy = DefaultColdStartStrategy()
        assert isinstance(strategy, ColdStartStrategy)


# ----------------------------------------------------------------------
# NoopIntelligenceModule
# ----------------------------------------------------------------------


class TestNoopIntelligenceModule:
    def test_is_intelligence_module_subclass(self):
        module = NoopIntelligenceModule()
        assert isinstance(module, IntelligenceModule)

    def test_predict_returns_cold_start_prediction(self):
        module = NoopIntelligenceModule()
        ctx = PredictionContext(domain="ride")
        pred = module.predict(ctx)
        assert isinstance(pred, Prediction)
        assert pred.target == "ride"
        # domain="ride" 不在默认 defaults 中（默认只有 demand/price/eta），回退 1.0
        assert pred.value == 1.0
        assert pred.confidence == 0.0
        assert pred.metadata == {"cold_start": True}

    def test_predict_with_known_domain_returns_default(self):
        """当 context.domain 命中冷启动默认 target 时返回对应默认值。"""
        module = NoopIntelligenceModule()
        ctx = PredictionContext(domain="eta")
        pred = module.predict(ctx)
        assert pred.target == "eta"
        assert pred.value == 600.0
        assert pred.confidence == 0.0

    def test_predict_uses_injected_cold_start_strategy(self):
        custom_strategy = DefaultColdStartStrategy(defaults={"ride": 9.9})
        module = NoopIntelligenceModule(cold_start=custom_strategy)
        pred = module.predict(PredictionContext(domain="ride"))
        assert pred.value == 9.9

    def test_recommend_returns_pool_copy(self):
        """recommend 返回列表应与输入池内容相同（顺序保留），但是副本。"""
        module = NoopIntelligenceModule()
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        r1 = _Resource(supplier_id="s1", domain_tag=DomainTag.of("ride"))
        r2 = _Resource(supplier_id="s2", domain_tag=DomainTag.of("ride"))
        pool = [r1, r2]
        result = module.recommend(task, pool)
        assert result == pool
        assert result is not pool  # 应是新列表

    def test_recommend_empty_pool(self):
        module = NoopIntelligenceModule()
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert module.recommend(task, []) == []

    def test_detect_anomaly_returns_none(self):
        module = NoopIntelligenceModule()
        event = Event(
            type=EventType.ANOMALY_DETECTED,
            source_layer="L6",
            payload={"suspicious": True},
        )
        assert module.detect_anomaly(event) is None

    def test_default_cold_start_when_none_passed(self):
        """未注入 cold_start 时使用 DefaultColdStartStrategy。"""
        module = NoopIntelligenceModule()
        assert isinstance(module.cold_start, DefaultColdStartStrategy)
