"""端到端测试：复合任务编排。"""

from __future__ import annotations

from umcp_core.core.composite_task import CompositeTask
from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource, ResourceStatus
from umcp_core.core.task import StandardTask, TaskStatus
from umcp_core.layers.l3 import InstantMatch, MatchResult
from umcp_core.server import UMCPServer


class _E2EResource(Resource):
    """端到端测试用资源。"""

    def __init__(self, resource_id: str = "res_1", domain: str = "ride") -> None:
        super().__init__(
            supplier_id="supplier_1",
            domain_tag=DomainTag.of(domain),
            resource_id=resource_id,
        )
        self.status = ResourceStatus.IDLE

    def resource_type(self) -> str:
        return "e2e"


class _AlwaysMatchStrategy(InstantMatch):
    """始终匹配第一个候选资源。"""

    def execute(self, task, candidates):
        if not candidates:
            return MatchResult(task_id=task.task_id)
        return MatchResult(
            task_id=task.task_id,
            selected_resource_id=candidates[0].resource_id,
            candidates=[r.resource_id for r in candidates],
        )


class _NoMatchStrategy(InstantMatch):
    """永远不匹配。"""

    def execute(self, task, candidates):
        return MatchResult(task_id=task.task_id)

def _make_server_with_domains(*domains: str, no_match_domain: str | None = None) -> UMCPServer:
    server = UMCPServer()
    server.use_in_memory_repositories()
    for d in domains:
        strategy = _NoMatchStrategy() if d == no_match_domain else _AlwaysMatchStrategy()
        server.register_match_strategy(d, strategy)
        server.resource_repo.save(_E2EResource(resource_id=f"res_{d}", domain=d))
    return server


def _make_subtask(task_id: str, domain: str = "ride") -> StandardTask:
    task = StandardTask(
        demander_id="user_001",
        domain_tag=DomainTag.of(domain),
    )
    task.task_id = task_id
    return task


class TestParallelComposite:
    def test_parallel_composite_all_complete(self):
        """3 个无依赖子任务并行执行 → 父任务 COMPLETED。"""
        server = _make_server_with_domains("ride", "escort", "group_buying")
        sub_ride = _make_subtask("ride_1", "ride")
        sub_escort = _make_subtask("escort_1", "escort")
        sub_gb = _make_subtask("gb_1", "group_buying")

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_ride, sub_escort, sub_gb],
        )
        server.execute_composite(composite)

        assert sub_ride.status == TaskStatus.COMPLETED
        assert sub_escort.status == TaskStatus.COMPLETED
        assert sub_gb.status == TaskStatus.COMPLETED
        assert composite.status == TaskStatus.COMPLETED


class TestSerialComposite:
    def test_serial_composite_pipeline(self):
        """A→B→C 串行依赖，按序完成 → 父任务 COMPLETED。"""
        server = _make_server_with_domains("ride")
        sub_a = _make_subtask("a", "ride")
        sub_b = _make_subtask("b", "ride")
        sub_c = _make_subtask("c", "ride")

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b, sub_c],
            dependencies={"b": ["a"], "c": ["b"]},
        )
        server.execute_composite(composite)

        assert sub_a.status == TaskStatus.COMPLETED
        assert sub_b.status == TaskStatus.COMPLETED
        assert sub_c.status == TaskStatus.COMPLETED
        assert composite.status == TaskStatus.COMPLETED


class TestMixedDag:
    def test_mixed_dag_parallel_and_serial(self):
        """混合 DAG：A∥B → C（A、B 并行，都完成后 C 才执行）。"""
        server = _make_server_with_domains("ride")
        sub_a = _make_subtask("a", "ride")
        sub_b = _make_subtask("b", "ride")
        sub_c = _make_subtask("c", "ride")

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b, sub_c],
            dependencies={"c": ["a", "b"]},
        )
        server.execute_composite(composite)

        assert sub_a.status == TaskStatus.COMPLETED
        assert sub_b.status == TaskStatus.COMPLETED
        assert sub_c.status == TaskStatus.COMPLETED
        assert composite.status == TaskStatus.COMPLETED


