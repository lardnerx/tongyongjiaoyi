"""阶段四C Demo：复合任务编排（商务出行包）。

场景：
- 子任务 1：打车去机场（ride 域，无依赖）
- 子任务 2：代驾回家（escort 域，depends_on=[1]）
- 子任务 3：团购伴手礼（group_buying 域，无依赖，与打车并行）

运行方式：
    PYTHONPATH=src;plugins python -m examples.composite_task_demo
"""

from __future__ import annotations

import sys
from pathlib import Path

# 注入 src 和 plugins 到 sys.path，使 demo 可直接运行
_SRC = Path(__file__).parent.parent / "src"
_PLUGINS = Path(__file__).parent.parent / "plugins"
for p in (_SRC, _PLUGINS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer


class _DemoResource(Resource):
    """Demo 资源桩。"""

    def __init__(self, resource_id: str, domain: str, supplier_name: str) -> None:
        super().__init__(
            supplier_id=f"supplier_{resource_id}",
            domain_tag=DomainTag.of(domain),
            resource_id=resource_id,
        )
        self.status = ResourceStatus.IDLE
        self.metadata["name"] = supplier_name

    def resource_type(self) -> str:
        return "demo"


class _DemoMatchStrategy(InstantMatch):
    """Demo 匹配策略：始终匹配第一个候选。"""

    def execute(self, task, candidates):
        if not candidates:
            return MatchResult(task_id=task.task_id)
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=candidates[0].resource_id,
            candidates=[r.resource_id for r in candidates],
        )


def _make_subtask(task_id: str, domain: str, title: str) -> StandardTask:
    task = StandardTask(
        demander_id="business_user_001",
        domain_tag=DomainTag.of(domain),
        title=title,
    )
    task.task_id = task_id
    return task


def run_success_scenario() -> None:
    """场景一：成功完成商务出行包。"""
    print("=" * 60)
    print("场景一：商务出行包（成功完成）")
    print("=" * 60)

    server = UMCPServer()
    server.use_in_memory_repositories()

    # 注册三个 domain 的策略和资源
    for d, res_id, name in [
        ("ride", "ride_res", "出租车司机老王"),
        ("escort", "escort_res", "陪驾教练老李"),
        ("group_buying", "gb_res", "伴手礼供应商老张"),
    ]:
        server.register_match_strategy(d, _DemoMatchStrategy())
        server.resource_repo.save(_DemoResource(res_id, d, name))

    # 构造子任务
    sub_ride = _make_subtask("ride_1", "ride", "打车去机场")
    sub_escort = _make_subtask("escort_1", "escort", "代驾回家")
    sub_gb = _make_subtask("gb_1", "group_buying", "团购伴手礼")

    print(f"\n子任务 A: {sub_ride.title} ({sub_ride.domain_tag.value})")
    print(f"子任务 B: {sub_escort.title} ({sub_escort.domain_tag.value}), depends_on=[A]")
    print(f"子任务 C: {sub_gb.title} ({sub_gb.domain_tag.value})")

    composite = CompositeTask(
        demander_id="business_user_001",
        domain_tag=DomainTag.of("composite"),
        subtasks=[sub_ride, sub_escort, sub_gb],
        dependencies={"escort_1": ["ride_1"]},
    )

    print(f"\n父任务 ID: {composite.task_id}")
    print(f"初始状态: {composite.status}")
    print("\n启动编排...")

    server.execute_composite(composite)

    print(f"\n--- 执行结果 ---")
    print(f"子任务 A ({sub_ride.title}): {sub_ride.status}")
    print(f"  └─ 指派资源: {sub_ride.assigned_resource_id}")
    print(f"子任务 B ({sub_escort.title}): {sub_escort.status}")
    print(f"  └─ 指派资源: {sub_escort.assigned_resource_id}")
    print(f"子任务 C ({sub_gb.title}): {sub_gb.status}")
    print(f"  └─ 指派资源: {sub_gb.assigned_resource_id}")
    print(f"\n父任务状态: {composite.status}")

    assert composite.status == TaskStatus.COMPLETED
    print("\n✓ 商务出行包全部完成")


def run_failure_scenario() -> None:
    """场景二：打车失败，代驾取消，团购完成，父任务失败。"""
    print("\n" + "=" * 60)
    print("场景二：打车失败 → 代驾取消 → 父任务失败")
    print("=" * 60)

    server = UMCPServer()
    server.use_in_memory_repositories()

    # ride 域注册无匹配策略（模拟无可用出租车）
    class _NoMatchStrategy(InstantMatch):
        def execute(self, task, candidates):
            return MatchResult(task_id=task.task_id)

    server.register_match_strategy("ride", _NoMatchStrategy())
    server.register_match_strategy("escort", _DemoMatchStrategy())
    server.register_match_strategy("group_buying", _DemoMatchStrategy())
    server.resource_repo.save(_DemoResource("escort_res", "escort", "陪驾教练老李"))
    server.resource_repo.save(_DemoResource("gb_res", "group_buying", "伴手礼供应商老张"))

    sub_ride = _make_subtask("ride_1", "ride", "打车去机场")
    sub_escort = _make_subtask("escort_1", "escort", "代驾回家")
    sub_gb = _make_subtask("gb_1", "group_buying", "团购伴手礼")

    composite = CompositeTask(
        demander_id="business_user_001",
        domain_tag=DomainTag.of("composite"),
        subtasks=[sub_ride, sub_escort, sub_gb],
        dependencies={"escort_1": ["ride_1"]},
    )

    print(f"\n子任务 A: {sub_ride.title} (无可用资源)")
    print(f"子任务 B: {sub_escort.title}, depends_on=[A]")
    print(f"子任务 C: {sub_gb.title} (无依赖)")

    print("\n启动编排...")
    server.execute_composite(composite)

    print(f"\n--- 执行结果 ---")
    print(f"子任务 A ({sub_ride.title}): {sub_ride.status} (无匹配资源)")
    print(f"子任务 B ({sub_escort.title}): {sub_escort.status} (依赖 A，被传播取消)")
    print(f"子任务 C ({sub_gb.title}): {sub_gb.status} (无依赖兄弟，继续完成)")
    print(f"\n父任务状态: {composite.status}")

    assert sub_ride.status == TaskStatus.CANCELLED
    assert sub_escort.status == TaskStatus.CANCELLED
    assert sub_gb.status == TaskStatus.COMPLETED
    assert composite.status == TaskStatus.CANCELLED
    print("\n✓ 失败传播正确：A 失败 → B 取消，C 完成，父任务失败")


if __name__ == "__main__":
    run_success_scenario()
    run_failure_scenario()
    print("\n" + "=" * 60)
    print("Demo 完成")
    print("=" * 60)
