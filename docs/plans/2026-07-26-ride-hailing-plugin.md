# 阶段一网约车行业验证 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把 umcp-core 骨架中的模拟网约车实现提炼为独立可加载的行业插件包 `plugins/ride_hailing/`，跑通完整交易流程，并附可运行 demo，验证核心抽象的正确性。

**架构：** 插件包作为独立 Python 包放在 `umcp-core/plugins/ride_hailing/`，通过 `plugin.json` 声明性配置 + `register_plugin(server)` 钩子完成加载。插件包含 `RideTask`（标准化任务子类）、`DriverResource`（资源子类）、`RideMatchScorer`（按距离评分的匹配器）、haversine 距离工具。交易流程复用 umcp-core 的预置策略（InstantMatch + DynamicPricing + WeightedSumTrustEngine）。

**技术栈：** Python 3.10+，pytest，umcp-core 静态库（src 布局）

---

## 文件结构

本计划涉及创建或修改的文件：

```
umcp-core/
├── pyproject.toml                          # 修改：添加 pytest pythonpath 配置
├── plugins/                                # 新建目录
│   └── ride_hailing/                       # 新建：网约车插件包
│       ├── __init__.py                     # 新建：PLUGIN_MANIFEST + register_plugin 钩子
│       ├── plugin.json                     # 新建：声明性配置（CodeWiki 6.3 节格式）
│       ├── tasks.py                        # 新建：RideTask 标准化任务子类
│       ├── resources.py                    # 新建：DriverResource 资源子类
│       ├── scoring.py                      # 新建：haversine 距离 + RideMatchScorer
│       └── tests/                          # 新建：插件单元测试
│           ├── __init__.py
│           ├── test_tasks.py               # RideTask 测试
│           ├── test_resources.py           # DriverResource 测试
│           ├── test_scoring.py             # 距离与评分器测试
│           └── test_plugin_loading.py      # 插件加载机制测试
├── examples/                               # 新建目录
│   └── ride_hailing_demo.py                # 新建：可运行 demo 脚本
└── tests/                                  # 已有
    └── test_end_to_end_plugin.py           # 新建：基于插件的端到端测试
```

**设计决策：**
- 插件包放在 `plugins/` 而非 `src/` 下，因为它不是核心库的一部分，是行业外延
- `plugin.json` 只声明声明性信息（task_types、match_strategy、access_rule_expression）
- `register_plugin(server)` 钩子负责需要参数的组件创建（payment_schema、trust_engine）
- 距离计算用标准 haversine 公式，不引入外部依赖

---

## 任务 1：配置 pytest 路径与创建插件包骨架

**文件：**
- 修改：`umcp-core/pyproject.toml`
- 创建：`plugins/ride_hailing/__init__.py`（空占位，任务 5 填充）
- 创建：`plugins/ride_hailing/plugin.json`
- 创建：`plugins/ride_hailing/tests/__init__.py`

- [ ] **步骤 1：修改 pyproject.toml 添加 pythonpath 配置**

修改 `umcp-core/pyproject.toml` 的 `[tool.pytest.ini_options]` 节，添加 `pythonpath`：

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "plugins"]
python_files = "test_*.py"
asyncio_mode = "auto"
pythonpath = ["src", "plugins"]
```

- [ ] **步骤 2：创建插件包目录与空 __init__.py**

创建 `plugins/ride_hailing/__init__.py`，内容为占位注释（任务 5 会填充）：

```python
"""网约车行业插件包。"""
```

- [ ] **步骤 3：创建 plugin.json（CodeWiki 6.3 节格式）**

创建 `plugins/ride_hailing/plugin.json`：

```json
{
  "name": "ride-hailing",
  "version": "1.0.0",
  "task_types": ["ride_hailing.tasks.RideTask"],
  "resource_types": ["ride_hailing.resources.DriverResource"],
  "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
  "trust_dimensions": ["punctuality", "cleanliness", "driving_smoothness", "communication"],
  "commission_rate": 0.20,
  "access_rule_expression": "hasCredential('driver_license') && trustScore >= 4.0"
}
```

**说明：** `payment_schema` 和 `trust_engine` 不在 plugin.json 中声明（因为它们需要构造参数），改由 `register_plugin` 钩子手动创建（任务 5）。

- [ ] **步骤 4：创建 tests 包**

创建 `plugins/ride_hailing/tests/__init__.py`（空文件即可）：

```python
"""网约车插件测试包。"""
```

- [ ] **步骤 5：验证 pytest 能发现插件测试目录**

运行：`cd umcp-core ; python -m pytest --collect-only`
预期：无错误，能收集到现有 86 个测试（插件测试尚未编写，暂不出现）

- [ ] **步骤 6：Commit**

```bash
git add pyproject.toml plugins/
git commit -m "feat(ride-hailing): 创建网约车插件包骨架与 plugin.json"
```

---

## 任务 2：实现 RideTask（TDD）

**文件：**
- 创建：`plugins/ride_hailing/tasks.py`
- 创建：`plugins/ride_hailing/tests/test_tasks.py`

**职责：** 网约车行程任务，继承 `StandardTask`，封装起终点、车型、乘客数、预估价等字段。

- [ ] **步骤 1：编写失败的测试**

创建 `plugins/ride_hailing/tests/test_tasks.py`：

```python
"""测试 RideTask。"""

from __future__ import annotations

import pytest

from umcp_core.core import DomainTag, TaskStatus
from umcp_core.core.domain import SpatioTemporalConstraint
from ride_hailing.tasks import RideTask