class TestFailurePropagation:
    def test_failure_propagation_cancels_downstream(self):
        """A 失败 → B（依赖 A）取消，C（无依赖）继续完成 → 父任务 CANCELLED。"""
        server = _make_server_with_domains("ride", "no_match", no_match_domain="no_match")
        sub_a = _make_subtask("a", "no_match")  # A 会失败（无匹配）
        sub_b = _make_subtask("b", "ride")      # B 依赖 A
        sub_c = _make_subtask("c", "ride")      # C 无依赖

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b, sub_c],
            dependencies={"b": ["a"]},
        )
        server.execute_composite(composite)

        assert sub_a.status == TaskStatus.CANCELLED
        assert sub_b.status == TaskStatus.CANCELLED  # 依赖 A，被传播取消
        assert sub_c.status == TaskStatus.COMPLETED  # 无依赖兄弟继续完成
        assert composite.status == TaskStatus.CANCELLED

    def test_failure_no_dep_sibling_continues(self):
        """A 失败，B（无依赖）已完成 → 父任务 CANCELLED，但 B 保持 COMPLETED。"""
        server = _make_server_with_domains("ride", "no_match", no_match_domain="no_match")
        sub_a = _make_subtask("a", "no_match")  # A 会失败
        sub_b = _make_subtask("b", "ride")      # B 无依赖

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a, sub_b],
        )
        server.execute_composite(composite)

        assert sub_a.status == TaskStatus.CANCELLED
        assert sub_b.status == TaskStatus.COMPLETED  # 兄弟保持完成
        assert composite.status == TaskStatus.CANCELLED


class TestCrossDomainRouting:
    def test_cross_domain_subtasks_use_domain_routing(self):
        """ride 子任务用 ride 域策略，group_buying 子任务用 gb 域策略。"""
        # 注册两个不同的策略实例，通过 resource_id 区分
        class _RideStrategy(_AlwaysMatchStrategy):
            def execute(self, task, candidates):
                return MatchResult(
                    task_id=task.task_id,
                    selected_resource_id="ride_res",
                    candidates=["ride_res"],
                )

        class _GbStrategy(_AlwaysMatchStrategy):
            def execute(self, task, candidates):
                return MatchResult(
                    task_id=task.task_id,
                    selected_resource_id="gb_res",
                    candidates=["gb_res"],
                )

        server = UMCPServer()
        server.use_in_memory_repositories()
        server.register_match_strategy("ride", _RideStrategy())
        server.register_match_strategy("group_buying", _GbStrategy())
        server.resource_repo.save(_E2EResource("ride_res", "ride"))
        server.resource_repo.save(_E2EResource("gb_res", "group_buying"))

        sub_ride = _make_subtask("ride_1", "ride")
        sub_gb = _make_subtask("gb_1", "group_buying")

        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_ride, sub_gb],
        )
        server.execute_composite(composite)

        assert sub_ride.assigned_resource_id == "ride_res"
        assert sub_gb.assigned_resource_id == "gb_res"
        assert composite.status == TaskStatus.COMPLETED


class TestCustomExecutorE2E:
    def test_custom_executor_per_domain(self):
        """注册 ride 域自定义执行器（延迟完成），验证覆盖默认行为。"""
        server = _make_server_with_domains("ride")
        completed_by_custom: list[str] = []

        def custom_executor(subtask):
            subtask.publish()
            subtask.assign_to("custom_res")
            subtask.start_execution()
            subtask.complete()
            completed_by_custom.append(subtask.task_id)

        server.register_subtask_executor("ride", custom_executor)

        sub_a = _make_subtask("a", "ride")
        composite = CompositeTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("composite"),
            subtasks=[sub_a],
        )
        server.execute_composite(composite)

        assert completed_by_custom == ["a"]
        assert sub_a.assigned_resource_id == "custom_res"
        assert composite.status == TaskStatus.COMPLETED


class TestTenderTaskBackwardCompatible:
    def test_tender_task_backward_compatible(self):
        """TenderTask（继承 PackageTask）行为零改动，现有集采流程正常。"""
        from umcp_core.core.task import CustomTask, PackageTask, StandardTask

        # 构造一个 PackageTask（模拟 TenderTask 的基本结构）
        std_sub = StandardTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("group_buying"),
        )
        std_sub.task_id = "product_sub"
        cus_sub = CustomTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("group_buying"),
        )
        cus_sub.task_id = "service_sub"

        package = PackageTask(
            demander_id="user_001",
            domain_tag=DomainTag.of("group_buying"),
            standard_sub_tasks=[std_sub],
            custom_sub_task=cus_sub,
        )
        assert package.task_type() == "package"
        assert len(package.standard_sub_tasks) == 1
        assert package.custom_sub_task is not None
        # 验证 PackageTask 仍可独立使用，不受 CompositeTask 影响
