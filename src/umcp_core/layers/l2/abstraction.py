"""L2 需求与资源抽象层：任务工厂、资源注册表。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from umcp_core.core.domain import DomainTag
from umcp_core.core.resource import Resource
from umcp_core.core.task import Task


class TaskFactory(ABC):
    """任务工厂抽象。

    行业插件需提供具体实现，根据任务类型字符串创建对应的 Task 子类实例。
    """

    def __init__(self) -> None:
        self._builders: dict[str, Any] = {}

    def register_builder(self, task_type: str, builder: Any) -> None:
        """注册任务构造器。

        builder 可以是类（构造时调用 demander_id, domain_tag 等参数）或可调用对象。
        """
        self._builders[task_type] = builder

    @abstractmethod
    def create_task(
        self,
        task_type: str,
        demander_id: str,
        domain_tag: DomainTag,
        **kwargs: Any,
    ) -> Task:
        """根据任务类型创建实例。"""


class ResourceRegistry(ABC):
    """资源注册表抽象。"""

    @abstractmethod
    def register(self, resource: Resource) -> None:
        """资源上线注册。"""

    @abstractmethod
    def unregister(self, resource_id: str) -> None:
        """资源下线。"""

    @abstractmethod
    def find_by_id(self, resource_id: str) -> Resource | None:
        """按 ID 查找资源。"""

    @abstractmethod
    def find_available(self, domain_tag: DomainTag) -> list[Resource]:
        """查找某领域下所有可用资源。"""


class DefaultTaskFactory(TaskFactory):
    """默认任务工厂实现（内存注册表）。"""

    def create_task(
        self,
        task_type: str,
        demander_id: str,
        domain_tag: DomainTag,
        **kwargs: Any,
    ) -> Task:
        builder = self._builders.get(task_type)
        if builder is None:
            raise ValueError(f"未注册的任务类型: {task_type}")
        if isinstance(builder, type):
            return builder(demander_id=demander_id, domain_tag=domain_tag, **kwargs)
        return builder(demander_id=demander_id, domain_tag=domain_tag, **kwargs)
