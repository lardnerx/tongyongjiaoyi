# 陪驾 Web 应用 MVP - 阶段一：后端基础设施与业务骨架 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 umcp-core 之上搭建陪驾业务的数据库扩展层、规则配置中心、共享基础设施抽象骨架、陪驾业务后端 router 与 Top3 预约单匹配，产出可被前端调用的最小后端骨架。

**架构：** 复用 umcp-core 的 FastAPI 应用工厂、JWT 认证、EventBus、PostgreSQL 仓储。新增 `src/umcp_core/shared/` 共享层（payment/lbs/notification/storage/rules 抽象 + Mock 实现），新增 `transport/routers/escort/` 与 `transport/routers/platform/` 业务 router 分区，扩展 `plugins/escort_driving/` 支持实时单/预约单双模式与 Top3 推荐。共享层走依赖注入，router 走 `app.state` 装配，所有新增表通过 Alembic 迁移管理。

**技术栈：** Python 3.10+ / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL（含 PostGIS 扩展，迁移中启用）/ Pydantic v2 / pytest

**规格来源：** [docs/specs/2026-07-30-escort-mvp-design.md](file:///c:/trae_projects/tongyongjiaoyi/umcp-core/docs/specs/2026-07-30-escort-mvp-design.md)（章节三/四/五/六/七）

**阶段范围（本计划仅覆盖以下，超出部分由后续计划承接）：**
- 数据库扩展表 + Alembic 迁移（任务 1-2）
- 规则配置中心（任务 3-5）
- 共享基础设施层抽象 + Mock 实现（任务 6-9）
- 陪驾插件扩展：实时单/预约单 + Top3（任务 10-12）
- 陪驾业务 router：下单/接单/签到签退/双向评价（任务 13-16）
- 平台级 router：规则配置管理（任务 17）
- 应用工厂装配与端到端冒烟（任务 18）

不在本计划范围：前端、真实支付/LBS/通知集成、社交好友、信用分计算、教练等级自动升降、E2E 部署。

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `migrations/versions/002_escort_business_tables.py` | 新增 11 张表（coach_profiles/reviews/service_records/friendships/payments/notifications/notification_templates/lbs_locations/files/business_rules/business_rule_history/credit_logs）+ tasks/deals/users 表扩展字段 + DealStatus.IN_SERVICE 状态 |
| `src/umcp_core/shared/__init__.py` | 共享层包入口 |
| `src/umcp_core/shared/rules/__init__.py` | 规则配置包入口 |
| `src/umcp_core/shared/rules/repository.py` | `RuleRepository`（基于 PG session） |
| `src/umcp_core/shared/rules/config.py` | `RuleConfig` 服务（内存缓存 + 变更订阅 + 默认值） |
| `src/umcp_core/shared/rules/models.py` | ORM 模型：`BusinessRuleModel`、`BusinessRuleHistoryModel` |
| `src/umcp_core/shared/payment/__init__.py` | 支付包入口 |
| `src/umcp_core/shared/payment/base.py` | `PaymentGateway` 抽象 + `PaymentIntent`/`PaymentStatus`/`RefundResult` 数据类 + `PaymentType`/`PaymentStatusEnum` 枚举 |
| `src/umcp_core/shared/payment/mock.py` | `MockGateway`（测试用，同步成功） |
| `src/umcp_core/shared/payment/repository.py` | `PaymentRepository` + `PaymentModel` ORM |
| `src/umcp_core/shared/payment/service.py` | `PaymentService`（封装 create/query/refund + 事件发布） |
| `src/umcp_core/shared/lbs/__init__.py` | LBS 包入口 |
| `src/umcp_core/shared/lbs/base.py` | `LBSService` 抽象 |
| `src/umcp_core/shared/lbs/in_memory.py` | `InMemoryLBSService`（开发用，无 PostGIS 依赖） |
| `src/umcp_core/shared/lbs/repository.py` | `LocationRepository` + `LocationModel` ORM（geometry 列） |
| `src/umcp_core/shared/notification/__init__.py` | 通知包入口 |
| `src/umcp_core/shared/notification/base.py` | `NotificationChannel` 抽象 + `Notification` 数据类 |
| `src/umcp_core/shared/notification/ws_channel.py` | `WSNotificationChannel`（复用 umcp-core 的 WS ConnectionManager） |
| `src/umcp_core/shared/notification/center.py` | `NotificationCenter`（多渠道分发 + 模板渲染） |
| `src/umcp_core/shared/notification/repository.py` | `NotificationRepository` + `NotificationModel`/`NotificationTemplateModel` ORM |
| `src/umcp_core/shared/storage/__init__.py` | 存储包入口 |
| `src/umcp_core/shared/storage/base.py` | `FileStorage` 抽象 + `FileMeta` 数据类 |
| `src/umcp_core/shared/storage/local.py` | `LocalStorage`（开发用，写本地磁盘） |
| `src/umcp_core/shared/storage/repository.py` | `FileRepository` + `FileModel` ORM |
| `src/umcp_core/transport/routers/escort/__init__.py` | 陪驾 router 包入口 + `register_escort_routers(app)` |
| `src/umcp_core/transport/routers/escort/orders.py` | 学员下单（实时/预约）、取消、查询 |
| `src/umcp_core/transport/routers/escort/coaches.py` | 教练接单、签到签退、我的订单 |
| `src/umcp_core/transport/routers/escort/reviews.py` | 双向评价（学员评教练 / 教练评学员） |
| `src/umcp_core/transport/routers/platform/__init__.py` | 平台 router 包入口 + `register_platform_routers(app)` |
| `src/umcp_core/transport/routers/platform/rules.py` | 规则配置 CRUD + 历史 + 回滚 |
| `plugins/escort_driving/scheduled_match.py` | `ScheduledMatchStrategy`（预约单 Top3 推荐） |
| `tests/test_rule_config.py` | 规则配置中心测试 |
| `tests/test_payment_service.py` | 支付服务测试（MockGateway） |
| `tests/test_lbs_in_memory.py` | LBS 内存实现测试 |
| `tests/test_notification_center.py` | 通知中心测试 |
| `tests/test_storage_local.py` | 本地存储测试 |
| `tests/test_escort_orders_router.py` | 陪驾下单 router 测试 |
| `tests/test_escort_coaches_router.py` | 陪驾教练 router 测试 |
| `tests/test_escort_reviews_router.py` | 陪驾评价 router 测试 |
| `tests/test_platform_rules_router.py` | 平台规则 router 测试 |
| `tests/test_escort_scheduled_match.py` | 预约单 Top3 匹配测试 |
| `tests/test_escort_mvp_e2e.py` | 端到端冒烟（下单→匹配→签到→签退→双向评价） |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `src/umcp_core/core/deal.py` | `DealStatus` 新增 `IN_SERVICE`，`Deal` 新增 `start_service()`/`check_in()` 方法别名 |
| `src/umcp_core/fsm/deal_fsm.py` | `TRANSITIONS` 增加 `IN_SERVICE` 状态及其转移 |
| `src/umcp_core/events/types.py` | 新增 `DEAL_IN_SERVICE`、`REVIEW_SUBMITTED`、`FRIEND_REQUEST_CREATED`、`FRIEND_REQUEST_ACCEPTED`、`CHECK_IN`/`CHECK_OUT` 事件类型 |
| `src/umcp_core/server.py` | 新增 `set_rule_config`/`set_payment_service`/`set_lbs_service`/`set_notification_center`/`set_file_storage` 方法 + 对应单值属性 |
| `src/umcp_core/transport/app.py` | lifespan 中初始化共享层组件并注入 `app.state`；调用 `register_escort_routers` 和 `register_platform_routers` |
| `src/umcp_core/transport/routers/__init__.py` | 导入并调用 escort/platform 子包注册函数 |
| `src/umcp_core/transport/deps.py` | 新增 `get_rule_config`/`get_payment_service`/`get_lbs_service`/`get_notification_center`/`get_file_storage` 依赖 |
| `src/umcp_core/transport/config.py` | 新增 `shared_layer` 配置段（storage_path/lbs_type/notification_channels 等） |
| `plugins/escort_driving/__init__.py` | `register_plugin` 中注册 `ScheduledMatchStrategy` 到 escort domain |
| `plugins/escort_driving/tasks.py` | `EscortTask` 新增 `order_type`/`scheduled_at`/`coach_level_pref` 字段 |
| `plugins/escort_driving/plugin.json` | 新增 `scheduled_match_strategy` 字段 |
| `pyproject.toml` | `[project.optional-dependencies]` 新增 `escort = ["geoalchemy2>=0.14", "jinja2>=3.1"]`；`dev` 组同步加入 |
| `tests/conftest.py` | 新增 `rule_config`/`payment_service`/`lbs_service`/`notification_center`/`file_storage` fixture；`http_app` fixture 装配共享层 |

---

## 任务列表

### 任务 1：扩展 DealStatus 与 Deal 状态机，新增 IN_SERVICE

**文件：**
- 修改：`src/umcp_core/core/deal.py:11-25`
- 修改：`src/umcp_core/fsm/deal_fsm.py:17-24`
- 测试：`tests/test_fsm.py`（追加用例）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_fsm.py` 末尾追加：

```python
def test_deal_fsm_allows_active_to_in_service():
    from umcp_core.fsm.deal_fsm import DealStateMachine
    sm = DealStateMachine()
    # 不抛异常即通过
    sm.validate_transition("active", "in_service")


def test_deal_fsm_allows_in_service_to_completed():
    from umcp_core.fsm.deal_fsm import DealStateMachine
    sm = DealStateMachine()
    sm.validate_transition("in_service", "completed")


def test_deal_fsm_allows_in_service_to_disputed():
    from umcp_core.fsm.deal_fsm import DealStateMachine
    sm = DealStateMachine()
    sm.validate_transition("in_service", "disputed")


def test_deal_fsm_rejects_pending_to_in_service():
    from umcp_core.fsm.deal_fsm import DealStateMachine
    import pytest
    sm = DealStateMachine()
    with pytest.raises(ValueError):
        sm.validate_transition("pending", "in_service")


def test_deal_start_service_transitions_active_to_in_service():
    from umcp_core.core.deal import Deal, DealStatus
    deal = Deal(task_id="t1", resource_id="r1", demander_id="d1", supplier_id="s1")
    deal.activate()  # PENDING → ACTIVE
    deal.start_service()  # ACTIVE → IN_SERVICE
    assert deal.status == DealStatus.IN_SERVICE


def test_deal_check_in_is_alias_of_start_service():
    from umcp_core.core.deal import Deal, DealStatus
    deal = Deal(task_id="t1", resource_id="r1", demander_id="d1", supplier_id="s1")
    deal.activate()
    deal.check_in()
    assert deal.status == DealStatus.IN_SERVICE
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_fsm.py::test_deal_fsm_allows_active_to_in_service tests/test_fsm.py::test_deal_start_service_transitions_active_to_in_service -v`
预期：FAIL，报错 `ValueError: active → in_service 不是合法的状态转移` 或 `DealStatus.IN_SERVICE` 不存在

- [ ] **步骤 3：扩展 DealStatus 与 Deal 状态机**

修改 `src/umcp_core/core/deal.py:11-25`，在 `DealStatus` 类中新增 `IN_SERVICE`，并把 `start_service`/`check_in` 加入 `Deal` 类。完整修改后的 `DealStatus` 块：

```python
class DealStatus:
    """交易状态枚举。"""

    PENDING = "pending"
    ACTIVE = "active"
    IN_SERVICE = "in_service"
    COMPLETED = "completed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    RESOLVED = "resolved"

    ALL: tuple[str, ...] = (PENDING, ACTIVE, IN_SERVICE, COMPLETED, DISPUTED, CANCELLED, RESOLVED)

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        return status in (cls.COMPLETED, cls.CANCELLED)
```

在 `Deal` 类的 `activate()` 方法后插入：

```python
    def start_service(self) -> None:
        """服务开始（教练签到）。ACTIVE → IN_SERVICE。"""
        self._transition(DealStatus.IN_SERVICE)
        self._emit(self._get_event_type("DEAL_IN_SERVICE"))

    def check_in(self) -> None:
        """签到（start_service 的业务别名）。"""
        self.start_service()
```

修改 `src/umcp_core/fsm/deal_fsm.py:17-24`，`TRANSITIONS` 改为：

```python
    TRANSITIONS: dict[str, set[str]] = {
        DealStatus.PENDING: {DealStatus.ACTIVE, DealStatus.CANCELLED},
        DealStatus.ACTIVE: {DealStatus.IN_SERVICE, DealStatus.COMPLETED, DealStatus.DISPUTED, DealStatus.CANCELLED},
        DealStatus.IN_SERVICE: {DealStatus.COMPLETED, DealStatus.DISPUTED, DealStatus.CANCELLED},
        DealStatus.DISPUTED: {DealStatus.RESOLVED},
        DealStatus.RESOLVED: {DealStatus.COMPLETED, DealStatus.CANCELLED},
        DealStatus.COMPLETED: set(),
        DealStatus.CANCELLED: set(),
    }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_fsm.py -v -k "deal_fsm or deal_start_service or deal_check_in"`
预期：PASS（全部新增用例通过）

- [ ] **步骤 5：运行全量回归测试确认无破坏**

运行：`pytest tests/test_fsm.py tests/test_deals_trust_events.py tests/test_http_e2e.py -v`
预期：PASS（已有用例不受影响）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/core/deal.py src/umcp_core/fsm/deal_fsm.py tests/test_fsm.py
git commit -m "feat(deal): 新增 IN_SERVICE 状态与 start_service/check_in 方法"
```

---

### 任务 2：扩展 EventType 枚举（陪驾 MVP 所需事件）

**文件：**
- 修改：`src/umcp_core/events/types.py:8-56`
- 测试：`tests/test_event_types_extension.py`（追加用例）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_event_types_extension.py` 末尾追加：

```python
def test_event_type_deal_in_service_exists():
    from umcp_core.events.types import EventType
    assert EventType.DEAL_IN_SERVICE.value == "deal.in_service"


def test_event_type_review_submitted_exists():
    from umcp_core.events.types import EventType
    assert EventType.REVIEW_SUBMITTED.value == "review.submitted"


def test_event_type_friend_request_created_exists():
    from umcp_core.events.types import EventType
    assert EventType.FRIEND_REQUEST_CREATED.value == "friend_request.created"


def test_event_type_friend_request_accepted_exists():
    from umcp_core.events.types import EventType
    assert EventType.FRIEND_REQUEST_ACCEPTED.value == "friend_request.accepted"


def test_event_type_check_in_exists():
    from umcp_core.events.types import EventType
    assert EventType.CHECK_IN.value == "check_in"


def test_event_type_check_out_exists():
    from umcp_core.events.types import EventType
    assert EventType.CHECK_OUT.value == "check_out"


def test_event_type_payment_paid_exists():
    from umcp_core.events.types import EventType
    assert EventType.PAYMENT_PAID.value == "payment.paid"


def test_event_type_payment_refunded_exists():
    from umcp_core.events.types import EventType
    assert EventType.PAYMENT_REFUNDED.value == "payment.refunded"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_event_types_extension.py -v -k "deal_in_service or review_submitted or friend or check_in or check_out or payment_paid or payment_refunded"`
预期：FAIL，`AttributeError: DEAL_IN_SERVICE is not a valid EventType`

- [ ] **步骤 3：扩展 EventType 枚举**

修改 `src/umcp_core/events/types.py`，在 `DEAL_RESOLVED = "deal.resolved"` 行后追加：

```python
    DEAL_IN_SERVICE = "deal.in_service"

    # 评价（陪驾 MVP 扩展）
    REVIEW_SUBMITTED = "review.submitted"

    # 好友（陪驾 MVP 扩展）
    FRIEND_REQUEST_CREATED = "friend_request.created"
    FRIEND_REQUEST_ACCEPTED = "friend_request.accepted"

    # 签到签退（陪驾 MVP 扩展）
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"

    # 支付（陪驾 MVP 扩展）
    PAYMENT_PAID = "payment.paid"
    PAYMENT_REFUNDED = "payment.refunded"
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_event_types_extension.py -v`
预期：PASS

- [ ] **步骤 5：运行回归测试**

运行：`pytest tests/test_event_types_extension.py tests/test_events.py tests/test_deals_trust_events.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/events/types.py tests/test_event_types_extension.py
git commit -m "feat(events): 新增陪驾 MVP 所需事件类型"
```

---

### 任务 3：规则配置层 ORM 模型与迁移

**文件：**
- 创建：`src/umcp_core/shared/__init__.py`
- 创建：`src/umcp_core/shared/rules/__init__.py`
- 创建：`src/umcp_core/shared/rules/models.py`
- 创建：`migrations/versions/002_escort_business_tables.py`（本任务只创建规则表部分，其余表在任务 4-9 逐步补充）
- 测试：手动 `alembic upgrade head` 验证

- [ ] **步骤 1：创建 shared 包骨架**

写入 `src/umcp_core/shared/__init__.py`：

```python
"""共享基础设施层：一次建设，多业务复用。"""
```

写入 `src/umcp_core/shared/rules/__init__.py`：

```python
"""规则配置中心。"""

from umcp_core.shared.rules.config import RuleConfig
from umcp_core.shared.rules.repository import RuleRepository

__all__ = ["RuleConfig", "RuleRepository"]
```

- [ ] **步骤 2：创建规则配置 ORM 模型**

写入 `src/umcp_core/shared/rules/models.py`：

```python
"""规则配置 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base


class BusinessRuleModel(Base):
    """业务规则配置表。"""

    __tablename__ = "business_rules"

    rule_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    rule_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BusinessRuleHistoryModel(Base):
    """规则变更历史表。"""

    __tablename__ = "business_rule_history"

    history_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **步骤 3：创建 Alembic 迁移脚本骨架**

写入 `migrations/versions/002_escort_business_tables.py`（本任务先建规则表 + 索引；其余表在后续任务增量追加到同一文件 `upgrade()`/`downgrade()` 中）：

```python
"""陪驾业务扩展表 + 共享基础设施表

Revision ID: 002
Revises: 001
Create Date: 2026-07-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- 规则配置表 ----------
    op.create_table(
        "business_rules",
        sa.Column("rule_key", sa.String(128), primary_key=True),
        sa.Column("rule_value", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_business_rules_category", "business_rules", ["category"])

    op.create_table(
        "business_rule_history",
        sa.Column("history_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_key", sa.String(128), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("changed_by", sa.String(64), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
    )
    op.create_index("idx_rule_history_key", "business_rule_history", ["rule_key"])


def downgrade() -> None:
    op.drop_table("business_rule_history")
    op.drop_table("business_rules")
```

- [ ] **步骤 4：本地验证迁移可执行**

运行：`alembic upgrade head`（需要本地 PG；若无 PG 跳过，依赖 CI 验证）
预期：`Running upgrade 001 -> 002, ...` 无报错

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/shared/__init__.py src/umcp_core/shared/rules/__init__.py src/umcp_core/shared/rules/models.py migrations/versions/002_escort_business_tables.py
git commit -m "feat(rules): 规则配置层 ORM 模型与初始迁移"
```

---

### 任务 4：RuleRepository 实现

**文件：**
- 创建：`src/umcp_core/shared/rules/repository.py`
- 测试：`tests/test_rule_config.py`（先建 fixture 部分）

- [ ] **步骤 1：编写失败的测试**

写入 `tests/test_rule_config.py`：

```python
"""规则配置中心测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def rule_repo():
    """内存版 RuleRepository，便于无 PG 环境测试。"""
    from umcp_core.shared.rules.repository import InMemoryRuleRepository
    return InMemoryRuleRepository()


def test_rule_repo_find_by_key_returns_none_when_absent(rule_repo):
    assert rule_repo.find_by_key("nonexistent") is None


def test_rule_repo_upsert_and_find(rule_repo):
    rule_repo.upsert("escort.cancel.policy", {"window_minutes": 5}, "admin_1", "cancel")
    rule = rule_repo.find_by_key("escort.cancel.policy")
    assert rule is not None
    assert rule["rule_value"] == {"window_minutes": 5}
    assert rule["category"] == "cancel"
    assert rule["version"] == 1


def test_rule_repo_upsert_increments_version(rule_repo):
    rule_repo.upsert("k", {"v": 1}, "admin", "cat")
    rule_repo.upsert("k", {"v": 2}, "admin", "cat")
    rule = rule_repo.find_by_key("k")
    assert rule["rule_value"] == {"v": 2}
    assert rule["version"] == 2


def test_rule_repo_list_by_category(rule_repo):
    rule_repo.upsert("a", {"v": 1}, "admin", "cancel")
    rule_repo.upsert("b", {"v": 2}, "admin", "cancel")
    rule_repo.upsert("c", {"v": 3}, "admin", "coach")
    items = rule_repo.list_by_category("cancel")
    assert len(items) == 2


def test_rule_repo_list_all(rule_repo):
    rule_repo.upsert("a", {}, "admin", "cat")
    rule_repo.upsert("b", {}, "admin", "cat")
    assert len(rule_repo.list_all()) == 2


def test_rule_repo_append_history(rule_repo):
    rule_repo.upsert("k", {"v": 1}, "admin_1", "cat")
    rule_repo.upsert("k", {"v": 2}, "admin_2", "cat", reason="调整参数")
    history = rule_repo.history("k")
    assert len(history) == 2
    assert history[0]["old_value"] is None
    assert history[0]["new_value"] == {"v": 1}
    assert history[1]["old_value"] == {"v": 1}
    assert history[1]["new_value"] == {"v": 2}
    assert history[1]["changed_by"] == "admin_2"
    assert history[1]["change_reason"] == "调整参数"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_rule_config.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.shared.rules.repository'`

- [ ] **步骤 3：实现 RuleRepository（含内存实现）**

写入 `src/umcp_core/shared/rules/repository.py`：

```python
"""规则配置仓储。

提供两套实现：
- InMemoryRuleRepository：开发与测试用
- PostgresRuleRepository：生产用，基于 SQLAlchemy session

仓储接口返回纯 dict（不暴露 ORM 模型），降低上层对 ORM 的耦合。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class RuleRepositoryProtocol(Protocol):
    """规则仓储协议。"""

    def find_by_key(self, rule_key: str) -> dict[str, Any] | None: ...

    def list_all(self) -> list[dict[str, Any]]: ...

    def list_by_category(self, category: str) -> list[dict[str, Any]]: ...

    def upsert(
        self,
        rule_key: str,
        rule_value: dict[str, Any],
        updated_by: str,
        category: str,
        description: str | None = None,
        reason: str | None = None,
    ) -> None: ...

    def history(self, rule_key: str) -> list[dict[str, Any]]: ...


class InMemoryRuleRepository:
    """内存规则仓储（开发与测试用）。"""

    def __init__(self) -> None:
        self._rules: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []

    def find_by_key(self, rule_key: str) -> dict[str, Any] | None:
        rule = self._rules.get(rule_key)
        return dict(rule) if rule else None

    def list_all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rules.values()]

    def list_by_category(self, category: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rules.values() if r["category"] == category]

    def upsert(
        self,
        rule_key: str,
        rule_value: dict[str, Any],
        updated_by: str,
        category: str,
        description: str | None = None,
        reason: str | None = None,
    ) -> None:
        old = self._rules.get(rule_key)
        old_value = old["rule_value"] if old else None
        new_version = (old["version"] + 1) if old else 1
        now = datetime.utcnow()
        self._rules[rule_key] = {
            "rule_key": rule_key,
            "rule_value": dict(rule_value),
            "description": description or (old["description"] if old else None),
            "category": category,
            "version": new_version,
            "updated_by": updated_by,
            "updated_at": now,
        }
        self._history.append(
            {
                "history_id": len(self._history) + 1,
                "rule_key": rule_key,
                "old_value": dict(old_value) if old_value else None,
                "new_value": dict(rule_value),
                "changed_by": updated_by,
                "changed_at": now,
                "change_reason": reason,
            }
        )

    def history(self, rule_key: str) -> list[dict[str, Any]]:
        return [dict(h) for h in self._history if h["rule_key"] == rule_key]


class PostgresRuleRepository:
    """PostgreSQL 规则仓储（生产用）。"""

    def __init__(self, session_factory) -> None:
        """session_factory: SQLAlchemy sessionmaker。"""
        self._session_factory = session_factory

    def find_by_key(self, rule_key: str) -> dict[str, Any] | None:
        from umcp_core.shared.rules.models import BusinessRuleModel

        with self._session_factory() as session:
            m = session.get(BusinessRuleModel, rule_key)
            if m is None:
                return None
            return self._to_dict(m)

    def list_all(self) -> list[dict[str, Any]]:
        from umcp_core.shared.rules.models import BusinessRuleModel

        with self._session_factory() as session:
            rows = session.query(BusinessRuleModel).all()
            return [self._to_dict(m) for m in rows]

    def list_by_category(self, category: str) -> list[dict[str, Any]]:
        from umcp_core.shared.rules.models import BusinessRuleModel

        with self._session_factory() as session:
            rows = session.query(BusinessRuleModel).filter_by(category=category).all()
            return [self._to_dict(m) for m in rows]

    def upsert(
        self,
        rule_key: str,
        rule_value: dict[str, Any],
        updated_by: str,
        category: str,
        description: str | None = None,
        reason: str | None = None,
    ) -> None:
        from umcp_core.shared.rules.models import BusinessRuleHistoryModel, BusinessRuleModel

        with self._session_factory() as session:
            m = session.get(BusinessRuleModel, rule_key)
            old_value = dict(m.rule_value) if m else None
            now = datetime.utcnow()
            if m is None:
                m = BusinessRuleModel(
                    rule_key=rule_key,
                    rule_value=dict(rule_value),
                    description=description,
                    category=category,
                    version=1,
                    updated_by=updated_by,
                    updated_at=now,
                )
                session.add(m)
            else:
                m.rule_value = dict(rule_value)
                m.version = m.version + 1
                m.updated_by = updated_by
                m.updated_at = now
                if description is not None:
                    m.description = description
            session.add(
                BusinessRuleHistoryModel(
                    rule_key=rule_key,
                    old_value=old_value,
                    new_value=dict(rule_value),
                    changed_by=updated_by,
                    changed_at=now,
                    change_reason=reason,
                )
            )
            session.commit()

    def history(self, rule_key: str) -> list[dict[str, Any]]:
        from umcp_core.shared.rules.models import BusinessRuleHistoryModel

        with self._session_factory() as session:
            rows = (
                session.query(BusinessRuleHistoryModel)
                .filter_by(rule_key=rule_key)
                .order_by(BusinessRuleHistoryModel.history_id)
                .all()
            )
            return [
                {
                    "history_id": h.history_id,
                    "rule_key": h.rule_key,
                    "old_value": dict(h.old_value) if h.old_value else None,
                    "new_value": dict(h.new_value) if h.new_value else None,
                    "changed_by": h.changed_by,
                    "changed_at": h.changed_at,
                    "change_reason": h.change_reason,
                }
                for h in rows
            ]

    @staticmethod
    def _to_dict(m) -> dict[str, Any]:
        return {
            "rule_key": m.rule_key,
            "rule_value": dict(m.rule_value) if m.rule_value else {},
            "description": m.description,
            "category": m.category,
            "version": m.version,
            "updated_by": m.updated_by,
            "updated_at": m.updated_at,
        }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_rule_config.py -v`
预期：PASS（6 个用例）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/shared/rules/repository.py tests/test_rule_config.py
git commit -m "feat(rules): RuleRepository 内存与 PG 双实现"
```

---

### 任务 5：RuleConfig 服务（内存缓存 + 默认值 + 订阅）

**文件：**
- 创建：`src/umcp_core/shared/rules/config.py`
- 测试：`tests/test_rule_config.py`（追加用例）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_rule_config.py` 末尾追加：

```python
@pytest.fixture
def rule_config(rule_repo):
    from umcp_core.shared.rules.config import RuleConfig
    return RuleConfig(rule_repo)


def test_rule_config_get_returns_default_when_absent(rule_config):
    assert rule_config.get("nonexistent", default=42) == 42


def test_rule_config_get_returns_value_after_set(rule_config):
    rule_config.set("escort.cancel.policy", {"window": 5}, "admin_1", "cancel")
    assert rule_config.get("escort.cancel.policy") == {"window": 5}


def test_rule_config_get_caches_value(rule_config):
    rule_config.set("k", {"v": 1}, "admin", "cat")
    _ = rule_config.get("k")
    # 直接修改 repo，cache 应仍返回旧值
    rule_config._repo.upsert("k", {"v": 999}, "admin", "cat")
    assert rule_config.get("k") == {"v": 1}


def test_rule_config_reload_refreshes_cache(rule_config):
    rule_config.set("k", {"v": 1}, "admin", "cat")
    _ = rule_config.get("k")
    rule_config._repo.upsert("k", {"v": 999}, "admin", "cat")
    rule_config.reload()
    assert rule_config.get("k") == {"v": 999}


def test_rule_config_subscribe_invokes_callback_on_set(rule_config):
    received = []
    rule_config.subscribe("k", lambda value: received.append(value))
    rule_config.set("k", {"v": 1}, "admin", "cat")
    assert received == [{"v": 1}]
    rule_config.set("k", {"v": 2}, "admin", "cat")
    assert received == [{"v": 1}, {"v": 2}]


def test_rule_config_preload_defaults():
    from umcp_core.shared.rules.config import RuleConfig
    from umcp_core.shared.rules.repository import InMemoryRuleRepository
    rc = RuleConfig(InMemoryRuleRepository())
    rc.set_defaults(
        {
            "escort.coach.level_config": {"levels": ["BRONZE", "SILVER"]},
            "escort.payment.deposit_ratio": 0.3,
        }
    )
    assert rc.get("escort.coach.level_config") == {"levels": ["BRONZE", "SILVER"]}
    assert rc.get("escort.payment.deposit_ratio") == 0.3
    # set_defaults 不覆盖已设置的值
    rc.set("escort.payment.deposit_ratio", 0.5, "admin", "payment")
    rc.set_defaults({"escort.payment.deposit_ratio": 0.3})
    assert rc.get("escort.payment.deposit_ratio") == 0.5
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_rule_config.py -v -k "rule_config"`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.shared.rules.config'`

- [ ] **步骤 3：实现 RuleConfig**

写入 `src/umcp_core/shared/rules/config.py`：

```python
"""规则配置服务（带内存缓存 + 变更订阅 + 默认值预加载）。

业务代码通过 RuleConfig.get(key) 读取规则，避免每次都查库；
运营后台通过 RuleConfig.set(key, value, updated_by, category) 更新规则，
set 会同步到仓储、刷新缓存、通知订阅者。
"""
from __future__ import annotations

from threading import RLock
from typing import Any, Callable

from umcp_core.shared.rules.repository import RuleRepositoryProtocol


class RuleConfig:
    """规则配置服务。"""

    def __init__(self, repo: RuleRepositoryProtocol) -> None:
        self._repo = repo
        self._cache: dict[str, Any] = {}
        self._defaults: dict[str, Any] = {}
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}
        self._lock = RLock()

    def get(self, key: str, default: Any = None) -> Any:
        """读取规则值。优先级：缓存 > 仓储 > 默认值 > default 参数。"""
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            rule = self._repo.find_by_key(key)
            if rule is not None:
                value = rule["rule_value"]
                self._cache[key] = value
                return value
            if key in self._defaults:
                return self._defaults[key]
            return default

    def set(
        self,
        key: str,
        value: Any,
        updated_by: str,
        category: str,
        description: str | None = None,
        reason: str | None = None,
    ) -> None:
        """更新规则值：写库 + 刷新缓存 + 通知订阅者。"""
        with self._lock:
            self._repo.upsert(key, value, updated_by, category, description, reason)
            self._cache[key] = value
            for callback in self._subscribers.get(key, []):
                callback(value)

    def reload(self) -> None:
        """清空缓存，下次 get 重新查库。"""
        with self._lock:
            self._cache.clear()

    def subscribe(self, key: str, callback: Callable[[Any], None]) -> None:
        """订阅指定 key 的变更。"""
        with self._lock:
            self._subscribers.setdefault(key, []).append(callback)

    def set_defaults(self, defaults: dict[str, Any]) -> None:
        """预加载默认值。已通过 set 设置的 key 不被覆盖。"""
        with self._lock:
            for k, v in defaults.items():
                self._defaults.setdefault(k, v)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_rule_config.py -v`
预期：PASS（13 个用例）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/shared/rules/config.py tests/test_rule_config.py
git commit -m "feat(rules): RuleConfig 服务（缓存+订阅+默认值）"
```

---

### 任务 6：支付网关抽象 + MockGateway

**文件：**
- 创建：`src/umcp_core/shared/payment/__init__.py`
- 创建：`src/umcp_core/shared/payment/base.py`
- 创建：`src/umcp_core/shared/payment/mock.py`
- 测试：`tests/test_payment_service.py`（先建网关部分）

- [ ] **步骤 1：编写失败的测试**

写入 `tests/test_payment_service.py`：

```python
"""支付服务测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def mock_gateway():
    from umcp_core.shared.payment.mock import MockGateway
    return MockGateway()


def test_mock_gateway_create_payment_returns_intent(mock_gateway):
    from umcp_core.shared.payment.base import PaymentType
    intent = mock_gateway.create_payment(
        deal_id="deal_1", amount=100.0, payment_type=PaymentType.DEPOSIT
    )
    assert intent.payment_id
    assert intent.amount == 100.0
    assert intent.deal_id == "deal_1"
    assert intent.payment_type == PaymentType.DEPOSIT
    assert intent.client_secret  # 非空


def test_mock_gateway_query_payment_returns_paid(mock_gateway):
    from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
    intent = mock_gateway.create_payment(
        deal_id="deal_1", amount=100.0, payment_type=PaymentType.DEPOSIT
    )
    status = mock_gateway.query_payment(intent.payment_id)
    assert status.status == PaymentStatusEnum.PAID
    assert status.trade_no


def test_mock_gateway_refund_succeeds(mock_gateway):
    from umcp_core.shared.payment.base import PaymentType
    intent = mock_gateway.create_payment(
        deal_id="deal_1", amount=100.0, payment_type=PaymentType.DEPOSIT
    )
    result = mock_gateway.refund(intent.payment_id, amount=50.0, reason="test")
    assert result.success is True
    assert result.refund_amount == 50.0


def test_mock_gateway_handle_callback_returns_result(mock_gateway):
    result = mock_gateway.handle_callback(b"mock_callback_data")
    assert result["status"] == "paid"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_payment_service.py -v -k "mock_gateway"`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.shared.payment'`

- [ ] **步骤 3：实现支付网关抽象与 Mock**

写入 `src/umcp_core/shared/payment/__init__.py`：

```python
"""支付网关抽象层。"""

from umcp_core.shared.payment.base import (
    PaymentGateway,
    PaymentIntent,
    PaymentStatus,
    PaymentStatusEnum,
    PaymentType,
    RefundResult,
)

__all__ = [
    "PaymentGateway",
    "PaymentIntent",
    "PaymentStatus",
    "PaymentStatusEnum",
    "PaymentType",
    "RefundResult",
]
```

写入 `src/umcp_core/shared/payment/base.py`：

```python
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
```

写入 `src/umcp_core/shared/payment/mock.py`：

```python
"""Mock 支付网关（开发与测试用，同步成功）。"""
from __future__ import annotations

import uuid
from datetime import datetime

from umcp_core.shared.payment.base import (
    PaymentGateway,
    PaymentIntent,
    PaymentStatus,
    PaymentStatusEnum,
    PaymentType,
    RefundResult,
)


class MockGateway(PaymentGateway):
    """Mock 网关：所有操作同步成功，用于开发联调。"""

    def __init__(self) -> None:
        self._payments: dict[str, PaymentIntent] = {}
        self._trade_nos: dict[str, str] = {}

    def create_payment(
        self, deal_id: str, amount: float, payment_type: PaymentType
    ) -> PaymentIntent:
        payment_id = f"pay_mock_{uuid.uuid4().hex[:12]}"
        intent = PaymentIntent(
            payment_id=payment_id,
            deal_id=deal_id,
            amount=amount,
            payment_type=payment_type,
            client_secret=f"mock_secret_{payment_id}",
        )
        self._payments[payment_id] = intent
        self._trade_nos[payment_id] = f"mock_trade_{payment_id}"
        return intent

    def query_payment(self, payment_id: str) -> PaymentStatus:
        if payment_id not in self._payments:
            return PaymentStatus(
                payment_id=payment_id,
                status=PaymentStatusEnum.FAILED,
                trade_no="",
            )
        return PaymentStatus(
            payment_id=payment_id,
            status=PaymentStatusEnum.PAID,
            trade_no=self._trade_nos[payment_id],
            paid_at=datetime.utcnow(),
        )

    def refund(self, payment_id: str, amount: float, reason: str) -> RefundResult:
        if payment_id not in self._payments:
            return RefundResult(
                payment_id=payment_id,
                success=False,
                refund_amount=0.0,
                message="支付单不存在",
            )
        return RefundResult(
            payment_id=payment_id,
            success=True,
            refund_amount=amount,
            trade_no=self._trade_nos[payment_id],
            message="mock refund ok",
        )

    def handle_callback(self, raw_data: bytes) -> dict:
        return {"status": "paid", "raw": raw_data.decode("utf-8", errors="ignore")}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_payment_service.py -v -k "mock_gateway"`
预期：PASS（4 个用例）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/shared/payment/ tests/test_payment_service.py
git commit -m "feat(payment): 支付网关抽象与 Mock 实现"
```

---

### 任务 7：PaymentRepository + PaymentModel（ORM 与迁移）

**文件：**
- 创建：`src/umcp_core/shared/payment/repository.py`
- 修改：`migrations/versions/002_escort_business_tables.py`（追加 payments 表）
- 测试：`tests/test_payment_service.py`（追加仓储用例）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_payment_service.py` 追加：

```python
def test_in_memory_payment_repo_save_and_find():
    from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    repo = InMemoryPaymentRepository()
    repo.save(
        payment_id="pay_1",
        deal_id="deal_1",
        user_id="u_1",
        amount=100.0,
        payment_type=PaymentType.DEPOSIT,
        status=PaymentStatusEnum.PAID,
        gateway="MOCK",
        trade_no="t_1",
    )
    p = repo.find_by_id("pay_1")
    assert p is not None
    assert p["payment_id"] == "pay_1"
    assert p["amount"] == 100.0
    assert p["status"] == PaymentStatusEnum.PAID.value


def test_in_memory_payment_repo_find_by_deal():
    from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    repo = InMemoryPaymentRepository()
    repo.save("pay_1", "deal_1", "u_1", 30.0, PaymentType.DEPOSIT, PaymentStatusEnum.PAID, "MOCK", "t_1")
    repo.save("pay_2", "deal_1", "u_1", 70.0, PaymentType.BALANCE, PaymentStatusEnum.PENDING, "MOCK", "t_2")
    items = repo.find_by_deal("deal_1")
    assert len(items) == 2
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_payment_service.py -v -k "in_memory_payment_repo"`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.shared.payment.repository'`

- [ ] **步骤 3：实现 PaymentRepository**

写入 `src/umcp_core/shared/payment/repository.py`：

```python
"""支付记录仓储。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base
from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType


class PaymentModel(Base):
    """支付记录表。"""

    __tablename__ = "payments"

    payment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    gateway: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InMemoryPaymentRepository:
    """内存支付仓储（开发与测试用）。"""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def save(
        self,
        payment_id: str,
        deal_id: str,
        user_id: str,
        amount: float,
        payment_type: PaymentType,
        status: PaymentStatusEnum,
        gateway: str,
        trade_no: str | None = None,
        paid_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._items[payment_id] = {
            "payment_id": payment_id,
            "deal_id": deal_id,
            "user_id": user_id,
            "amount": amount,
            "type": payment_type.value if isinstance(payment_type, PaymentType) else str(payment_type),
            "status": status.value if isinstance(status, PaymentStatusEnum) else str(status),
            "gateway": gateway,
            "trade_no": trade_no,
            "paid_at": paid_at,
            "refunded_at": None,
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
        }

    def find_by_id(self, payment_id: str) -> dict[str, Any] | None:
        item = self._items.get(payment_id)
        return dict(item) if item else None

    def find_by_deal(self, deal_id: str) -> list[dict[str, Any]]:
        return [dict(v) for v in self._items.values() if v["deal_id"] == deal_id]

    def update_status(
        self,
        payment_id: str,
        status: PaymentStatusEnum,
        trade_no: str | None = None,
        paid_at: datetime | None = None,
    ) -> None:
        if payment_id in self._items:
            self._items[payment_id]["status"] = status.value
            if trade_no:
                self._items[payment_id]["trade_no"] = trade_no
            if paid_at:
                self._items[payment_id]["paid_at"] = paid_at


class PostgresPaymentRepository:
    """PG 支付仓储。"""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def save(
        self,
        payment_id: str,
        deal_id: str,
        user_id: str,
        amount: float,
        payment_type: PaymentType,
        status: PaymentStatusEnum,
        gateway: str,
        trade_no: str | None = None,
        paid_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        with self._session_factory() as session:
            m = PaymentModel(
                payment_id=payment_id,
                deal_id=deal_id,
                user_id=user_id,
                amount=amount,
                type=payment_type.value if isinstance(payment_type, PaymentType) else str(payment_type),
                status=status.value if isinstance(status, PaymentStatusEnum) else str(status),
                gateway=gateway,
                trade_no=trade_no,
                paid_at=paid_at,
                metadata_=metadata,
                created_at=datetime.utcnow(),
            )
            session.add(m)
            session.commit()

    def find_by_id(self, payment_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            m = session.get(PaymentModel, payment_id)
            return self._to_dict(m) if m else None

    def find_by_deal(self, deal_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.query(PaymentModel).filter_by(deal_id=deal_id).all()
            return [self._to_dict(m) for m in rows]

    def update_status(
        self,
        payment_id: str,
        status: PaymentStatusEnum,
        trade_no: str | None = None,
        paid_at: datetime | None = None,
    ) -> None:
        with self._session_factory() as session:
            m = session.get(PaymentModel, payment_id)
            if m is None:
                return
            m.status = status.value if isinstance(status, PaymentStatusEnum) else str(status)
            if trade_no:
                m.trade_no = trade_no
            if paid_at:
                m.paid_at = paid_at
            session.commit()

    @staticmethod
    def _to_dict(m: PaymentModel) -> dict[str, Any]:
        return {
            "payment_id": m.payment_id,
            "deal_id": m.deal_id,
            "user_id": m.user_id,
            "amount": float(m.amount),
            "type": m.type,
            "status": m.status,
            "gateway": m.gateway,
            "trade_no": m.trade_no,
            "paid_at": m.paid_at,
            "refunded_at": m.refunded_at,
            "metadata": m.metadata_ or {},
            "created_at": m.created_at,
        }
```

- [ ] **步骤 4：在迁移脚本中追加 payments 表**

修改 `migrations/versions/002_escort_business_tables.py`，在 `upgrade()` 末尾（`business_rule_history` 表之后）追加：

```python
    # ---------- 支付记录表 ----------
    op.create_table(
        "payments",
        sa.Column("payment_id", sa.String(64), primary_key=True),
        sa.Column("deal_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("gateway", sa.String(16), nullable=False),
        sa.Column("trade_no", sa.String(128), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_payments_deal", "payments", ["deal_id"])
    op.create_index("idx_payments_user", "payments", ["user_id", "status"])
```

在 `downgrade()` 开头追加：

```python
    op.drop_table("payments")
```

- [ ] **步骤 5：运行测试验证通过**

运行：`pytest tests/test_payment_service.py -v`
预期：PASS（6 个用例）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/shared/payment/repository.py migrations/versions/002_escort_business_tables.py tests/test_payment_service.py
git commit -m "feat(payment): PaymentRepository 内存与 PG 实现 + payments 表迁移"
```

---

### 任务 8：PaymentService（封装网关 + 仓储 + 事件发布）

**文件：**
- 创建：`src/umcp_core/shared/payment/service.py`
- 测试：`tests/test_payment_service.py`（追加用例）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_payment_service.py` 追加：

```python
@pytest.fixture
def payment_service():
    from umcp_core.events.bus import EventBus
    from umcp_core.shared.payment.mock import MockGateway
    from umcp_core.shared.payment.repository import InMemoryPaymentRepository
    from umcp_core.shared.payment.service import PaymentService
    return PaymentService(
        gateway=MockGateway(),
        repo=InMemoryPaymentRepository(),
        event_bus=EventBus(),
    )


def test_payment_service_create_payment_persists_and_returns_intent(payment_service):
    from umcp_core.shared.payment.base import PaymentType
    intent = payment_service.create_payment(
        deal_id="deal_1",
        user_id="u_1",
        amount=30.0,
        payment_type=PaymentType.DEPOSIT,
    )
    assert intent.payment_id
    persisted = payment_service.repo.find_by_id(intent.payment_id)
    assert persisted is not None
    assert persisted["amount"] == 30.0


def test_payment_service_confirm_payment_updates_status_and_emits_event(payment_service):
    from umcp_core.events.types import EventType
    from umcp_core.shared.payment.base import PaymentType
    received = []
    payment_service._event_bus.subscribe(EventType.PAYMENT_PAID, lambda e: received.append(e))

    intent = payment_service.create_payment("deal_1", "u_1", 30.0, PaymentType.DEPOSIT)
    payment_service.confirm_payment(intent.payment_id, trade_no="trade_x")

    persisted = payment_service.repo.find_by_id(intent.payment_id)
    from umcp_core.shared.payment.base import PaymentStatusEnum
    assert persisted["status"] == PaymentStatusEnum.PAID.value
    assert persisted["trade_no"] == "trade_x"
    assert len(received) == 1
    assert received[0].type == EventType.PAYMENT_PAID
    assert received[0].payload["payment_id"] == intent.payment_id


def test_payment_service_refund_emits_event(payment_service):
    from umcp_core.events.types import EventType
    from umcp_core.shared.payment.base import PaymentType
    refund_events = []
    payment_service._event_bus.subscribe(EventType.PAYMENT_REFUNDED, lambda e: refund_events.append(e))

    intent = payment_service.create_payment("deal_1", "u_1", 100.0, PaymentType.FULL)
    payment_service.confirm_payment(intent.payment_id, trade_no="t1")
    payment_service.refund(intent.payment_id, amount=50.0, reason="test")

    assert len(refund_events) == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_payment_service.py -v -k "payment_service"`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.shared.payment.service'`

- [ ] **步骤 3：实现 PaymentService**

写入 `src/umcp_core/shared/payment/service.py`：

```python
"""支付服务：封装网关调用 + 仓储持久化 + 事件发布。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from umcp_core.events.bus import Event, EventBus
from umcp_core.events.types import EventType
from umcp_core.shared.payment.base import (
    PaymentGateway,
    PaymentIntent,
    PaymentStatusEnum,
    PaymentType,
)
from umcp_core.shared.payment.repository import InMemoryPaymentRepository


class PaymentService:
    """支付服务。

    业务流程：
    1. create_payment：调网关创建意图 + 仓储落 PENDING 记录
    2. confirm_payment：网关查询确认已支付 → 更新仓储为 PAID + 发 PAYMENT_PAID 事件
    3. refund：调网关退款 → 更新仓储 + 发 PAYMENT_REFUNDED 事件
    """

    def __init__(
        self,
        gateway: PaymentGateway,
        repo: InMemoryPaymentRepository,
        event_bus: EventBus,
    ) -> None:
        self._gateway = gateway
        self._repo = repo
        self._event_bus = event_bus

    @property
    def repo(self) -> InMemoryPaymentRepository:
        return self._repo

    def create_payment(
        self,
        deal_id: str,
        user_id: str,
        amount: float,
        payment_type: PaymentType,
    ) -> PaymentIntent:
        """创建支付意图并落 PENDING 记录。"""
        intent = self._gateway.create_payment(deal_id, amount, payment_type)
        self._repo.save(
            payment_id=intent.payment_id,
            deal_id=deal_id,
            user_id=user_id,
            amount=amount,
            payment_type=payment_type,
            status=PaymentStatusEnum.PENDING,
            gateway=type(self._gateway).__name__,
        )
        return intent

    def confirm_payment(
        self,
        payment_id: str,
        trade_no: str | None = None,
    ) -> None:
        """确认支付成功：更新状态为 PAID + 发布事件。"""
        self._repo.update_status(
            payment_id=payment_id,
            status=PaymentStatusEnum.PAID,
            trade_no=trade_no,
            paid_at=datetime.utcnow(),
        )
        persisted = self._repo.find_by_id(payment_id)
        self._event_bus.publish(
            Event(
                type=EventType.PAYMENT_PAID,
                source_layer="SHARED",
                payload={
                    "payment_id": payment_id,
                    "deal_id": persisted["deal_id"] if persisted else None,
                    "user_id": persisted["user_id"] if persisted else None,
                    "amount": persisted["amount"] if persisted else None,
                },
            )
        )

    def refund(self, payment_id: str, amount: float, reason: str) -> None:
        """退款：调网关 + 更新仓储 + 发布事件。"""
        result = self._gateway.refund(payment_id, amount, reason)
        if not result.success:
            raise RuntimeError(f"退款失败: {result.message}")
        self._repo.update_status(payment_id, PaymentStatusEnum.REFUNDED)
        persisted = self._repo.find_by_id(payment_id)
        self._event_bus.publish(
            Event(
                type=EventType.PAYMENT_REFUNDED,
                source_layer="SHARED",
                payload={
                    "payment_id": payment_id,
                    "deal_id": persisted["deal_id"] if persisted else None,
                    "refund_amount": amount,
                    "reason": reason,
                },
            )
        )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_payment_service.py -v`
预期：PASS（9 个用例）

- [ ] **步骤 5：Commit**

```bash
git add src/umcp_core/shared/payment/service.py tests/test_payment_service.py
git commit -m "feat(payment): PaymentService 封装网关+仓储+事件"
```

---

### 任务 9：LBS 抽象 + InMemoryLBSService + LocationRepository

**文件：**
- 创建：`src/umcp_core/shared/lbs/__init__.py`
- 创建：`src/umcp_core/shared/lbs/base.py`
- 创建：`src/umcp_core/shared/lbs/in_memory.py`
- 创建：`src/umcp_core/shared/lbs/repository.py`
- 修改：`migrations/versions/002_escort_business_tables.py`（追加 lbs_locations 表）
- 测试：`tests/test_lbs_in_memory.py`

- [ ] **步骤 1：编写失败的测试**

写入 `tests/test_lbs_in_memory.py`：

```python
"""LBS 内存实现测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def lbs():
    from umcp_core.shared.lbs.in_memory import InMemoryLBSService
    return InMemoryLBSService()


def test_lbs_update_location_stores_latest(lbs):
    lbs.update_location("res_1", lat=39.9042, lng=116.4074, heading=90.0, speed=30.0)
    loc = lbs.get_location("res_1")
    assert loc is not None
    assert loc["lat"] == 39.9042
    assert loc["lng"] == 116.4074
    assert loc["heading"] == 90.0


def test_lbs_nearby_returns_sorted_by_distance(lbs):
    lbs.update_location("res_1", lat=39.9042, lng=116.4074)
    lbs.update_location("res_2", lat=39.9050, lng=116.4080)  # 更近
    lbs.update_location("res_3", lat=40.0000, lng=117.0000)  # 很远
    result = lbs.nearby(lat=39.9042, lng=116.4074, radius_km=10.0)
    resource_ids = [r["resource_id"] for r in result]
    assert "res_1" in resource_ids
    assert "res_2" in resource_ids
    assert "res_3" not in resource_ids
    # 距离升序
    assert result[0]["distance_km"] <= result[1]["distance_km"]


def test_lbs_nearby_respects_radius(lbs):
    lbs.update_location("res_1", lat=39.9042, lng=116.4074)
    lbs.update_location("res_2", lat=40.0000, lng=117.0000)
    result = lbs.nearby(lat=39.9042, lng=116.4074, radius_km=1.0)
    assert len(result) == 1
    assert result[0]["resource_id"] == "res_1"


def test_lbs_distance_returns_meters(lbs):
    d = lbs.distance(39.9042, 116.4074, 39.9050, 116.4080)
    assert d > 0
    assert d < 1.0  # 很近的两个点


def test_lbs_get_location_returns_none_when_absent(lbs):
    assert lbs.get_location("nonexistent") is None
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_lbs_in_memory.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.shared.lbs'`

- [ ] **步骤 3：实现 LBS 抽象与内存实现**

写入 `src/umcp_core/shared/lbs/__init__.py`：

```python
"""LBS 定位服务。"""

from umcp_core.shared.lbs.base import LBSService, LocationInfo

__all__ = ["LBSService", "LocationInfo"]
```

写入 `src/umcp_core/shared/lbs/base.py`：

```python
"""LBS 服务抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LocationInfo:
    """资源位置信息。"""

    resource_id: str
    lat: float
    lng: float
    heading: float = 0.0
    speed: float = 0.0
    updated_at: Any = None  # datetime，避免导入


class LBSService(ABC):
    """LBS 服务抽象基类。"""

    @abstractmethod
    def update_location(
        self, resource_id: str, lat: float, lng: float, heading: float = 0.0, speed: float = 0.0
    ) -> None:
        """更新资源位置。"""

    @abstractmethod
    def get_location(self, resource_id: str) -> dict[str, Any] | None:
        """查询资源最新位置。"""

    @abstractmethod
    def nearby(
        self, lat: float, lng: float, radius_km: float, level: str | None = None
    ) -> list[dict[str, Any]]:
        """查询附近资源，返回按距离升序排列的列表。"""

    @abstractmethod
    def distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """计算两点间距离（公里）。"""
```

写入 `src/umcp_core/shared/lbs/in_memory.py`：

```python
"""内存 LBS 实现（开发与测试用，基于 haversine 公式）。"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from umcp_core.shared.lbs.base import LBSService

_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """haversine 公式计算球面距离（公里）。"""
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class InMemoryLBSService(LBSService):
    """内存 LBS 服务。"""

    def __init__(self) -> None:
        self._locations: dict[str, dict[str, Any]] = {}

    def update_location(
        self, resource_id: str, lat: float, lng: float, heading: float = 0.0, speed: float = 0.0
    ) -> None:
        self._locations[resource_id] = {
            "resource_id": resource_id,
            "lat": lat,
            "lng": lng,
            "heading": heading,
            "speed": speed,
            "updated_at": datetime.utcnow(),
        }

    def get_location(self, resource_id: str) -> dict[str, Any] | None:
        loc = self._locations.get(resource_id)
        return dict(loc) if loc else None

    def nearby(
        self, lat: float, lng: float, radius_km: float, level: str | None = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for loc in self._locations.values():
            d = _haversine_km(lat, lng, loc["lat"], loc["lng"])
            if d <= radius_km:
                results.append({**loc, "distance_km": d})
        results.sort(key=lambda x: x["distance_km"])
        return results

    def distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        return _haversine_km(lat1, lng1, lat2, lng2)
```

写入 `src/umcp_core/shared/lbs/repository.py`：

```python
"""位置信息仓储（PostGIS）。

注：实际 PostGIS 实现需要 geoalchemy2，本计划阶段先用内存 LBS，
PostGIS 仓储骨架在此占位以便后续计划接入。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base


class LocationModel(Base):
    """位置信息表（PostGIS geometry 列在迁移中用 raw SQL 创建）。"""

    __tablename__ = "lbs_locations"

    location_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # 注意：geometry 列需在迁移中用 SELECT AddGeometryColumn 创建，
    # 这里不映射为 ORM 属性，仅作占位
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

- [ ] **步骤 4：在迁移脚本中追加 lbs_locations 表**

修改 `migrations/versions/002_escort_business_tables.py`，在 `upgrade()` 末尾追加（PostGIS 扩展 + geometry 列）：

```python
    # ---------- LBS 位置表（PostGIS）----------
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "lbs_locations",
        sa.Column("location_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("heading", sa.Float(), nullable=True),
        sa.Column("speed", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.execute("SELECT AddGeometryColumn('lbs_locations', 'location', 4326, 'POINT', 2)")
    op.execute("CREATE INDEX idx_lbs_locations_geom ON lbs_locations USING GIST (location)")
    op.create_index("idx_lbs_locations_resource", "lbs_locations", ["resource_id"])
```

在 `downgrade()` 中追加（在 `op.drop_table("payments")` 之前）：

```python
    op.drop_table("lbs_locations")
```

- [ ] **步骤 5：运行测试验证通过**

运行：`pytest tests/test_lbs_in_memory.py -v`
预期：PASS（5 个用例）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/shared/lbs/ migrations/versions/002_escort_business_tables.py tests/test_lbs_in_memory.py
git commit -m "feat(lbs): LBS 抽象 + 内存实现 + PostGIS 迁移骨架"
```

---

### 任务 10：通知中心（抽象 + WS 渠道 + 多渠道分发）

**文件：**
- 创建：`src/umcp_core/shared/notification/__init__.py`
- 创建：`src/umcp_core/shared/notification/base.py`
- 创建：`src/umcp_core/shared/notification/ws_channel.py`
- 创建：`src/umcp_core/shared/notification/center.py`
- 创建：`src/umcp_core/shared/notification/repository.py`
- 修改：`migrations/versions/002_escort_business_tables.py`（追加 notifications/notification_templates 表）
- 测试：`tests/test_notification_center.py`

- [ ] **步骤 1：编写失败的测试**

写入 `tests/test_notification_center.py`：

```python
"""通知中心测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def notification_center():
    from umcp_core.shared.notification.center import NotificationCenter
    from umcp_core.shared.notification.ws_channel import WSNotificationChannel
    center = NotificationCenter()
    center.register_channel("WS_PUSH", WSNotificationChannel(ws_manager=_FakeWSManager()))
    return center


class _FakeWSManager:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_to_user(self, user_id: str, message: dict) -> None:
        self.sent.append({"user_id": user_id, "message": message})


def test_notification_center_notify_dispatches_to_registered_channel(notification_center):
    import asyncio
    received = []

    notification_center.register_channel("IN_APP", lambda user_id, payload: received.append((user_id, payload)))
    notification_center.notify(
        user_id="u_1",
        event_type="DEAL_CREATED",
        channels=["WS_PUSH", "IN_APP"],
        params={"deal_id": "d_1"},
    )
    # IN_APP 是同步 lambda
    assert ("u_1", {"deal_id": "d_1"}) in received


def test_notification_center_notify_skips_unregistered_channels(notification_center):
    # 只注册了 WS_PUSH，IN_APP 未注册时不抛异常
    notification_center.notify(
        user_id="u_1",
        event_type="DEAL_CREATED",
        channels=["WS_PUSH", "UNKNOWN_CHANNEL"],
        params={"deal_id": "d_1"},
    )
    # 不抛异常即通过


def test_notification_center_notify_both(notification_center):
    received = []
    notification_center.register_channel("IN_APP", lambda user_id, payload: received.append(user_id))
    notification_center.notify_both(
        user_id_a="student_1",
        user_id_b="coach_1",
        event_type="DEAL_CONFIRMED",
        channels=["IN_APP"],
        params={"deal_id": "d_1"},
    )
    assert "student_1" in received
    assert "coach_1" in received
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_notification_center.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.shared.notification'`

- [ ] **步骤 3：实现通知中心**

写入 `src/umcp_core/shared/notification/__init__.py`：

```python
"""消息通知中心。"""

from umcp_core.shared.notification.base import Notification, NotificationChannel
from umcp_core.shared.notification.center import NotificationCenter

__all__ = ["Notification", "NotificationChannel", "NotificationCenter"]
```

写入 `src/umcp_core/shared/notification/base.py`：

```python
"""通知抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class Notification:
    """通知实体。"""

    user_id: str
    event_type: str
    title: str
    body: str
    channels: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class NotificationChannel(ABC):
    """通知渠道抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """渠道名（如 WS_PUSH / SMS / IN_APP）。"""

    @abstractmethod
    def send(self, user_id: str, notification: Notification) -> None:
        """发送通知。"""


class FunctionChannel(NotificationChannel):
    """函数式渠道（测试与 IN_APP 用）。"""

    def __init__(self, channel_name: str, func: Callable[[str, "Notification"], None]) -> None:
        self._name = channel_name
        self._func = func

    @property
    def name(self) -> str:
        return self._name

    def send(self, user_id: str, notification: Notification) -> None:
        self._func(user_id, notification)
```

写入 `src/umcp_core/shared/notification/ws_channel.py`：

```python
"""WebSocket 通知渠道（复用 umcp-core 的 ConnectionManager）。"""
from __future__ import annotations

import asyncio
from typing import Any

from umcp_core.shared.notification.base import NotificationChannel, Notification


class WSNotificationChannel(NotificationChannel):
    """WebSocket 推送渠道。

    依赖 umcp-core 的 transport.ws.ConnectionManager，
    通过 send_to_user 推送消息给在线用户。
    """

    def __init__(self, ws_manager: Any) -> None:
        self._ws_manager = ws_manager

    @property
    def name(self) -> str:
        return "WS_PUSH"

    def send(self, user_id: str, notification: Notification) -> None:
        message = {
            "type": "notification",
            "event_type": notification.event_type,
            "title": notification.title,
            "body": notification.body,
            "params": notification.params,
        }
        # ConnectionManager.send_to_user 是 async，用 ensure_future 触发
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._ws_manager.send_to_user(user_id, message))
            else:
                loop.run_until_complete(self._ws_manager.send_to_user(user_id, message))
        except RuntimeError:
            # 无事件循环，跳过（开发期可接受）
            pass
```

写入 `src/umcp_core/shared/notification/center.py`：

```python
"""通知中心：多渠道分发 + 模板渲染。"""
from __future__ import annotations

from typing import Any, Callable

from umcp_core.shared.notification.base import FunctionChannel, Notification, NotificationChannel


class NotificationCenter:
    """通知中心。

    - register_channel：注册渠道
    - notify：向单个用户多渠道分发
    - notify_both：向双方分发（如学员+教练）
    """

    def __init__(self) -> None:
        self._channels: dict[str, NotificationChannel] = {}
        self._templates: dict[str, dict[str, Any]] = {}

    def register_channel(self, name: str, channel: NotificationChannel | Callable) -> None:
        """注册渠道。channel 可为 NotificationChannel 实例或同步函数。"""
        if isinstance(channel, NotificationChannel):
            self._channels[name] = channel
        else:
            self._channels[name] = FunctionChannel(name, channel)

    def register_template(self, event_type: str, title_template: str, body_template: str) -> None:
        """注册通知模板。"""
        self._templates[event_type] = {"title": title_template, "body": body_template}

    def notify(
        self,
        user_id: str,
        event_type: str,
        channels: list[str],
        params: dict[str, Any],
        title: str | None = None,
        body: str | None = None,
    ) -> Notification:
        """向单个用户分发通知。"""
        tpl = self._templates.get(event_type, {})
        notification = Notification(
            user_id=user_id,
            event_type=event_type,
            title=title or tpl.get("title", event_type),
            body=body or tpl.get("body", ""),
            channels=list(channels),
            params=dict(params),
        )
        for ch_name in channels:
            channel = self._channels.get(ch_name)
            if channel is None:
                continue  # 未注册的渠道静默跳过
            channel.send(user_id, notification)
        return notification

    def notify_both(
        self,
        user_id_a: str,
        user_id_b: str,
        event_type: str,
        channels: list[str],
        params: dict[str, Any],
    ) -> tuple[Notification, Notification]:
        """向双方分发通知。"""
        n_a = self.notify(user_id_a, event_type, channels, params)
        n_b = self.notify(user_id_b, event_type, channels, params)
        return n_a, n_b
```

写入 `src/umcp_core/shared/notification/repository.py`：

```python
"""通知仓储 ORM 模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base


class NotificationModel(Base):
    """站内通知表。"""

    __tablename__ = "notifications"

    notification_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class NotificationTemplateModel(Base):
    """通知模板表（后台可配置）。"""

    __tablename__ = "notification_templates"

    template_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(32), nullable=False)
    channels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    title_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

- [ ] **步骤 4：在迁移脚本中追加通知表**

修改 `migrations/versions/002_escort_business_tables.py`，在 `upgrade()` 末尾追加：

```python
    # ---------- 通知表 ----------
    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("channels", postgresql.JSONB(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_notifications_user", "notifications", ["user_id", "read_at"])

    op.create_table(
        "notification_templates",
        sa.Column("template_key", sa.String(128), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("recipient_role", sa.String(32), nullable=False),
        sa.Column("channels", postgresql.JSONB(), nullable=True),
        sa.Column("title_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
```

在 `downgrade()` 中追加（在 `op.drop_table("lbs_locations")` 之前）：

```python
    op.drop_table("notification_templates")
    op.drop_table("notifications")
```

- [ ] **步骤 5：运行测试验证通过**

运行：`pytest tests/test_notification_center.py -v`
预期：PASS（3 个用例）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/shared/notification/ migrations/versions/002_escort_business_tables.py tests/test_notification_center.py
git commit -m "feat(notification): 通知中心 + WS 渠道 + 模板表迁移"
```

---

### 任务 11：文件存储抽象 + LocalStorage + FileRepository

**文件：**
- 创建：`src/umcp_core/shared/storage/__init__.py`
- 创建：`src/umcp_core/shared/storage/base.py`
- 创建：`src/umcp_core/shared/storage/local.py`
- 创建：`src/umcp_core/shared/storage/repository.py`
- 修改：`migrations/versions/002_escort_business_tables.py`（追加 files 表）
- 测试：`tests/test_storage_local.py`

- [ ] **步骤 1：编写失败的测试**

写入 `tests/test_storage_local.py`：

```python
"""本地文件存储测试。"""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture
def storage():
    from umcp_core.shared.storage.local import LocalStorage
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield LocalStorage(root_dir=tmp_dir)


def test_storage_upload_returns_file_meta(storage):
    meta = storage.upload(
        content=b"hello",
        filename="test.txt",
        uploader_id="u_1",
        file_type="AVATAR",
        biz_type="user",
        biz_id="u_1",
        mime="text/plain",
    )
    assert meta.file_id
    assert meta.filename == "test.txt"
    assert meta.size == 5
    assert meta.mime == "text/plain"


def test_storage_download_returns_content(storage):
    meta = storage.upload(b"hello", "test.txt", "u_1", "AVATAR", "user", "u_1", "text/plain")
    content = storage.download(meta.file_id)
    assert content == b"hello"


def test_storage_delete_removes_file(storage):
    meta = storage.upload(b"hello", "test.txt", "u_1", "AVATAR", "user", "u_1", "text/plain")
    storage.delete(meta.file_id)
    assert storage.download(meta.file_id) is None


def test_storage_get_signed_url_returns_path(storage):
    meta = storage.upload(b"hello", "test.txt", "u_1", "AVATAR", "user", "u_1", "text/plain")
    url = storage.get_signed_url(meta.file_id, expire_sec=3600)
    assert url  # 非空
    assert meta.file_id in url or "test" in url
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_storage_local.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'umcp_core.shared.storage'`

- [ ] **步骤 3：实现文件存储**

写入 `src/umcp_core/shared/storage/__init__.py`：

```python
"""文件存储抽象层。"""

from umcp_core.shared.storage.base import FileMeta, FileStorage

__all__ = ["FileMeta", "FileStorage"]
```

写入 `src/umcp_core/shared/storage/base.py`：

```python
"""文件存储抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileMeta:
    """文件元信息。"""

    file_id: str
    uploader_id: str
    filename: str
    url: str
    file_type: str
    biz_type: str
    biz_id: str
    size: int
    mime: str
    created_at: datetime


class FileStorage(ABC):
    """文件存储抽象基类。"""

    @abstractmethod
    def upload(
        self,
        content: bytes,
        filename: str,
        uploader_id: str,
        file_type: str,
        biz_type: str,
        biz_id: str,
        mime: str,
    ) -> FileMeta:
        """上传文件。"""

    @abstractmethod
    def download(self, file_id: str) -> bytes | None:
        """下载文件内容。不存在返回 None。"""

    @abstractmethod
    def get_signed_url(self, file_id: str, expire_sec: int = 3600) -> str:
        """获取签名访问 URL。"""

    @abstractmethod
    def delete(self, file_id: str) -> None:
        """删除文件。"""
```

写入 `src/umcp_core/shared/storage/local.py`：

```python
"""本地文件存储（开发用，写本地磁盘）。"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

from umcp_core.shared.storage.base import FileMeta, FileStorage


class LocalStorage(FileStorage):
    """本地磁盘存储。"""

    def __init__(self, root_dir: str) -> None:
        self._root_dir = root_dir
        os.makedirs(root_dir, exist_ok=True)
        self._metas: dict[str, FileMeta] = {}

    def upload(
        self,
        content: bytes,
        filename: str,
        uploader_id: str,
        file_type: str,
        biz_type: str,
        biz_id: str,
        mime: str,
    ) -> FileMeta:
        file_id = f"file_{uuid.uuid4().hex[:16]}"
        path = os.path.join(self._root_dir, f"{file_id}_{filename}")
        with open(path, "wb") as f:
            f.write(content)
        meta = FileMeta(
            file_id=file_id,
            uploader_id=uploader_id,
            filename=filename,
            url=path,
            file_type=file_type,
            biz_type=biz_type,
            biz_id=biz_id,
            size=len(content),
            mime=mime,
            created_at=datetime.utcnow(),
        )
        self._metas[file_id] = meta
        return meta

    def download(self, file_id: str) -> bytes | None:
        meta = self._metas.get(file_id)
        if meta is None:
            return None
        try:
            with open(meta.url, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def get_signed_url(self, file_id: str, expire_sec: int = 3600) -> str:
        meta = self._metas.get(file_id)
        if meta is None:
            return ""
        return f"file://{meta.url}?expires={expire_sec}"

    def delete(self, file_id: str) -> None:
        meta = self._metas.pop(file_id, None)
        if meta and os.path.exists(meta.url):
            os.remove(meta.url)
```

写入 `src/umcp_core/shared/storage/repository.py`：

```python
"""文件元信息仓储 ORM。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base


class FileModel(Base):
    """文件存储表。"""

    __tablename__ = "files"

    file_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    uploader_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False)
    biz_id: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

- [ ] **步骤 4：在迁移脚本中追加 files 表**

修改 `migrations/versions/002_escort_business_tables.py`，在 `upgrade()` 末尾追加：

```python
    # ---------- 文件存储表 ----------
    op.create_table(
        "files",
        sa.Column("file_id", sa.String(64), primary_key=True),
        sa.Column("uploader_id", sa.String(64), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("file_type", sa.String(32), nullable=False),
        sa.Column("biz_type", sa.String(32), nullable=False),
        sa.Column("biz_id", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_files_biz", "files", ["biz_type", "biz_id"])
```

在 `downgrade()` 中追加（在 `op.drop_table("notifications")` 之前）：

```python
    op.drop_table("files")
```

- [ ] **步骤 5：运行测试验证通过**

运行：`pytest tests/test_storage_local.py -v`
预期：PASS（4 个用例）

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/shared/storage/ migrations/versions/002_escort_business_tables.py tests/test_storage_local.py
git commit -m "feat(storage): 文件存储抽象 + 本地实现 + files 表迁移"
```

---

### 任务 12：陪驾业务扩展表迁移（coach_profiles/reviews/service_records/friendships/credit_logs + 核心表扩展字段）

**文件：**
- 修改：`migrations/versions/002_escort_business_tables.py`（追加陪驾业务表与核心表字段）
- 修改：`src/umcp_core/repositories/postgres/models.py`（追加 ORM 模型）
- 测试：`tests/test_postgres_converters.py`（暂不追加，由任务 13-16 的 router 测试覆盖）

- [ ] **步骤 1：在迁移脚本中追加陪驾业务表与字段扩展**

修改 `migrations/versions/002_escort_business_tables.py`，在 `upgrade()` 末尾追加：

```python
    # ---------- 核心表字段扩展 ----------
    # tasks 表新增字段
    op.add_column("tasks", sa.Column("order_type", sa.String(16), nullable=True))
    op.add_column("tasks", sa.Column("scheduled_at", sa.DateTime(), nullable=True))
    op.add_column("tasks", sa.Column("coach_level_pref", sa.String(16), nullable=True))

    # deals 表新增字段
    op.add_column("deals", sa.Column("deposit_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("deals", sa.Column("deposit_status", sa.String(16), nullable=True))
    op.add_column("deals", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("deals", sa.Column("cancel_initiator", sa.String(16), nullable=True))

    # users 表新增字段
    op.add_column("users", sa.Column("credit_score", sa.Integer(), nullable=False, server_default="100"))

    # ---------- 陪驾业务扩展表 ----------
    op.create_table(
        "escort_coach_profiles",
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("car_model", sa.String(64), nullable=True),
        sa.Column("license_plate", sa.String(32), nullable=True),
        sa.Column("service_areas", postgresql.JSONB(), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("coach_level", sa.String(16), nullable=False, server_default="BRONZE"),
        sa.Column("level_updated_at", sa.DateTime(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by", sa.String(64), nullable=True),
    )
    op.create_index("idx_coach_profiles_user", "escort_coach_profiles", ["user_id"], unique=True)
    op.create_index("idx_coach_profiles_level", "escort_coach_profiles", ["coach_level"])

    op.create_table(
        "escort_reviews",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("deal_id", sa.String(64), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("reviewee_id", sa.String(64), nullable=False),
        sa.Column("reviewer_role", sa.String(16), nullable=False),
        sa.Column("teaching_score", sa.Integer(), nullable=True),
        sa.Column("patience_score", sa.Integer(), nullable=True),
        sa.Column("safety_score", sa.Integer(), nullable=True),
        sa.Column("punctuality_score", sa.Integer(), nullable=True),
        sa.Column("cooperation_score", sa.Integer(), nullable=True),
        sa.Column("payment_score", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_reviews_deal", "escort_reviews", ["deal_id"])
    op.create_index("idx_reviews_reviewee", "escort_reviews", ["reviewee_id"])

    op.create_table(
        "escort_service_records",
        sa.Column("record_id", sa.String(64), primary_key=True),
        sa.Column("deal_id", sa.String(64), nullable=False),
        sa.Column("check_in_at", sa.DateTime(), nullable=True),
        sa.Column("check_out_at", sa.DateTime(), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("route_geojson", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
    )
    op.create_index("idx_service_records_deal", "escort_service_records", ["deal_id"])

    op.create_table(
        "friendships",
        sa.Column("friendship_id", sa.String(64), primary_key=True),
        sa.Column("user_id_a", sa.String(64), nullable=False),
        sa.Column("user_id_b", sa.String(64), nullable=False),
        sa.Column("source_deal_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_friendships_a", "friendships", ["user_id_a", "status"])
    op.create_index("idx_friendships_b", "friendships", ["user_id_b", "status"])

    op.create_table(
        "credit_logs",
        sa.Column("log_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("deal_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_credit_logs_user", "credit_logs", ["user_id"])
```

在 `downgrade()` 开头追加（按 upgrade 反序）：

```python
    op.drop_table("credit_logs")
    op.drop_table("friendships")
    op.drop_table("escort_service_records")
    op.drop_table("escort_reviews")
    op.drop_table("escort_coach_profiles")
    op.drop_column("users", "credit_score")
    op.drop_column("deals", "cancel_initiator")
    op.drop_column("deals", "cancel_reason")
    op.drop_column("deals", "deposit_status")
    op.drop_column("deals", "deposit_amount")
    op.drop_column("tasks", "coach_level_pref")
    op.drop_column("tasks", "scheduled_at")
    op.drop_column("tasks", "order_type")
```

- [ ] **步骤 2：在 ORM models.py 中追加新表模型**

修改 `src/umcp_core/repositories/postgres/models.py`，在文件末尾追加：

```python
class EscortCoachProfileModel(Base):
    """教练资料扩展表。"""

    __tablename__ = "escort_coach_profiles"

    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    car_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    service_areas: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    hourly_rate: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    coach_level: Mapped[str] = mapped_column(String(16), nullable=False)
    level_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EscortReviewModel(Base):
    """陪驾双向评价表。"""

    __tablename__ = "escort_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(16), nullable=False)
    teaching_score: Mapped[int | None] = mapped_column(nullable=True)
    patience_score: Mapped[int | None] = mapped_column(nullable=True)
    safety_score: Mapped[int | None] = mapped_column(nullable=True)
    punctuality_score: Mapped[int | None] = mapped_column(nullable=True)
    cooperation_score: Mapped[int | None] = mapped_column(nullable=True)
    payment_score: Mapped[int | None] = mapped_column(nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EscortServiceRecordModel(Base):
    """服务执行记录表。"""

    __tablename__ = "escort_service_records"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_min: Mapped[int | None] = mapped_column(nullable=True)
    route_geojson: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class FriendshipModel(Base):
    """好友关系表。"""

    __tablename__ = "friendships"

    friendship_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id_a: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id_b: Mapped[str] = mapped_column(String(64), nullable=False)
    source_deal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CreditLogModel(Base):
    """信用分变更日志表。"""

    __tablename__ = "credit_logs"

    log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    delta: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    deal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

并在 `TaskModel` 中追加三个字段（在 `custom_fields` 之后）：

```python
    order_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    coach_level_pref: Mapped[str | None] = mapped_column(String(16), nullable=True)
```

在 `DealModel` 中追加四个字段（在 `metadata_` 之后）：

```python
    deposit_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deposit_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_initiator: Mapped[str | None] = mapped_column(String(16), nullable=True)
```

在 `UserModel` 中追加一个字段（在 `metadata_` 之后）：

```python
    credit_score: Mapped[int] = mapped_column(nullable=False, default=100)
```

- [ ] **步骤 3：本地验证迁移可执行（若有 PG）**

运行：`alembic downgrade 001 && alembic upgrade head`
预期：无报错，所有新表与新字段创建成功

- [ ] **步骤 4：运行已有 PG 测试确认 ORM 兼容**

运行：`pytest tests/test_postgres_converters.py tests/test_postgres_repos.py -v -m postgres`（若 PG 可用）
预期：PASS（若 PG 不可用则跳过，由 CI 验证）

- [ ] **步骤 5：Commit**

```bash
git add migrations/versions/002_escort_business_tables.py src/umcp_core/repositories/postgres/models.py
git commit -m "feat(escort): 陪驾业务扩展表与核心表字段迁移"
```

---

### 任务 13：EscortTask 扩展实时单/预约单字段

**文件：**
- 修改：`plugins/escort_driving/tasks.py`
- 测试：`plugins/escort_driving/tests/test_tasks.py`（追加用例）

- [ ] **步骤 1：编写失败的测试**

在 `plugins/escort_driving/tests/test_tasks.py` 末尾追加：

```python
def test_escort_task_default_order_type_is_instant():
    from umcp_core.core.domain import DomainTag
    from escort_driving.tasks import EscortTask
    task = EscortTask(
        demander_id="s_1",
        domain_tag=DomainTag.of("escort"),
        origin_lat=39.9,
        origin_lng=116.4,
    )
    assert task.structured_fields["order_type"] == "INSTANT"


def test_escort_task_supports_scheduled_order():
    from datetime import datetime
    from umcp_core.core.domain import DomainTag
    from escort_driving.tasks import EscortTask
    scheduled = datetime(2026, 8, 15, 10, 0)
    task = EscortTask(
        demander_id="s_1",
        domain_tag=DomainTag.of("escort"),
        origin_lat=39.9,
        origin_lng=116.4,
        order_type="SCHEDULED",
        scheduled_at=scheduled,
    )
    assert task.structured_fields["order_type"] == "SCHEDULED"
    assert task.structured_fields["scheduled_at"] == scheduled


def test_escort_task_supports_coach_level_pref():
    from umcp_core.core.domain import DomainTag
    from escort_driving.tasks import EscortTask
    task = EscortTask(
        demander_id="s_1",
        domain_tag=DomainTag.of("escort"),
        origin_lat=39.9,
        origin_lng=116.4,
        coach_level_pref="GOLD",
    )
    assert task.structured_fields["coach_level_pref"] == "GOLD"


def test_escort_task_default_coach_level_pref_is_any():
    from umcp_core.core.domain import DomainTag
    from escort_driving.tasks import EscortTask
    task = EscortTask(
        demander_id="s_1",
        domain_tag=DomainTag.of("escort"),
        origin_lat=39.9,
        origin_lng=116.4,
    )
    assert task.structured_fields["coach_level_pref"] == "ANY"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest plugins/escort_driving/tests/test_tasks.py -v -k "order_type or scheduled_order or coach_level_pref"`
预期：FAIL，`KeyError: 'order_type'`

- [ ] **步骤 3：扩展 EscortTask**

修改 `plugins/escort_driving/tasks.py`，完整替换为：

```python
"""陪驾服务任务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from umcp_core.core.domain import DomainTag, SpatioTemporalConstraint
from umcp_core.core.task import StandardTask


class EscortTask(StandardTask):
    """陪驾服务任务（标准化任务）。

    支持两种订单类型：
    - INSTANT：实时单，下班约车开回家场景，秒级响应
    - SCHEDULED：预约单，指定未来时间，Top3 推荐
    """

    _task_type_name = "escort"

    def __init__(
        self,
        demander_id: str,
        domain_tag: DomainTag,
        origin_lat: float,
        origin_lng: float,
        car_type: str = "manual",
        required_skills: list[str] | None = None,
        duration_hours: float = 1.0,
        order_type: str = "INSTANT",
        scheduled_at: datetime | None = None,
        coach_level_pref: str = "ANY",
        **kwargs: Any,
    ) -> None:
        spatio = SpatioTemporalConstraint(
            origin_lat=origin_lat,
            origin_lng=origin_lng,
        )
        super().__init__(demander_id, domain_tag, spatio_temporal=spatio, **kwargs)

        self.structured_fields["car_type"] = car_type
        self.structured_fields["required_skills"] = required_skills or []
        self.structured_fields["duration_hours"] = duration_hours
        self.structured_fields["order_type"] = order_type
        self.structured_fields["scheduled_at"] = scheduled_at
        self.structured_fields["coach_level_pref"] = coach_level_pref

        # 供 Hourly 支付策略使用
        self.custom_fields["actual_hours"] = duration_hours

    def task_type(self) -> str:
        return "escort"
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest plugins/escort_driving/tests/test_tasks.py -v`
预期：PASS（13 个用例，含 4 个新增 + 9 个原有）

- [ ] **步骤 5：运行回归测试**

运行：`pytest plugins/escort_driving/tests/ tests/test_end_to_end_escort.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add plugins/escort_driving/tasks.py plugins/escort_driving/tests/test_tasks.py
git commit -m "feat(escort): EscortTask 支持实时单/预约单与等级偏好"
```

---

### 任务 14：ScheduledMatchStrategy（预约单 Top3 推荐）

**文件：**
- 创建：`plugins/escort_driving/scheduled_match.py`
- 测试：`tests/test_escort_scheduled_match.py`

- [ ] **步骤 1：编写失败的测试**

写入 `tests/test_escort_scheduled_match.py`：

```python
"""预约单 Top3 匹配测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def scheduled_match():
    from escort_driving.scheduled_match import ScheduledMatchStrategy
    return ScheduledMatchStrategy(top_n=3)


def _make_coach(resource_id, coach_level="B", car_type="manual", skills=None, lat=39.9, lng=116.4):
    from umcp_core.core.domain import DomainTag
    from escort_driving.resources import CoachResource
    return CoachResource(
        supplier_id=f"supplier_{resource_id}",
        domain_tag=DomainTag.of("escort"),
        current_lat=lat,
        current_lng=lng,
        car_type=car_type,
        coach_level=coach_level,
        skills=skills or [],
    )


def _make_task(order_type="SCHEDULED", required_skills=None, coach_level_pref="ANY"):
    from umcp_core.core.domain import DomainTag
    from escort_driving.tasks import EscortTask
    return EscortTask(
        demander_id="s_1",
        domain_tag=DomainTag.of("escort"),
        origin_lat=39.9042,
        origin_lng=116.4074,
        required_skills=required_skills or [],
        order_type=order_type,
        coach_level_pref=coach_level_pref,
    )


def test_scheduled_match_returns_top3_sorted_by_score(scheduled_match):
    from umcp_core.layers.l3 import MatchResult
    task = _make_task(required_skills=["night_driving", "highway"])
    coaches = [
        _make_coach("c1", coach_level="A", skills=["night_driving", "highway", "parking"]),
        _make_coach("c2", coach_level="B", skills=["night_driving"]),
        _make_coach("c3", coach_level="A", skills=["night_driving", "highway"]),
        _make_coach("c4", coach_level="B", skills=[]),  # 不匹配，应排除
    ]
    result = scheduled_match.execute(task, coaches)
    assert isinstance(result, MatchResult)
    assert len(result.candidates) <= 3
    # Top1 应是 c1 或 c3（A 级 + 两个技能匹配）
    assert result.selected_resource_id in ("res_c1", "res_c3")


def test_scheduled_match_returns_empty_when_no_match(scheduled_match):
    task = _make_task(required_skills=["nonexistent_skill"])
    coaches = [_make_coach("c1", skills=["other"])]
    result = scheduled_match.execute(task, coaches)
    assert result.selected_resource_id is None
    assert result.candidates == []


def test_scheduled_match_respects_top_n():
    from escort_driving.scheduled_match import ScheduledMatchStrategy
    strategy = ScheduledMatchStrategy(top_n=2)
    task = _make_task()
    coaches = [_make_coach(f"c{i}", coach_level="A") for i in range(5)]
    result = strategy.execute(task, coaches)
    assert len(result.candidates) == 2


def test_scheduled_match_filters_by_coach_level_pref():
    scheduled_match_strict = ScheduledMatchStrategy(top_n=3)
    task = _make_task(coach_level_pref="GOLD")
    # CoachResource 的 coach_level 是 A/B（插件旧值），等级偏好 GOLD 不匹配任何
    # 简化：当 pref=ANY 时不过滤；非 ANY 时按 metadata.coach_level 过滤
    coaches = [
        _make_coach("c1", coach_level="A"),
        _make_coach("c2", coach_level="B"),
    ]
    result = scheduled_match_strict.execute(task, coaches)
    # coach_level_pref=GOLD 与 A/B 都不匹配，应返回空
    assert result.selected_resource_id is None
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_escort_scheduled_match.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'escort_driving.scheduled_match'`

- [ ] **步骤 3：实现 ScheduledMatchStrategy**

写入 `plugins/escort_driving/scheduled_match.py`：

```python
"""预约单 Top3 推荐匹配策略。

与 InstantMatch（实时单派单 Top1）不同，预约单返回 Top N 候选，
由学员在前端浏览并选择一位教练，再创建 Deal。
"""
from __future__ import annotations

from umcp_core.core.task import Task
from umcp_core.layers.l3 import MatchResult, MatchStrategy
from escort_driving.scoring import EscortMatchScorer, CAR_TYPE_MISMATCH_SCORE


class ScheduledMatchStrategy(MatchStrategy):
    """预约单 Top N 推荐策略。

    流程：
    1. 用 EscortMatchScorer 评分所有候选
    2. 排除车型不匹配（score == CAR_TYPE_MISMATCH_SCORE）
    3. 按等级偏好过滤（coach_level_pref != ANY 时）
    4. 取 Top N 返回（不自动选定，selected_resource_id=None）
    """

    def __init__(self, top_n: int = 3) -> None:
        self._scorer = EscortMatchScorer()
        self._top_n = top_n

    def execute(self, task: Task, candidates: list) -> MatchResult:
        task_level_pref = task.structured_fields.get("coach_level_pref", "ANY")

        scored = []
        for resource in candidates:
            score = self._scorer(task, resource)
            if score == CAR_TYPE_MISMATCH_SCORE:
                continue
            # 等级偏好过滤（ANY 时跳过）
            if task_level_pref != "ANY":
                # CoachResource 的 coach_level 是 A/B（旧体系），
                # 与 BRONZE/SILVER/GOLD/PLATINUM 不直接对应，按字符串相等过滤
                if resource.metadata.get("coach_level") != task_level_pref:
                    continue
            scored.append((resource, score))

        # 降序排序（高分优先）
        scored.sort(key=lambda x: x[1], reverse=True)

        top = scored[: self._top_n]
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=None,  # 预约单不自动选定
            candidates=[r.resource_id for r, _ in top],
        )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_escort_scheduled_match.py -v`
预期：PASS（4 个用例）

- [ ] **步骤 5：Commit**

```bash
git add plugins/escort_driving/scheduled_match.py tests/test_escort_scheduled_match.py
git commit -m "feat(escort): 预约单 Top3 推荐匹配策略"
```

---

### 任务 15：陪驾插件注册 ScheduledMatchStrategy

**文件：**
- 修改：`plugins/escort_driving/__init__.py`
- 修改：`plugins/escort_driving/plugin.json`
- 测试：`plugins/escort_driving/tests/test_plugin_loading.py`（追加用例）

- [ ] **步骤 1：编写失败的测试**

在 `plugins/escort_driving/tests/test_plugin_loading.py` 末尾追加：

```python
def test_scheduled_match_strategy_registered():
    from umcp_core.server import UMCPServer
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.load_plugin("escort_driving")
    # 应该同时注册 InstantMatch（实时单）和 ScheduledMatchStrategy（预约单）
    # 用 match_strategy_for("escort") 拿到的是 InstantMatch（兜底）
    # ScheduledMatchStrategy 通过 server._scheduled_match_strategies["escort"] 访问
    scheduled = getattr(server, "_scheduled_match_strategies", {}).get("escort")
    assert scheduled is not None
    assert scheduled._top_n == 3
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest plugins/escort_driving/tests/test_plugin_loading.py::test_scheduled_match_strategy_registered -v`
预期：FAIL，`AssertionError: assert None is not None`

- [ ] **步骤 3：扩展 UMCPServer 与插件注册**

修改 `src/umcp_core/server.py`，在 `__init__` 中（`_subtask_executors` 之后）追加：

```python
        # 预约单匹配策略（按 domain 注册）
        self._scheduled_match_strategies: dict[str, Any] = {}
```

在 `register_trust_engine` 方法后追加新方法：

```python
    def register_scheduled_match_strategy(self, domain: str, strategy: Any) -> None:
        """按 domain 注册预约单匹配策略。"""
        self._scheduled_match_strategies[domain.lower()] = strategy

    def scheduled_match_strategy_for(self, domain: DomainTag | str) -> Any | None:
        """按 domain 查询预约单匹配策略。"""
        key = domain.value if isinstance(domain, DomainTag) else str(domain).lower()
        return self._scheduled_match_strategies.get(key)
```

修改 `plugins/escort_driving/__init__.py`，在 `register_plugin` 函数末尾追加：

```python
    from escort_driving.scheduled_match import ScheduledMatchStrategy
    server.register_scheduled_match_strategy(domain, ScheduledMatchStrategy(top_n=3))
```

修改 `plugins/escort_driving/plugin.json`，追加字段（在 `match_strategy` 之后）：

```json
  "scheduled_match_strategy": "escort_driving.scheduled_match.ScheduledMatchStrategy",
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest plugins/escort_driving/tests/test_plugin_loading.py -v`
预期：PASS（9 个用例，含 1 个新增 + 8 个原有）

- [ ] **步骤 5：运行回归测试**

运行：`pytest plugins/escort_driving/tests/ tests/test_multi_plugin_routing.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add src/umcp_core/server.py plugins/escort_driving/__init__.py plugins/escort_driving/plugin.json plugins/escort_driving/tests/test_plugin_loading.py
git commit -m "feat(escort): 插件注册预约单匹配策略"
```

---

### 任务 16：陪驾 orders router（学员下单/取消/查询）

**文件：**
- 创建：`src/umcp_core/transport/routers/escort/__init__.py`
- 创建：`src/umcp_core/transport/routers/escort/orders.py`
- 测试：`tests/test_escort_orders_router.py`

- [ ] **步骤 1：编写失败的测试**

写入 `tests/test_escort_orders_router.py`：

```python
"""陪驾下单 router 测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def escort_app(client):
    """装配了 escort 插件的 app（client fixture 来自 conftest）。
    本任务暂用 client，后续任务 18 会用专用 escort_client 替代。"""
    return client


def test_create_instant_order_returns_task_info(escort_app):
    # 注意：本测试在任务 18 完成 app 工厂装配后才能真正跑通
    # 此处先写测试，预期失败引导实现
    payload = {
        "demander_id": "student_1",
        "domain_tag": "escort",
        "title": "下班回家",
        "order_type": "INSTANT",
        "origin_lat": 39.9042,
        "origin_lng": 116.4074,
        "car_type": "manual",
        "duration_hours": 1.0,
        "coach_level_pref": "ANY",
    }
    resp = escort_app.post("/api/v1/escort/orders", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert data["data"]["task_id"]
    assert data["data"]["order_type"] == "INSTANT"


def test_create_scheduled_order_returns_top3_candidates(escort_app):
    payload = {
        "demander_id": "student_1",
        "domain_tag": "escort",
        "title": "周末练车",
        "order_type": "SCHEDULED",
        "scheduled_at": "2026-08-15T10:00:00",
        "origin_lat": 39.9042,
        "origin_lng": 116.4074,
        "car_type": "manual",
        "coach_level_pref": "ANY",
    }
    resp = escort_app.post("/api/v1/escort/orders", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    # 预约单返回 Top3 候选（可能少于 3）
    assert "candidates" in data["data"]
    assert isinstance(data["data"]["candidates"], list)


def test_list_my_orders(escort_app):
    # 先创建一个订单
    payload = {
        "demander_id": "student_1",
        "domain_tag": "escort",
        "order_type": "INSTANT",
        "origin_lat": 39.9,
        "origin_lng": 116.4,
    }
    escort_app.post("/api/v1/escort/orders", json=payload)
    resp = escort_app.get("/api/v1/escort/orders?demander_id=student_1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert len(data["data"]["items"]) >= 1


def test_cancel_order(escort_app):
    payload = {
        "demander_id": "student_1",
        "domain_tag": "escort",
        "order_type": "INSTANT",
        "origin_lat": 39.9,
        "origin_lng": 116.4,
    }
    create_resp = escort_app.post("/api/v1/escort/orders", json=payload)
    task_id = create_resp.json()["data"]["task_id"]
    resp = escort_app.post(f"/api/v1/escort/orders/{task_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_escort_orders_router.py -v`
预期：FAIL，`AttributeError: 'NoneType' object has no attribute 'post'` 或 404（路由未注册）

- [ ] **步骤 3：实现 escort orders router**

写入 `src/umcp_core/transport/routers/escort/__init__.py`：

```python
"""陪驾业务 router 包。"""

from umcp_core.transport.routers.escort import coaches, orders, reviews


def register_escort_routers(app) -> None:
    """注册陪驾业务路由。"""
    app.include_router(orders.router, prefix="/api/v1/escort")
    app.include_router(coaches.router, prefix="/api/v1/escort")
    app.include_router(reviews.router, prefix="/api/v1/escort")
```

写入 `src/umcp_core/transport/routers/escort/orders.py`：

```python
"""陪驾订单路由（学员端：下单/取消/查询）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.domain import DomainTag
from umcp_core.core.task import TaskStatus
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, PaginatedData, ok, paginated
from escort_driving.tasks import EscortTask

router = APIRouter()


class CreateOrderRequest(BaseModel):
    demander_id: str
    domain_tag: str = "escort"
    title: str = ""
    description: str = ""
    order_type: str = "INSTANT"  # INSTANT / SCHEDULED
    scheduled_at: str | None = None  # ISO 格式，预约单必填
    origin_lat: float
    origin_lng: float
    car_type: str = "manual"
    required_skills: list[str] | None = None
    duration_hours: float = 1.0
    coach_level_pref: str = "ANY"


class OrderInfo(BaseModel):
    task_id: str
    demander_id: str
    domain_tag: str
    status: str
    title: str
    order_type: str
    scheduled_at: str | None = None
    coach_level_pref: str = "ANY"
    assigned_resource_id: str | None = None


class ScheduledOrderInfo(BaseModel):
    task_id: str
    order_type: str
    candidates: list[str]
    scores: list[float] = []


def _task_to_order_info(task: Any) -> OrderInfo:
    scheduled_at = task.structured_fields.get("scheduled_at")
    return OrderInfo(
        task_id=task.task_id,
        demander_id=task.demander_id,
        domain_tag=task.domain_tag.value,
        status=task.status,
        title=getattr(task, "title", ""),
        order_type=task.structured_fields.get("order_type", "INSTANT"),
        scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
        coach_level_pref=task.structured_fields.get("coach_level_pref", "ANY"),
        assigned_resource_id=task.assigned_resource_id,
    )


@router.post("/orders", response_model=Envelope)
async def create_order(
    req: CreateOrderRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """学员下单（实时单/预约单）。

    - 实时单：走 InstantMatch，自动派单 Top1
    - 预约单：走 ScheduledMatchStrategy，返回 Top3 候选，学员后续选择
    """
    scheduled_at = None
    if req.scheduled_at:
        scheduled_at = datetime.fromisoformat(req.scheduled_at)

    task = EscortTask(
        demander_id=req.demander_id,
        domain_tag=DomainTag.of(req.domain_tag),
        origin_lat=req.origin_lat,
        origin_lng=req.origin_lng,
        car_type=req.car_type,
        required_skills=req.required_skills,
        duration_hours=req.duration_hours,
        order_type=req.order_type,
        scheduled_at=scheduled_at,
        coach_level_pref=req.coach_level_pref,
    )
    task.title = req.title
    task.description = req.description

    if req.order_type == "SCHEDULED":
        # 预约单：调 ScheduledMatchStrategy 返回 Top3，不自动 publish
        strategy = server.scheduled_match_strategy_for(req.domain_tag)
        if strategy is None:
            raise IllegalStateError(message=f"domain {req.domain_tag} 未注册预约单匹配策略")
        candidates = server.resource_repo.list_all()
        domain_candidates = [r for r in candidates if r.domain_tag.value == req.domain_tag]
        result = strategy.execute(task, domain_candidates)
        # 保存任务为 DRAFT 状态（等待学员选择教练后再 publish）
        server.task_repo.save(task)
        return ok(
            data=ScheduledOrderInfo(
                task_id=task.task_id,
                order_type="SCHEDULED",
                candidates=result.candidates,
            ).model_dump()
        )

    # 实时单：publish_and_match
    try:
        server.publish_and_match(task)
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    return ok(_task_to_order_info(task))


@router.get("/orders", response_model=Envelope[PaginatedData[OrderInfo]])
async def list_orders(
    demander_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[PaginatedData[OrderInfo]]:
    """查询订单列表。"""
    tasks = server.task_repo.list_all()
    # 只返回 escort domain
    tasks = [t for t in tasks if t.domain_tag.value == "escort"]
    if demander_id:
        tasks = [t for t in tasks if t.demander_id == demander_id]
    if status:
        tasks = [t for t in tasks if t.status == status]

    total = len(tasks)
    start = (page - 1) * size
    end = start + size
    page_items = tasks[start:end]
    return paginated(
        items=[_task_to_order_info(t) for t in page_items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/orders/{task_id}", response_model=Envelope[OrderInfo])
async def get_order(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[OrderInfo]:
    """查询订单详情。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    return ok(_task_to_order_info(task))


@router.post("/orders/{task_id}/cancel", response_model=Envelope)
async def cancel_order(
    task_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """学员取消订单。"""
    task = server.task_repo.find_by_id(task_id)
    if task is None:
        raise NotFoundError(message=f"订单 {task_id} 不存在")
    try:
        task.cancel()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.task_repo.save(task)
    return ok(message="已取消")
```

- [ ] **步骤 4：运行测试验证失败（路由未注册）**

运行：`pytest tests/test_escort_orders_router.py -v`
预期：FAIL，404 或 app 未装配 escort 路由

- [ ] **步骤 5：Commit（路由文件先入库，装配在任务 18 完成）**

```bash
git add src/umcp_core/transport/routers/escort/__init__.py src/umcp_core/transport/routers/escort/orders.py tests/test_escort_orders_router.py
git commit -m "feat(escort): orders router 实现（装配待任务 18）"
```

---

### 任务 17：陪驾 coaches router（教练接单/签到签退）

**文件：**
- 创建：`src/umcp_core/transport/routers/escort/coaches.py`
- 测试：`tests/test_escort_coaches_router.py`

- [ ] **步骤 1：编写失败的测试**

写入 `tests/test_escort_coaches_router.py`：

```python
"""陪驾教练 router 测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def escort_client(client):
    """复用 conftest 的 client（任务 18 装配后会真正可用）。"""
    return client


def test_coach_accept_order_transitions_deal_to_active(escort_client):
    # 本测试需要预先创建 deal，较复杂；在任务 18 端到端冒烟中覆盖
    # 此处先验证端点存在
    resp = escort_client.post("/api/v1/escort/coaches/deals/dummy/accept")
    # 即便 deal 不存在，应返回 NotFoundError（code != 0）而非 404 路由不存在
    assert resp.status_code == 200
    assert resp.json()["code"] != 0  # 业务错误


def test_coach_check_in_transitions_deal_to_in_service(escort_client):
    resp = escort_client.post("/api/v1/escort/coaches/deals/dummy/check-in")
    assert resp.status_code == 200
    assert resp.json()["code"] != 0  # deal 不存在


def test_coach_check_out_completes_deal(escort_client):
    resp = escort_client.post("/api/v1/escort/coaches/deals/dummy/check-out")
    assert resp.status_code == 200
    assert resp.json()["code"] != 0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_escort_coaches_router.py -v`
预期：FAIL，404（路由未注册）

- [ ] **步骤 3：实现 coaches router**

写入 `src/umcp_core/transport/routers/escort/coaches.py`：

```python
"""陪驾教练路由（接单/签到签退/我的订单）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, PaginatedData, ok, paginated

router = APIRouter()


class AcceptOrderRequest(BaseModel):
    coach_id: str  # 教练 user_id
    resource_id: str


class CheckInRequest(BaseModel):
    coach_id: str
    lat: float
    lng: float


class CheckOutRequest(BaseModel):
    coach_id: str
    lat: float
    lng: float


class DealInfo(BaseModel):
    deal_id: str
    task_id: str
    resource_id: str
    demander_id: str
    supplier_id: str
    status: str


def _deal_to_info(deal: Deal) -> DealInfo:
    return DealInfo(
        deal_id=deal.deal_id,
        task_id=deal.task_id,
        resource_id=deal.resource_id,
        demander_id=deal.demander_id,
        supplier_id=deal.supplier_id,
        status=deal.status,
    )


@router.post("/coaches/deals/{deal_id}/accept", response_model=Envelope[DealInfo])
async def accept_deal(
    deal_id: str,
    req: AcceptOrderRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[DealInfo]:
    """教练接单：PENDING → ACTIVE。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.activate()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    return ok(_deal_to_info(deal))


@router.post("/coaches/deals/{deal_id}/check-in", response_model=Envelope[DealInfo])
async def check_in(
    deal_id: str,
    req: CheckInRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[DealInfo]:
    """教练签到：ACTIVE → IN_SERVICE。"""
    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    deal.bind_event_bus(server.event_bus)
    try:
        deal.check_in()
    except (RuntimeError, ValueError) as e:
        raise IllegalStateError(message=str(e)) from e
    server.deal_repo.save(deal)
    # 发布签到事件
    server.event_bus.publish(
        Event(
            type=EventType.CHECK_IN,
            source_layer="ESCORT",
            payload={"deal_id": deal_id, "coach_id": req.coach_id, "lat": req.lat, "lng": req.lng},
        )
    )
    return ok(_deal_to_info(deal))


@router.post("/coaches/deals/{deal_id}/check-out", response_model=Envelope[DealInfo])
async def check_out(
    deal_id: str,
    req: CheckOutRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope[DealInfo]:
    """教练签退：IN_SERVICE → COMPLETED。"""
    deal = server.deal_repo.find_by