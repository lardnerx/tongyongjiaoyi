"""实时单超时取消 + 扩展搜索范围 worker。

每个调度周期扫描所有 domain_tag=escort 且 status=published 的实时单：
- 若下单时间超过 `expand_after_seconds` 且未扩展过 → 再次广播抢单邀请（标记 expanded）
- 若下单时间超过 `timeout_seconds` → 自动 task.cancel()，发布 TASK_CANCELLED 事件
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from umcp_core.core.task import TaskStatus

logger = logging.getLogger(__name__)


class RealtimeCancelWorker:
    """实时单超时取消 worker。"""

    name = "escort_realtime_cancel"

    def __init__(self) -> None:
        # 记录已扩展过的 task_id，避免重复广播
        self._expanded_task_ids: set[str] = set()

    async def run(self, context: Any) -> None:
        server = context.get("server") if context else None
        if server is None:
            return

        rule_config = getattr(server, "rule_config", None)
        if rule_config is None:
            return

        timeout_seconds = rule_config.get(
            "escort.cancel.realtime.timeout_seconds", default=300
        )
        expand_after_seconds = rule_config.get(
            "escort.cancel.realtime.expand_after_seconds", default=30
        )

        now = datetime.utcnow()
        task_repo = server.task_repo
        if task_repo is None:
            return

        # 扫描所有 published 状态的 task（实时单在 published 等待抢单）
        published_tasks = task_repo.find_by_status(TaskStatus.PUBLISHED)
        for task in published_tasks:
            # 只处理陪驾 domain 的实时单
            if task.domain_tag.value != "escort":
                continue
            order_type = getattr(task, "order_type", None) or task.structured_fields.get("order_type")
            if order_type != "REALTIME":
                continue

            elapsed = (now - task.created_at).total_seconds()

            # 超时取消
            if elapsed >= timeout_seconds:
                try:
                    task.bind_event_bus(server.event_bus)
                    task.cancel()
                    task_repo.save(task)
                    logger.info("实时单 %s 超时自动取消（elapsed=%.1fs）", task.task_id, elapsed)
                except Exception:
                    logger.exception("取消实时单 %s 失败", task.task_id)
                # 已取消的从扩展集合中清理
                self._expanded_task_ids.discard(task.task_id)
                continue

            # 扩展搜索范围（未超时但超过 expand_after）
            if elapsed >= expand_after_seconds and task.task_id not in self._expanded_task_ids:
                manager = getattr(server, "ws_manager", None)
                if manager is not None:
                    message = {
                        "type": "task.published",
                        "timestamp": datetime.utcnow().isoformat(),
                        "data": {
                            "task_id": task.task_id,
                            "demander_id": task.demander_id,
                            "expanded": True,
                            "origin_lat": task.spatio_temporal.origin_lat if task.spatio_temporal else None,
                            "origin_lng": task.spatio_temporal.origin_lng if task.spatio_temporal else None,
                            "car_type": task.structured_fields.get("car_type"),
                            "origin_address": task.structured_fields.get("origin_address"),
                            "duration_hours": task.structured_fields.get("duration_hours"),
                            "coach_level_pref": task.structured_fields.get("coach_level_pref"),
                            "created_at": task.created_at.isoformat(),
                        },
                    }
                    try:
                        await manager.broadcast_to_online_suppliers(message)
                        self._expanded_task_ids.add(task.task_id)
                        logger.info("实时单 %s 扩展搜索范围（elapsed=%.1fs）", task.task_id, elapsed)
                    except Exception:
                        logger.exception("扩展搜索广播失败 task_id=%s", task.task_id)
