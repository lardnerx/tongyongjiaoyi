"""UMCP-Core: 通用市场协调协议核心库。

双边市场交易协调引擎，包含七层协议栈骨架、状态机、事件总线、核心抽象类与策略接口。
本库只包含接口定义与抽象实现，不包含任何具体行业的实现。
"""

from umcp_core.core.base import Demander, Role, Supplier, User
from umcp_core.core.deal import Deal, DealStatus
from umcp_core.core.domain import Attachment, DomainTag, SpatioTemporalConstraint
from umcp_core.core.resource import Capability, Resource, ResourceStatus
from umcp_core.core.task import (
    CustomTask,
    PackageTask,
    StandardTask,
    Task,
    TaskStatus,
)
from umcp_core.events.bus import EventBus, EventHandler, Event
from umcp_core.events.types import EventType
from umcp_core.fsm.deal_fsm import DealStateMachine
from umcp_core.fsm.task_fsm import TaskStateMachine
from umcp_core.protocol.primitives import (
    Confirm,
    Indication,
    LayerId,
    LayerProtocol,
    Request,
    Response,
)
from umcp_core.server import UMCPServer

__version__ = "2.0.0"

__all__ = [
    # 核心抽象
    "User",
    "Role",
    "Demander",
    "Supplier",
    "Task",
    "StandardTask",
    "CustomTask",
    "PackageTask",
    "TaskStatus",
    "Resource",
    "Capability",
    "ResourceStatus",
    "Deal",
    "DealStatus",
    "DomainTag",
    "Attachment",
    "SpatioTemporalConstraint",
    # 事件总线
    "EventBus",
    "EventHandler",
    "Event",
    "EventType",
    # 状态机
    "TaskStateMachine",
    "DealStateMachine",
    # 层间协议
    "Request",
    "Confirm",
    "Indication",
    "Response",
    "LayerId",
    "LayerProtocol",
    # 服务器
    "UMCPServer",
]