class TestRideTask:
    def test_create_with_origin_and_destination(self):
        task = RideTask(
            demander_id="u_passenger_1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
        )
        assert task.spatio_temporal is not None
        assert task.spatio_temporal.origin_lat == 39.9042
        assert task.spatio_temporal.origin_lng == 116.4074
        assert task.spatio_temporal.dest_lat == 39.9590
        assert task.spatio_temporal.dest_lng == 116.4518

    def test_default_car_type_is_economy(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        assert task.structured_fields["car_type"] == "economy"

    def test_custom_car_type(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
            car_type="comfort",
        )
        assert task.structured_fields["car_type"] == "comfort"

    def test_default_passenger_count_is_one(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        assert task.structured_fields["passenger_count"] == 1

    def test_has_base_price_for_dynamic_pricing(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        assert task.custom_fields["base_price"] > 0

    def test_task_type_is_ride(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        assert task.task_type() == "ride"

    def test_task_type_name_attribute_for_factory_registration(self):
        """_task_type_name 属性供 UMCPServer._apply_manifest 注册到 TaskFactory。"""
        assert RideTask._task_type_name == "ride"

    def test_publish_transitions_to_matching(self):
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        task.publish()
        assert task.status == TaskStatus.MATCHING

    def test_estimated_distance_calculated(self):
        """行程预估距离应基于起终点自动计算。"""
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,  # 北京天安门
            origin_lng=116.4074,
            dest_lat=39.9590,    # 北京鸟巢
            dest_lng=116.4518,
        )
        # 天安门到鸟巢约 7-8 公里
        assert 5.0 < task.structured_fields["estimated_distance_km"] < 10.0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd umcp-core ; python -m pytest plugins/ride_hailing/tests/test_tasks.py -v`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'ride_hailing.tasks'`

- [ ] **步骤 3：实现 RideTask**

创建 `plugins/ride_hailing/tasks.py`：

```python
"""网约车行程任务。"""

from __future__ import annotations

import math
from typing import Any

from umcp_core.core.domain import DomainTag, SpatioTemporalConstraint
from umcp_core.core.task import StandardTask


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """haversine 公式计算两点间距离（公里）。"""
    r = 6371.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class RideTask(StandardTask):
    """网约车行程任务（标准化任务）。

    封装起终点、车型、乘客数、预估价等字段。
    距离基于起终点自动计算，预估价基于距离 + 车型。
    """

    _task_type_name = "ride"

    BASE_RATE_PER_KM = 2.5  # 每公里基础费率（元）

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        car_type: str = "economy",
        passenger_count: int = 1,
        **kwargs: Any,
    ) -> None:
        spatio = SpatioTemporalConstraint(
            origin_lat=origin_lat,
            origin_lng=origin_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
        )
        super().__init__(demander_id, domain_tag, spatio_temporal=spatio, **kwargs)

        distance_km = _haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
        base_price = round(distance_km * self.BASE_RATE_PER_KM, 2)

        self.structured_fields["car_type"] = car_type
        self.structured_fields["passenger_count"] = passenger_count
        self.structured_fields["estimated_distance_km"] = round(distance_km, 2)

        self.custom_fields["base_price"] = base_price
        self.custom_fields["price"] = base_price

    def task_type(self) -> str:
        return "ride"
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd umcp-core ; python -m pytest plugins/ride_hailing/tests/test_tasks.py -v`
预期：9 个测试全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add plugins/ride_hailing/tasks.py plugins/ride_hailing/tests/test_tasks.py
git commit -m "feat(ride-hailing): 实现 RideTask 标准化任务子类"
```

---

## 任务 3：实现 DriverResource（TDD）

**文件：**
- 创建：`plugins/ride_hailing/resources.py`
- 创建：`plugins/ride_hailing/tests/test_resources.py`

**职责：** 司机资源，继承 `Resource`，封装当前位置、车牌、车型等字段，默认具备 driver_license 能力。

- [ ] **步骤 1：编写失败的测试**

创建 `plugins/ride_hailing/tests/test_resources.py`：

```python
"""测试 DriverResource。"""

from __future__ import annotations

from umcp_core.core import Capability, DomainTag, ResourceStatus
from ride_hailing.resources import DriverResource


class TestDriverResource:
    def test_create_driver_with_location(self):
        driver = DriverResource(
            supplier_id="u_driver_1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.91,
            current_lng=116.41,
        )
        assert driver.metadata["current_lat"] == 39.91
        assert driver.metadata["current_lng"] == 116.41

    def test_default_car_type_is_economy(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert driver.metadata["car_type"] == "economy"

    def test_custom_car_type(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
            car_type="comfort",
        )
        assert driver.metadata["car_type"] == "comfort"

    def test_has_plate_number(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
            plate_number="京A12345",
        )
        assert driver.metadata["plate_number"] == "京A12345"

    def test_default_has_driver_license_capability(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert driver.has_capability("driver_license")

    def test_custom_capabilities_override_default(self):
        extra = [
            Capability(type="certification", name="driver_license", value="C1", verified=True),
            Capability(type="certification", name="vehicle_license", verified=True),
        ]
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
            capabilities=extra,
        )
        assert driver.has_capability("driver_license")
        assert driver.has_capability("vehicle_license")

    def test_register_sets_idle(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert driver.status == ResourceStatus.OFFLINE
        driver.register()
        assert driver.status == ResourceStatus.IDLE
        assert driver.is_available()

    def test_resource_type_is_driver(self):
        driver = DriverResource(
            supplier_id="u1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        assert driver.resource_type() == "driver"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd umcp-core ; python -m pytest plugins/ride_hailing/tests/test_resources.py -v`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'ride_hailing.resources'`

- [ ] **步骤 3：实现 DriverResource**

创建 `plugins/ride_hailing/resources.py`：

```python
"""网约车司机资源。"""

from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Capability, Resource


class DriverResource(Resource):
    """司机资源（可调度单元）。

    封装当前位置、车牌、车型等字段。
    默认具备 driver_license 能力（准入规则要求）。
    """

    def __init__(
        self,
        supplier_id: str,
        domain_tag: DomainTag,
        current_lat: float,
        current_lng: float,
        car_type: str = "economy",
        plate_number: str = "",
        capabilities: list[Capability] | None = None,
        **kwargs: Any,
    ) -> None:
        if capabilities is None:
            capabilities = [
                Capability(
                    type="certification",
                    name="driver_license",
                    value="C1",
                    verified=True,
                ),
            ]
        super().__init__(
            supplier_id,
            domain_tag,
            capabilities=capabilities,
            **kwargs,
        )
        self.metadata["current_lat"] = current_lat
        self.metadata["current_lng"] = current_lng
        self.metadata["car_type"] = car_type
        self.metadata["plate_number"] = plate_number

    def resource_type(self) -> str:
        return "driver"
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd umcp-core ; python -m pytest plugins/ride_hailing/tests/test_resources.py -v`
预期：8 个测试全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add plugins/ride_hailing/resources.py plugins/ride_hailing/tests/test_resources.py
git commit -m "feat(ride-hailing): 实现 DriverResource 资源子类"
```

---

## 任务 4：实现距离工具与匹配评分器（TDD）

**文件：**
- 创建：`plugins/ride_hailing/scoring.py`
- 创建：`plugins/ride_hailing/tests/test_scoring.py`

**职责：** haversine 距离函数 + `RideMatchScorer`（可调用对象，按司机到乘客的距离评分，近者优先）。

**说明：** tasks.py 中已有一个 `_haversine_km` 私有函数，本任务将其提取到 `scoring.py` 作为公共工具，并让 tasks.py 引用它（DRY 原则）。

- [ ] **步骤 1：编写失败的测试**

创建 `plugins/ride_hailing/tests/test_scoring.py`：

```python
"""测试距离计算与匹配评分器。"""

from __future__ import annotations

import pytest

from umcp_core.core import DomainTag
from ride_hailing.resources import DriverResource
from ride_hailing.scoring import RideMatchScorer, haversine_km
from ride_hailing.tasks import RideTask


class TestHaversine:
    def test_same_point_returns_zero(self):
        assert haversine_km(39.9, 116.4, 39.9, 116.4) == 0.0

    def test_beijing_tiananmen_to_birds_nest(self):
        """天安门到鸟巢约 7-8 公里。"""
        dist = haversine_km(39.9042, 116.4074, 39.9590, 116.4518)
        assert 5.0 < dist < 10.0

    def test_distance_is_symmetric(self):
        d1 = haversine_km(39.9, 116.4, 39.95, 116.45)
        d2 = haversine_km(39.95, 116.45, 39.9, 116.4)
        assert abs(d1 - d2) < 0.001

    def test_distance_positive(self):
        assert haversine_km(39.9, 116.4, 40.0, 116.5) > 0


class TestRideMatchScorer:
    def test_closer_driver_scores_higher(self):
        """距离近的司机评分应更高（返回负距离，近者绝对值小，升序排在前）。"""
        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
        )
        close_driver = DriverResource(
            supplier_id="s_close",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.905,   # 非常近
            current_lng=116.408,
        )
        far_driver = DriverResource(
            supplier_id="s_far",
            domain_tag=DomainTag.of("ride"),
            current_lat=40.0,      # 较远
            current_lng=116.5,
        )
        scorer = RideMatchScorer()
        close_score = scorer(task, close_driver)
        far_score = scorer(task, far_driver)
        # 评分是负距离，近者评分更高（更接近 0）
        assert close_score > far_score

    def test_returns_zero_when_task_has_no_location(self):
        """任务无时空约束时返回 0（中性评分）。"""
        from umcp_core.core import StandardTask

        class _NoLocTask(StandardTask):
            def task_type(self) -> str:
                return "test"

        task = _NoLocTask(demander_id="u1", domain_tag=DomainTag.of("ride"))
        driver = DriverResource(
            supplier_id="s1",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.9,
            current_lng=116.4,
        )
        scorer = RideMatchScorer()
        assert scorer(task, driver) == 0.0

    def test_returns_zero_when_driver_has_no_location(self):
        """司机无位置元数据时返回 0。"""
        from umcp_core.core import DomainTag, Resource

        class _NoLocDriver(Resource):
            def resource_type(self) -> str:
                return "driver"

        task = RideTask(
            demander_id="u1",
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9,
            origin_lng=116.4,
            dest_lat=39.95,
            dest_lng=116.45,
        )
        driver = _NoLocDriver(supplier_id="s1", domain_tag=DomainTag.of("ride"))
        scorer = RideMatchScorer()
        assert scorer(task, driver) == 0.0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd umcp-core ; python -m pytest plugins/ride_hailing/tests/test_scoring.py -v`
预期：FAIL，报错 `ImportError: cannot import name 'RideMatchScorer' from 'ride_hailing.scoring'`

- [ ] **步骤 3：实现 scoring.py**

创建 `plugins/ride_hailing/scoring.py`：

```python
"""网约车匹配评分工具。"""

from __future__ import annotations

import math
from typing import Any

from umcp_core.core.resource import Resource
from umcp_core.core.task import Task


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """haversine 公式计算两个经纬度之间的距离（公里）。

    地球半径取 6371 公里。
    """
    r = 6371.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class RideMatchScorer:
    """网约车匹配评分器。

    按司机当前位置到乘客起点的距离评分。
    返回负距离（-distance），使 InstantMatch 升序排列时近者排在前。
    """

    def __call__(self, task: Task, resource: Resource) -> float:
        if task.spatio_temporal is None:
            return 0.0
        if task.spatio_temporal.origin_lat is None or task.spatio_temporal.origin_lng is None:
            return 0.0
        driver_lat = resource.metadata.get("current_lat")
        driver_lng = resource.metadata.get("current_lng")
        if driver_lat is None or driver_lng is None:
            return 0.0
        distance = haversine_km(
            task.spatio_temporal.origin_lat,
            task.spatio_temporal.origin_lng,
            driver_lat,
            driver_lng,
        )
        return -distance
```

- [ ] **步骤 4：重构 tasks.py 引用公共 haversine_km（DRY）**

修改 `plugins/ride_hailing/tasks.py`，删除私有 `_haversine_km` 函数，改为从 `scoring` 模块导入。

将 `tasks.py` 顶部的 import 部分修改为：

```python
"""网约车行程任务。"""

from __future__ import annotations

from typing import Any

from umcp_core.core.domain import DomainTag, SpatioTemporalConstraint
from umcp_core.core.task import StandardTask
from ride_hailing.scoring import haversine_km
```

删除 `tasks.py` 中的 `_haversine_km` 函数定义（从 `def _haversine_km` 到其结尾）。

将 `RideTask.__init__` 中的调用从 `_haversine_km(...)` 改为 `haversine_km(...)`：

```python
        distance_km = haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
```

- [ ] **步骤 5：运行测试验证通过（含回归）**

运行：`cd umcp-core ; python -m pytest plugins/ride_hailing/tests/test_scoring.py plugins/ride_hailing/tests/test_tasks.py -v`
预期：test_scoring 8 个 + test_tasks 9 个全部 PASS（重构未破坏现有功能）

- [ ] **步骤 6：Commit**

```bash
git add plugins/ride_hailing/scoring.py plugins/ride_hailing/tests/test_scoring.py plugins/ride_hailing/tasks.py
git commit -m "feat(ride-hailing): 实现 haversine 距离与 RideMatchScorer 评分器"
```

---

## 任务 5：实现插件 __init__.py 与 register_plugin 钩子

**文件：**
- 修改：`plugins/ride_hailing/__init__.py`

**职责：** 导出 `PLUGIN_MANIFEST` 字典（与 plugin.json 内容一致）和 `register_plugin(server)` 钩子函数。钩子负责创建需要参数的组件（DynamicPricing、WeightedSumTrustEngine）并注入 server。

- [ ] **步骤 1：实现 __init__.py**

修改 `plugins/ride_hailing/__init__.py` 为：

```python
"""网约车行业插件包。

通过 UMCPServer.load_plugin("ride_hailing") 加载。
plugin.json 中的声明性配置由 server._apply_manifest 处理（task_types、match_strategy、access_rule）。
需要构造参数的组件由 register_plugin 钩子手动创建并注入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from umcp_core.server import UMCPServer


# 与 plugin.json 内容一致，供模块路径方式加载使用
PLUGIN_MANIFEST = {
    "name": "ride-hailing",
    "version": "1.0.0",
    "task_types": ["ride_hailing.tasks.RideTask"],
    "resource_types": ["ride_hailing.resources.DriverResource"],
    "match_strategy": "umcp_core.layers.l3.matching.InstantMatch",
    "trust_dimensions": ["punctuality", "cleanliness", "driving_smoothness", "communication"],
    "commission_rate": 0.20,
    "access_rule_expression": "hasCredential('driver_license') && trustScore >= 4.0",
}


def register_plugin(server: "UMCPServer") -> None:
    """插件自定义初始化钩子。

    在 _apply_manifest 之后调用，用于创建需要构造参数的组件：
    - DynamicPricing（需 surge_factor 和 commission_rule）
    - WeightedSumTrustEngine（需 dimensions）
    - InstantMatch（需 scorer，覆盖 _apply_manifest 创建的无参实例）
    """
    from umcp_core.layers.l3 import CredentialFilter, InstantMatch
    from umcp_core.layers.l4 import DynamicPricing, FlatCommissionRule
    from umcp_core.layers.l5 import WeightedSumTrustEngine
    from ride_hailing.scoring import RideMatchScorer

    # 覆盖 match_strategy：注入按距离评分的 scorer 和资质过滤器
    server.set_match_strategy(
        InstantMatch(
            scorer=RideMatchScorer(),
            filters=[CredentialFilter(required_credentials=["driver_license"])],
        )
    )

    # 注入支付模式：动态定价，20% 抽成
    server.set_payment_schema(
        DynamicPricing(
            surge_factor=1.0,
            commission_rule=FlatCommissionRule(rate=PLUGIN_MANIFEST["commission_rate"]),
        )
    )

    # 注入信任引擎：4 维评价
    server.set_trust_engine(
        WeightedSumTrustEngine(dimensions=PLUGIN_MANIFEST["trust_dimensions"])
    )
```

- [ ] **步骤 2：验证模块可被导入**

运行：`cd umcp-core ; python -c "import sys; sys.path.insert(0, 'src'); sys.path.insert(0, 'plugins'); from ride_hailing import PLUGIN_MANIFEST, register_plugin; print(PLUGIN_MANIFEST['name'])"`
预期：输出 `ride-hailing`

- [ ] **步骤 3：Commit**

```bash
git add plugins/ride_hailing/__init__.py
git commit -m "feat(ride-hailing): 实现 PLUGIN_MANIFEST 与 register_plugin 钩子"
```

---

## 任务 6：测试插件加载机制（TDD）

**文件：**
- 创建：`plugins/ride_hailing/tests/test_plugin_loading.py`

**职责：** 验证 `UMCPServer.load_plugin()` 能正确加载网约车插件，且各层组件被正确注入。

- [ ] **步骤 1：编写失败的测试**

创建 `plugins/ride_hailing/tests/test_plugin_loading.py`：

```python
"""测试插件加载机制。"""

from __future__ import annotations

import pytest

from umcp_core.server import UMCPServer


class TestPluginLoading:
    @pytest.fixture
    def server_with_plugin(self) -> UMCPServer:
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.load_plugin("ride_hailing")
        server.start()
        return server

    def test_plugin_appears_in_loaded_list(self, server_with_plugin: UMCPServer):
        plugins = server_with_plugin.plugins
        assert len(plugins) == 1
        assert plugins[0].name == "ride-hailing"
        assert plugins[0].version == "1.0.0"

    def test_task_factory_registered_ride_type(self, server_with_plugin: UMCPServer):
        assert "ride" in server_with_plugin.task_factory._builders

    def test_match_strategy_injected(self, server_with_plugin: UMCPServer):
        from umcp_core.layers.l3 import InstantMatch

        assert isinstance(server_with_plugin.match_strategy, InstantMatch)

    def test_payment_schema_injected(self, server_with_plugin: UMCPServer):
        from umcp_core.layers.l4 import DynamicPricing

        assert isinstance(server_with_plugin.payment_schema, DynamicPricing)

    def test_trust_engine_injected(self, server_with_plugin: UMCPServer):
        from umcp_core.layers.l5 import WeightedSumTrustEngine

        assert isinstance(server_with_plugin.trust_engine, WeightedSumTrustEngine)

    def test_access_rule_injected(self, server_with_plugin: UMCPServer):
        """准入规则应包含 driver_license 要求。"""
        # 准入规则在 _apply_manifest 中通过 ExpressionAccessRule 添加
        # 验证：无 driver_license 的用户应被拒绝
        from umcp_core.core import DomainTag, StandardTask, User

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "ride"

        class _User(User):
            def authenticate(self, credential) -> bool:
                return True

        # 无资质的用户
        user_no_cred = _User(name="alice", metadata={"credentials": [], "trust_score": 5.0})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert not server_with_plugin.rule_engine.check_access(user_no_cred, task)

        # 有资质且信用达标的用户
        user_ok = _User(
            name="bob",
            metadata={"credentials": ["driver_license"], "trust_score": 4.5},
        )
        assert server_with_plugin.rule_engine.check_access(user_ok, task)

    def test_trust_dimensions_configured(self, server_with_plugin: UMCPServer):
        """信任引擎应配置 4 个维度。"""
        profile = server_with_plugin.trust_engine.evaluate("u_test")
        assert "punctuality" in profile.dimension_scores
        assert "cleanliness" in profile.dimension_scores
        assert "driving_smoothness" in profile.dimension_scores
        assert "communication" in profile.dimension_scores

    def test_commission_rate_configured(self, server_with_plugin: UMCPServer):
        """抽成比例应为 20%。"""
        from umcp_core.core import Deal, DomainTag, StandardTask

        class _Task(StandardTask):
            def task_type(self) -> str:
                return "ride"

        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        task.custom_fields["base_price"] = 100.0
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
            final_amount=100.0,
        )
        order = server_with_plugin.payment_schema.calculate(task, deal)
        assert order.commission == 20.0  # 20% of 100
```

- [ ] **步骤 2：运行测试验证通过（plugin.json 已就绪）**

运行：`cd umcp-core ; python -m pytest plugins/ride_hailing/tests/test_plugin_loading.py -v`
预期：8 个测试全部 PASS（因任务 1-5 已实现）

**说明：** 此任务的测试主要是验证性测试，由于前置任务已完成实现，测试应直接通过。若失败，说明前置任务实现有缺陷，需回溯修复。

- [ ] **步骤 3：Commit**

```bash
git add plugins/ride_hailing/tests/test_plugin_loading.py
git commit -m "test(ride-hailing): 验证插件加载机制与组件注入"
```

---

## 任务 7：编写基于插件的端到端测试

**文件：**
- 创建：`tests/test_end_to_end_plugin.py`

**职责：** 验证通过 `load_plugin("ride_hailing")` 加载插件后，能跑通完整交易流程。对应 CodeWiki 6.7 节阶段一验证清单。

- [ ] **步骤 1：编写端到端测试**

创建 `tests/test_end_to_end_plugin.py`：

```python
"""基于插件的端到端测试：通过 load_plugin 加载网约车插件，跑通完整交易流程。

对应 CodeWiki.md 6.7 节阶段一单行业验证清单。
"""

from __future__ import annotations

import pytest

from umcp_core.core import DealStatus, DomainTag, ResourceStatus, TaskStatus
from umcp_core.core.domain import Credential
from umcp_core.events import EventType
from umcp_core.server import UMCPServer
from ride_hailing.resources import DriverResource
from ride_hailing.tasks import RideTask


class TestEndToEndWithPlugin:
    """完整交易流程：认证 → 发单 → 匹配 → 支付 → 评价。"""

    @pytest.fixture
    def server(self) -> UMCPServer:
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.load_plugin("ride_hailing")
        server.start()
        return server

    def test_full_ride_hailing_flow(self, server: UMCPServer):
        # ===== L1 认证 =====
        passenger = server.auth_provider.authenticate(Credential.phone("13800000001"))
        driver_user = server.auth_provider.authenticate(Credential.phone("13900000002"))
        passenger.switch_role("demander")
        driver_user.switch_role("supplier")
        server.user_repo.save(passenger)
        server.user_repo.save(driver_user)

        # ===== L2 资源上线：司机出车 =====
        driver = DriverResource(
            supplier_id=driver_user.user_id,
            domain_tag=DomainTag.of("ride"),
            current_lat=39.905,  # 靠近乘客起点
            current_lng=116.408,
            plate_number="京A12345",
        )
        driver.register()
        server.resource_repo.save(driver)
        assert driver.status == ResourceStatus.IDLE

        # ===== L2 任务发布：乘客发单 =====
        task = RideTask(
            demander_id=passenger.user_id,
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
            title="从天安门到鸟巢",
        )
        task.bind_event_bus(server.event_bus)
        task.publish()
        server.task_repo.save(task)
        assert task.status == TaskStatus.MATCHING
        assert task.custom_fields["base_price"] > 0

        # ===== L3 匹配：系统派单 =====
        candidates = server.resource_repo.find_available(DomainTag.of("ride"))
        assert len(candidates) == 1
        result = server.match_strategy.execute(task, candidates)
        assert result.matched
        assert result.selected_resource_id == driver.resource_id

        task.assign_to(driver.resource_id)
        assert task.status == TaskStatus.ASSIGNED

        # ===== L4 支付：预估 + 托管 =====
        from umcp_core.core import Deal

        deal = Deal(
            task_id=task.task_id,
            resource_id=driver.resource_id,
            demander_id=passenger.user_id,
            supplier_id=driver_user.user_id,
            final_amount=task.custom_fields["base_price"],
        )
        deal.activate()
        server.deal_repo.save(deal)

        order = server.payment_schema.calculate(task, deal)
        assert order.total_amount > 0
        assert order.commission == round(order.total_amount * 0.20, 2)
        server.payment_schema.hold(order)
        from umcp_core.layers.l4 import PaymentStatus

        assert order.status == PaymentStatus.HELD

        # ===== 服务执行与完成 =====
        task.start_execution()
        driver.update_status(ResourceStatus.BUSY)

        task.complete()
        deal.complete()
        server.payment_schema.capture(order)

        assert task.status == TaskStatus.COMPLETED
        assert deal.status == DealStatus.COMPLETED
        assert order.status == PaymentStatus.CAPTURED

        # ===== L5 评价：双方互评 =====
        from umcp_core.layers.l5 import Evaluation

        passenger_eval = Evaluation(
            evaluator_id=passenger.user_id,
            evaluatee_id=driver_user.user_id,
            task_id=task.task_id,
            ratings={
                "punctuality": 5.0,
                "cleanliness": 4.0,
                "driving_smoothness": 5.0,
                "communication": 4.0,
            },
            comment="很顺利",
        )
        server.trust_engine.record_evaluation(passenger_eval)

        driver_profile = server.trust_engine.evaluate(driver_user.user_id)
        assert driver_profile.get_score("punctuality") == 5.0
        assert driver_profile.get_score("cleanliness") == 4.0

        # ===== 事件总线审计 =====
        history = server.event_bus.history()
        event_types = [e.type for e in history]
        assert EventType.TASK_PUBLISHED in event_types
        assert EventType.TASK_ASSIGNED in event_types
        assert EventType.TASK_COMPLETED in event_types

    def test_multiple_drivers_nearest_wins(self, server: UMCPServer):
        """多个司机时，最近的司机应被优先匹配。"""
        passenger = server.auth_provider.authenticate(Credential.phone("13800000001"))
        passenger.switch_role("demander")
        server.user_repo.save(passenger)

        # 三个司机，距离不同
        near_driver = DriverResource(
            supplier_id="s_near",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.905,
            current_lng=116.408,
        )
        mid_driver = DriverResource(
            supplier_id="s_mid",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.92,
            current_lng=116.42,
        )
        far_driver = DriverResource(
            supplier_id="s_far",
            domain_tag=DomainTag.of("ride"),
            current_lat=40.0,
            current_lng=116.5,
        )
        for d in [near_driver, mid_driver, far_driver]:
            d.register()
            server.resource_repo.save(d)

        task = RideTask(
            demander_id=passenger.user_id,
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
        )
        task.publish()

        candidates = server.resource_repo.find_available(DomainTag.of("ride"))
        result = server.match_strategy.execute(task, candidates)

        assert result.matched
        assert result.selected_resource_id == near_driver.resource_id

    def test_driver_without_license_filtered_out(self, server: UMCPServer):
        """无 driver_license 的司机应被过滤。"""
        from umcp_core.core import Capability

        passenger = server.auth_provider.authenticate(Credential.phone("13800000001"))
        passenger.switch_role("demander")

        # 无驾照的司机（不通过 DriverResource 默认构造，手动去掉能力）
        unlicensed_driver = DriverResource(
            supplier_id="s_unlicensed",
            domain_tag=DomainTag.of("ride"),
            current_lat=39.905,
            current_lng=116.408,
            capabilities=[],  # 无任何能力
        )
        unlicensed_driver.register()
        server.resource_repo.save(unlicensed_driver)

        task = RideTask(
            demander_id=passenger.user_id,
            domain_tag=DomainTag.of("ride"),
            origin_lat=39.9042,
            origin_lng=116.4074,
            dest_lat=39.9590,
            dest_lng=116.4518,
        )
        task.publish()

        candidates = server.resource_repo.find_available(DomainTag.of("ride"))
        result = server.match_strategy.execute(task, candidates)

        # 无驾照司机被过滤，匹配失败
        assert not result.matched
```

- [ ] **步骤 2：运行端到端测试**

运行：`cd umcp-core ; python -m pytest tests/test_end_to_end_plugin.py -v`
预期：3 个测试全部 PASS

- [ ] **步骤 3：运行全部测试确保无回归**

运行：`cd umcp-core ; python -m pytest -v`
预期：86（原有）+ 9（test_tasks）+ 8（test_resources）+ 8（test_scoring）+ 8（test_plugin_loading）+ 3（test_end_to_end_plugin）= 122 个测试全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add tests/test_end_to_end_plugin.py
git commit -m "test(ride-hailing): 基于插件的端到端交易流程测试"
```

---

## 任务 8：编写可运行 demo 脚本

**文件：**
- 创建：`examples/ride_hailing_demo.py`

**职责：** 可直接 `python examples/ride_hailing_demo.py` 运行的演示脚本，打印完整交易流程的每一步。

- [ ] **步骤 1：编写 demo 脚本**

创建 `examples/ride_hailing_demo.py`：

```python
"""网约车行业插件 demo。

直接运行：python examples/ride_hailing_demo.py

演示完整交易流程：
1. 加载网约车插件
2. 乘客与司机认证
3. 司机出车
4. 乘客发单（天安门 → 鸟巢）
5. 系统自动匹配最近司机
6. 预估费用并托管
7. 服务完成并扣款
8. 双方互评
9. 打印事件审计日志
"""

from __future__ import annotations

import sys
from pathlib import Path

# 将 src 和 plugins 加入 sys.path，使脚本可独立运行
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "plugins"))

from umcp_core.core import Deal, DealStatus, DomainTag, ResourceStatus, TaskStatus
from umcp_core.core.domain import Credential
from umcp_core.events import EventType
from umcp_core.layers.l4 import PaymentStatus
from umcp_core.layers.l5 import Evaluation
from umcp_core.server import UMCPServer
from ride_hailing.resources import DriverResource
from ride_hailing.tasks import RideTask


def main() -> None:
    print("=" * 60)
    print("UMCP 网约车行业插件 Demo")
    print("=" * 60)

    # 1. 启动服务器并加载插件
    print("\n[1] 启动 UMCP 服务器，加载网约车插件...")
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("ride_hailing")
    server.start()
    print(f"    已加载插件: {[p.name for p in server.plugins]}")

    # 2. 认证
    print("\n[2] 用户认证...")
    passenger = server.auth_provider.authenticate(Credential.phone("13800000001"))
    driver_user = server.auth_provider.authenticate(Credential.phone("13900000002"))
    passenger.switch_role("demander")
    driver_user.switch_role("supplier")
    print(f"    乘客: {passenger.user_id} (角色: demander)")
    print(f"    司机: {driver_user.user_id} (角色: supplier)")
    server.user_repo.save(passenger)
    server.user_repo.save(driver_user)

    # 3. 司机出车
    print("\n[3] 司机出车...")
    driver = DriverResource(
        supplier_id=driver_user.user_id,
        domain_tag=DomainTag.of("ride"),
        current_lat=39.905,
        current_lng=116.408,
        plate_number="京A12345",
        car_type="economy",
    )
    driver.register()
    server.resource_repo.save(driver)
    print(f"    司机资源已上线: {driver.resource_id}")
    print(f"    车牌: {driver.metadata['plate_number']}, 状态: {driver.status}")

    # 4. 乘客发单
    print("\n[4] 乘客发布行程...")
    task = RideTask(
        demander_id=passenger.user_id,
        domain_tag=DomainTag.of("ride"),
        origin_lat=39.9042,
        origin_lng=116.4074,
        dest_lat=39.9590,
        dest_lng=116.4518,
        title="从天安门到鸟巢",
    )
    task.bind_event_bus(server.event_bus)
    task.publish()
    server.task_repo.save(task)
    print(f"    任务 ID: {task.task_id}")
    print(f"    预估距离: {task.structured_fields['estimated_distance_km']} 公里")
    print(f"    预估费用: {task.custom_fields['base_price']} 元")
    print(f"    任务状态: {task.status}")

    # 5. 系统匹配
    print("\n[5] 系统自动匹配...")
    candidates = server.resource_repo.find_available(DomainTag.of("ride"))
    result = server.match_strategy.execute(task, candidates)
    print(f"    候选司机数: {len(candidates)}")
    print(f"    匹配结果: {result.selected_resource_id}")
    task.assign_to(driver.resource_id)
    print(f"    任务状态: {task.status}")

    # 6. 支付
    print("\n[6] 预估费用并托管...")
    deal = Deal(
        task_id=task.task_id,
        resource_id=driver.resource_id,
        demander_id=passenger.user_id,
        supplier_id=driver_user.user_id,
        final_amount=task.custom_fields["base_price"],
    )
    deal.activate()
    server.deal_repo.save(deal)

    order = server.payment_schema.calculate(task, deal)
    print(f"    订单金额: {order.total_amount} 元")
    print(f"    平台抽成: {order.commission} 元 (20%)")
    print(f"    司机所得: {order.supplier_amount} 元")
    server.payment_schema.hold(order)
    print(f"    支付状态: {order.status}")

    # 7. 服务完成
    print("\n[7] 服务执行与完成...")
    task.start_execution()
    driver.update_status(ResourceStatus.BUSY)
    print(f"    任务状态: {task.status}, 司机状态: {driver.status}")

    task.complete()
    deal.complete()
    server.payment_schema.capture(order)
    driver.update_status(ResourceStatus.IDLE)
    print(f"    任务状态: {task.status}")
    print(f"    交易状态: {deal.status}")
    print(f"    支付状态: {order.status}")
    print(f"    司机状态: {driver.status}")

    # 8. 评价
    print("\n[8] 双方互评...")
    eval_passenger_to_driver = Evaluation(
        evaluator_id=passenger.user_id,
        evaluatee_id=driver_user.user_id,
        task_id=task.task_id,
        ratings={
            "punctuality": 5.0,
            "cleanliness": 4.0,
            "driving_smoothness": 5.0,
            "communication": 4.0,
        },
        comment="很顺利",
    )
    server.trust_engine.record_evaluation(eval_passenger_to_driver)

    profile = server.trust_engine.evaluate(driver_user.user_id)
    print(f"    司机信誉画像:")
    for dim, score in profile.dimension_scores.items():
        print(f"      {dim}: {score}")
    print(f"      综合分: {profile.overall_score:.2f}")

    # 9. 事件审计
    print("\n[9] 事件审计日志...")
    history = server.event_bus.history()
    for event in history:
        print(f"    [{event.source_layer}] {event.type.value} | {event.payload}")

    print("\n" + "=" * 60)
    print("Demo 完成。交易流程全部跑通。")
    print("=" * 60)

    server.stop()


if __name__ == "__main__":
    main()
```

- [ ] **步骤 2：运行 demo 验证**

运行：`cd umcp-core ; python examples/ride_hailing_demo.py`
预期：输出 9 个步骤的完整流程，最后打印 "Demo 完成。交易流程全部跑通。"

- [ ] **步骤 3：Commit**

```bash
git add examples/ride_hailing_demo.py
git commit -m "feat(ride-hailing): 添加可运行 demo 脚本"
```

---

## 验收标准

完成全部 8 个任务后，以下验收标准应全部满足：

| # | 验收项 | 验证方式 |
| --- | --- | --- |
| 1 | 插件包结构完整 | `plugins/ride_hailing/` 下有 plugin.json、__init__.py、tasks.py、resources.py、scoring.py |
| 2 | 插件可被 UMCPServer.load_plugin() 加载 | `test_plugin_loading.py` 8 个测试通过 |
| 3 | RideTask 字段正确 | `test_tasks.py` 9 个测试通过 |
| 4 | DriverResource 字段正确 | `test_resources.py` 8 个测试通过 |
| 5 | 距离与评分器工作 | `test_scoring.py` 8 个测试通过 |
| 6 | 端到端交易流程跑通 | `test_end_to_end_plugin.py` 3 个测试通过 |
| 7 | 最近司机优先匹配 | `test_end_to_end_plugin.py::test_multiple_drivers_nearest_wins` 通过 |
| 8 | 无驾照司机被过滤 | `test_end_to_end_plugin.py::test_driver_without_license_filtered_out` 通过 |
| 9 | demo 脚本可独立运行 | `python examples/ride_hailing_demo.py` 输出完整流程 |
| 10 | 全部测试无回归 | `python -m pytest -v` 共 122 个测试全部通过 |

---

## 自检

### 1. 规格覆盖度

对照 CodeWiki 6.7 节阶段一单行业验证清单：

| 验证项 | 对应任务 |
| --- | --- |
| L1 认证 + 角色切换 | 任务 7 端到端测试 |
| L2 任务发布与入库 | 任务 2（RideTask）+ 任务 7（端到端） |
| L2 资源上线与状态流转 | 任务 3（DriverResource）+ 任务 7（端到端） |
| L3 InstantMatch 匹配 | 任务 4（评分器）+ 任务 6（加载）+ 任务 7（端到端） |
| L4 支付托管/扣款/分账 | 任务 7（端到端，20% 抽成验证） |
| L5 双向评价 + 画像更新 | 任务 7（端到端，4 维评价） |
| 事件总线日志完整 | 任务 7（端到端，3 类事件验证） |
| 状态机无非法跳转 | 复用骨架已有测试（test_fsm.py） |

**遗漏：** 无。所有验证项均有对应任务覆盖。

### 2. 占位符扫描

检查计划中是否有"待定"、"TODO"、"类似任务 N"等占位符 —— **无**。每个步骤都包含完整代码。

### 3. 类型一致性

- `RideTask._task_type_name = "ride"` —— 任务 2 定义，任务 6 测试引用，一致
- `DriverResource.metadata["current_lat"]` —— 任务 3 定义，任务 4 评分器引用，一致
- `haversine_km` 函数名 —— 任务 4 定义，任务 2 重构后引用，一致
- `RideMatchScorer` 类名 —— 任务 4 定义，任务 5 引用，一致
- `PLUGIN_MANIFEST` 字典 —— 任务 5 定义，任务 6 通过加载机制间接验证，一致
- `register_plugin` 函数名 —— 任务 5 定义，server.py 已有的钩子调用一致

**发现问题：** 无。
