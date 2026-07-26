"""层间协议原语：请求、确认、指示、响应。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")
E = TypeVar("E")


class LayerId(str, Enum):
    """七层协议栈层标识。"""

    L1_ACCESS = "L1"
    L2_ABSTRACTION = "L2"
    L3_MATCHING = "L3"
    L4_TRANSACTION = "L4"
    L5_TRUST = "L5"
    L6_INTELLIGENCE = "L6"
    L7_GOVERNANCE = "L7"


@dataclass
class Request(Generic[T]):
    """请求原语：上层向下层请求服务。"""

    target_layer: LayerId
    source_layer: LayerId
    operation: str
    payload: T | None = None
    request_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")


@dataclass
class Confirm(Generic[R]):
    """确认原语：下层向上层返回处理结果。"""

    source_layer: LayerId
    target_layer: LayerId
    request_id: str
    success: bool = True
    result: R | None = None
    error: str | None = None


@dataclass
class Indication(Generic[E]):
    """指示原语：下层主动向上层推送事件。"""

    source_layer: LayerId
    target_layer: LayerId
    event_type: str
    payload: E | None = None
    indication_id: str = field(default_factory=lambda: f"ind_{uuid.uuid4().hex[:12]}")


@dataclass
class Response:
    """响应原语：上层收到指示后的应答。"""

    source_layer: LayerId
    target_layer: LayerId
    indication_id: str
    success: bool = True
    message: str = ""


class LayerProtocol(ABC):
    """层间协议接口。

    每一层实现此接口，通过统一原语与其他层通信，避免直接依赖。
    """

    layer_id: LayerId

    @abstractmethod
    def send_request(self, target: LayerId, operation: str, payload: Any = None) -> Request:
        """向上层发送请求。"""

    @abstractmethod
    def send_indication(self, target: LayerId, event_type: str, payload: Any = None) -> Indication:
        """向上层发送指示。"""

    @abstractmethod
    def on_request(self, request: Request) -> Confirm:
        """处理收到的请求。"""

    @abstractmethod
    def on_indication(self, indication: Indication) -> Response:
        """处理收到的指示。"""
