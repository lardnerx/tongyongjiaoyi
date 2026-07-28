"""测试 UMCPServer 生命周期与错误路径。

覆盖 src/umcp_core/server.py 的：
- start() / stop() 状态切换与必需组件校验
- start() 重复启动（警告但不抛错）
- load_plugin() 错误路径：不存在路径 / 缺 plugin.json / 无效模块名 / 模块缺 PLUGIN_MANIFEST
- set_repositories()：注入自定义仓储后 event_bus 订阅生效
"""

from __future__ import annotations

import pytest

from umcp_core.events.bus import Event
from umcp_core.events.types import EventType
from umcp_core.layers.l3 import InstantMatch
from umcp_core.layers.l4 import FixedPrice
from umcp_core.layers.l5 import WeightedSumTrustEngine
from umcp_core.repositories.in_memory import (
    InMemoryDealRepository,
    InMemoryEventRepository,
    InMemoryResourceRepository,
    InMemoryTaskRepository,
    InMemoryTrustRepository,
    InMemoryUserRepository,
)
from umcp_core.server import UMCPServer


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------


def _fully_configured_server() -> UMCPServer:
    """返回一个具备全部必需组件的 server（未启动）。"""
    server = UMCPServer()
    server.use_in_memory_repositories()
    server.set_match_strategy(InstantMatch())
    server.set_payment_schema(FixedPrice())
    server.set_trust_engine(WeightedSumTrustEngine())
    return server


# ----------------------------------------------------------------------
# start() 必需组件校验
# ----------------------------------------------------------------------


class TestStartValidation:
    def test_start_raises_when_all_components_missing(self):
        """新 server 未注入任何组件时应抛 RuntimeError，列出全部缺失项。"""
        server = UMCPServer()
        with pytest.raises(RuntimeError, match="协议栈启动缺少必需组件") as exc_info:
            server.start()
        message = str(exc_info.value)
        assert "match_strategy" in message
        assert "payment_schema" in message
        assert "trust_engine" in message
        assert "task_repo" in message

    def test_start_raises_when_match_strategy_missing(self):
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.set_payment_schema(FixedPrice())
        server.set_trust_engine(WeightedSumTrustEngine())
        with pytest.raises(RuntimeError, match="match_strategy"):
            server.start()

    def test_start_raises_when_payment_schema_missing(self):
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.set_match_strategy(InstantMatch())
        server.set_trust_engine(WeightedSumTrustEngine())
        with pytest.raises(RuntimeError, match="payment_schema"):
            server.start()

    def test_start_raises_when_trust_engine_missing(self):
        server = UMCPServer()
        server.use_in_memory_repositories()
        server.set_match_strategy(InstantMatch())
        server.set_payment_schema(FixedPrice())
        with pytest.raises(RuntimeError, match="trust_engine"):
            server.start()

    def test_start_raises_when_task_repo_missing(self):
        """仅缺 task_repo（其余组件齐备）时应抛 RuntimeError。"""
        server = UMCPServer()
        server.set_match_strategy(InstantMatch())
        server.set_payment_schema(FixedPrice())
        server.set_trust_engine(WeightedSumTrustEngine())
        # 不调用 use_in_memory_repositories / set_repositories
        with pytest.raises(RuntimeError, match="task_repo"):
            server.start()

    def test_start_succeeds_when_all_components_present(self):
        server = _fully_configured_server()
        server.start()
        assert server.is_running is True
        server.stop()


# ----------------------------------------------------------------------
# start() / stop() 状态切换
# ----------------------------------------------------------------------


class TestStartStopLifecycle:
    def test_start_sets_running_flag(self):
        server = _fully_configured_server()
        assert server.is_running is False
        server.start()
        assert server.is_running is True
        server.stop()

    def test_start_twice_does_not_raise(self):
        """重复启动应仅打印警告，不抛错，不改变状态。"""
        server = _fully_configured_server()
        server.start()
        # 第二次启动不应抛异常
        server.start()
        assert server.is_running is True
        server.stop()

    def test_stop_clears_running_flag(self):
        server = _fully_configured_server()
        server.start()
        assert server.is_running is True
        server.stop()
        assert server.is_running is False

    def test_stop_when_not_started_is_noop(self):
        """未启动时调用 stop 不应抛错。"""
        server = UMCPServer()
        server.stop()
        assert server.is_running is False

    def test_restart_after_stop(self):
        server = _fully_configured_server()
        server.start()
        server.stop()
        # 停止后应能再次启动
        server.start()
        assert server.is_running is True
        server.stop()


