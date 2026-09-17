"""支付超时自动清理 Worker。

每个调度周期扫描所有 PENDING 状态的支付记录：
- 若创建时间超过 `payment.timeout_seconds` → 调用网关关闭订单
- 同步取消关联的 deal 和 task（若 deal 仍处于 pending 状态）
- 发布 PAYMENT_CLOSED 事件
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from umcp_core.shared.payment.base import PaymentStatusEnum

logger = logging.getLogger(__name__)


class PaymentTimeoutWorker:
    """支付超时自动清理 worker。"""

    name = "payment_timeout"

    async def run(self, context: Any) -> None:
        server = context.get("server") if context else None
        if server is None:
            return

        rule_config = getattr(server, "rule_config", None)
        if rule_config is None:
            return

        timeout_seconds = rule_config.get(
            "payment.timeout_seconds", default=1800  # 默认 30 分钟
        )
        cleanup_interval = rule_config.get(
            "payment.cleanup_interval", default=60  # 默认 60 秒扫描一次
        )

        # 通过 created_at 粗筛：只处理超过 timeout_seconds 的记录
        now = datetime.utcnow()
        payment_service = getattr(server, "payment_service", None)
        if payment_service is None:
            return

        repo = getattr(payment_service, "repo", None)
        if repo is None:
            return

        try:
            pending_records = repo.find_by_status(PaymentStatusEnum.PENDING)
        except Exception:
            logger.exception("[PAY_TIMEOUT] find_by_status failed")
            return

        import time

        now_ts = time.time()
        # 只在 cleanup_interval 间隔内处理一次
        last_check = getattr(self, "_last_cleanup_ts", 0.0)
        if now_ts - last_check < cleanup_interval:
            return

        for record in pending_records:
            payment_id = record["payment_id"]
            deal_id = record.get("deal_id", "")
            created_at = record.get("created_at")

            if not created_at:
                continue

            # 确保 created_at 是 datetime
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except (ValueError, TypeError):
                    continue

            elapsed = (now - created_at).total_seconds()
            if elapsed < timeout_seconds:
                continue

            logger.info(
                "[PAY_TIMEOUT] timeout detected: payment_id=%s deal_id=%s elapsed=%.0fs timeout=%ss",
                payment_id, deal_id, elapsed, timeout_seconds,
            )

            # 1. 关闭支付订单
            gateway = getattr(payment_service, "_gateway", None)
            if gateway is not None:
                try:
                    gateway.close_payment(payment_id)
                    repo.update_status(payment_id, PaymentStatusEnum.FAILED)
                    logger.info("[PAY_TIMEOUT] payment closed: payment_id=%s", payment_id)
                except Exception as e:
                    logger.warning(
                        "[PAY_TIMEOUT] close payment failed(ignored): payment_id=%s error=%s",
                        payment_id, e,
                    )

            # 2. 取消关联的 deal 和 task
            if not deal_id:
                continue

            deal = server.deal_repo.find_by_id(deal_id)
            if deal is None:
                logger.warning("[PAY_TIMEOUT] deal not found: deal_id=%s", deal_id)
                continue

            # 仅取消 PENDING 状态的 deal
            if deal.status not in ("pending",):
                logger.info(
                    "[PAY_TIMEOUT] skip deal not in pending: deal_id=%s status=%s",
                    deal_id, deal.status,
                )
                continue

            try:
                deal.bind_event_bus(server.event_bus)
                deal.cancel()
                server.deal_repo.save(deal)
                logger.info("[PAY_TIMEOUT] deal cancelled: deal_id=%s", deal_id)
            except (RuntimeError, ValueError) as e:
                logger.warning(
                    "[PAY_TIMEOUT] cancel deal failed(ignored): deal_id=%s error=%s",
                    deal_id, e,
                )

            # 取消关联的 task
            task_id = getattr(deal, "task_id", None)
            if task_id:
                task = server.task_repo.find_by_id(task_id)
                if task is not None and task.status not in ("completed", "cancelled"):
                    try:
                        task.bind_event_bus(server.event_bus)
                        task.cancel()
                        server.task_repo.save(task)
                        logger.info(
                            "[PAY_TIMEOUT] task cancelled: task_id=%s deal_id=%s",
                            task_id, deal_id,
                        )
                    except (RuntimeError, ValueError) as e:
                        logger.warning(
                            "[PAY_TIMEOUT] cancel task failed(ignored): task_id=%s error=%s",
                            task_id, e,
                        )

        self._last_cleanup_ts = now_ts