# ----------------------------------------------------------------------
# load_plugin() 错误路径
# ----------------------------------------------------------------------


class TestLoadPluginErrors:
    def test_load_plugin_nonexistent_path_raises_filenotfound(self):
        """不存在的路径（含分隔符）应抛 FileNotFoundError。"""
        server = UMCPServer()
        with pytest.raises(FileNotFoundError, match="无法定位插件"):
            server.load_plugin("nonexistent_dir/plugin.json")

    def test_load_plugin_missing_manifest_file_raises_filenotfound(self, tmp_path):
        """目录存在但缺少 plugin.json 应抛 FileNotFoundError。"""
        server = UMCPServer()
        # tmp_path 是真实目录但无 plugin.json
        with pytest.raises(FileNotFoundError, match="插件描述文件不存在"):
            server.load_plugin(str(tmp_path))

    def test_load_plugin_invalid_module_raises_importerror(self):
        """无效的 Python 模块名应抛 ImportError。"""
        server = UMCPServer()
        with pytest.raises(ImportError, match="无法导入插件模块"):
            server.load_plugin("definitely_not_a_real_module_xyz123")

    def test_load_plugin_module_without_manifest_raises_attributeerror(self):
        """模块存在但缺少 PLUGIN_MANIFEST 属性应抛 AttributeError。"""
        server = UMCPServer()
        # os 模块存在但无 PLUGIN_MANIFEST
        with pytest.raises(AttributeError, match="缺少 PLUGIN_MANIFEST"):
            server.load_plugin("os")


# ----------------------------------------------------------------------
# set_repositories() 注入与 event_bus 订阅
# ----------------------------------------------------------------------


class TestSetRepositories:
    def test_set_repositories_injects_all_repos(self):
        server = UMCPServer()
        task_repo = InMemoryTaskRepository()
        resource_repo = InMemoryResourceRepository()
        deal_repo = InMemoryDealRepository()
        user_repo = InMemoryUserRepository()
        trust_repo = InMemoryTrustRepository()
        event_repo = InMemoryEventRepository()

        server.set_repositories(
            task_repo=task_repo,
            resource_repo=resource_repo,
            deal_repo=deal_repo,
            user_repo=user_repo,
            trust_repo=trust_repo,
            event_repo=event_repo,
        )
        assert server.task_repo is task_repo
        assert server.resource_repo is resource_repo
        assert server.deal_repo is deal_repo
        assert server.user_repo is user_repo
        assert server.trust_repo is trust_repo
        assert server.event_repo is event_repo

    def test_set_repositories_subscribes_event_bus_to_event_repo(self):
        """注入自定义 event_repo 后，event_bus 发布的事件应落库到 event_repo。"""
        server = UMCPServer()
        event_repo = InMemoryEventRepository()
        server.set_repositories(
            task_repo=InMemoryTaskRepository(),
            resource_repo=InMemoryResourceRepository(),
            deal_repo=InMemoryDealRepository(),
            user_repo=InMemoryUserRepository(),
            trust_repo=InMemoryTrustRepository(),
            event_repo=event_repo,
        )

        # 发布一个事件
        event = Event(
            type=EventType.TASK_PUBLISHED,
            source_layer="L2",
            payload={"task_id": "t1"},
        )
        server.event_bus.publish(event)

        # event_repo 应收到该事件
        replayed = event_repo.replay()
        assert len(replayed) == 1
        assert replayed[0].type == EventType.TASK_PUBLISHED
        assert replayed[0].payload["task_id"] == "t1"

    def test_set_repositories_supports_start(self):
        """注入完整仓储后配合必需组件应能成功启动。"""
        server = UMCPServer()
        server.set_repositories(
            task_repo=InMemoryTaskRepository(),
            resource_repo=InMemoryResourceRepository(),
            deal_repo=InMemoryDealRepository(),
            user_repo=InMemoryUserRepository(),
            trust_repo=InMemoryTrustRepository(),
            event_repo=InMemoryEventRepository(),
        )
        server.set_match_strategy(InstantMatch())
        server.set_payment_schema(FixedPrice())
        server.set_trust_engine(WeightedSumTrustEngine())
        server.start()
        assert server.is_running is True
        server.stop()
