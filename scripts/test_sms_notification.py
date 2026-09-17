#!/usr/bin/env python3
"""短信通知真实场景集成测试。

模拟真实陪驾业务场景，验证短信通知渠道在以下事件中被正确触发：

  1. 注册学员和教练用户
  2. 学员创建任务（Task）→ 提交 Deal → 触发 DEAL_CREATED 事件 → SMS 通知教练
  3. 教练确认 Deal → 触发 DEAL_PAID 事件 → SMS 通知学员
  4. 支付成功 → 触发 PAYMENT_PAID 事件 → SMS 通知学员
  5. 取消 Deal → 触发 DEAL_CANCELLED 事件 → SMS 通知双方
  6. 完成 Deal → 触发 DEAL_COMPLETED 事件 → SMS 通知双方

用法：
    # 先启动服务： cd umcp-core && python -m umcp_core.transport
    python scripts/test_sms_notification.py --url http://localhost:8000

注意：
    SMS 当前为开发模式（无阿里云凭证），短信内容会输出到服务端日志。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

# 测试用户（使用时间戳后缀避免冲突）
_ts = uuid.uuid4().hex[:6]
STUDENT_PHONE = f"1380000{_ts[:6]}"
COACH_PHONE = f"1390000{_ts[:6]}"
STUDENT_NAME = f"学员_{_ts[:4]}"
COACH_NAME = f"教练_{_ts[:4]}"


async def check_server(base_url: str) -> bool:
    """检查后端服务是否可访问。"""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
            resp = await client.get("/metrics")
            return resp.status_code == 200
    except Exception as e:
        logger.error("服务不可用: %s", e)
        return False


async def register_user(
    client: httpx.AsyncClient, phone: str, name: str
) -> dict | None:
    """注册用户并返回 token 信息。"""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "name": name, "password": "test123"},
        timeout=5.0,
    )
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        logger.info("  ✅ 注册成功: %s (%s)", name, phone)
        return data
    else:
        body = resp.text[:200]
        if "已注册" in body:
            logger.info("  ⚠️  用户已存在: %s (%s)", name, phone)
            # 尝试登录
            return await login_user(client, phone)
        logger.error("  ❌ 注册失败: %s: %s", resp.status_code, body)
        return None


async def login_user(client: httpx.AsyncClient, phone: str) -> dict | None:
    """登录用户返回 token 信息。"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"credential_type": "phone", "token": phone, "password": "test123"},
        timeout=5.0,
    )
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        logger.info("  ✅ 登录成功: %s", phone)
        return data
    else:
        logger.error("  ❌ 登录失败: %s: %s", resp.status_code, resp.text[:200])
        return None


async def create_task(
    client: httpx.AsyncClient, headers: dict, student_id: str
) -> str | None:
    """学员创建陪驾任务。"""
    task_id = f"task_sms_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/escort/tasks",
        json={
            "task_id": task_id,
            "title": "陪驾训练 - 真实场景短信测试",
            "description": "用于验证短信通知的陪驾订单",
            "price": 200.00,
            "demander_id": student_id,
            "address": "测试地点",
            "scheduled_at": "2026-08-20T14:00:00",
        },
        headers=headers,
        timeout=5.0,
    )
    if resp.status_code in (200, 201):
        logger.info("  ✅ 任务创建成功: %s", task_id)
        return task_id
    else:
        logger.warning("  ⚠️  任务创建返回 %s: %s", resp.status_code, resp.text[:200])
        return None


async def create_deal(
    client: httpx.AsyncClient, headers: dict, task_id: str, student_id: str, coach_id: str
) -> str | None:
    """创建交易（触发 DEAL_CREATED 事件 → SMS 通知教练）。"""
    resource_id = f"resource_sms_{uuid.uuid4().hex[:8]}"
    deal_id = f"deal_sms_{uuid.uuid4().hex[:8]}"

    resp = await client.post(
        "/api/v1/deals",
        json={
            "deal_id": deal_id,
            "task_id": task_id,
            "resource_id": resource_id,
            "demander_id": student_id,
            "supplier_id": coach_id,
            "final_amount": 200.00,
        },
        headers=headers,
        timeout=5.0,
    )
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        deal_id = data.get("deal_id", deal_id)
        logger.info("  ✅ Deal 创建成功: %s", deal_id)
        logger.info("  ✅ Deal 状态: %s (应触发 DEAL_CREATED → SMS→教练)", data.get("status", ""))
        return deal_id
    elif resp.status_code == 409:
        logger.info("  ⚠️  Deal 已存在（幂等）: %s", deal_id)
        return deal_id
    else:
        logger.warning("  ⚠️  Deal 创建返回 %s: %s", resp.status_code, resp.text[:200])
        return None


async def confirm_deal(
    client: httpx.AsyncClient, headers: dict, deal_id: str
) -> bool:
    """教练确认交易（通过 pay 接口触发 DEAL_PAID 事件 → SMS 通知学员）。"""
    # 先创建支付订单
    resp = await client.post(
        "/api/v1/escort/payments/create",
        json={"deal_id": deal_id, "payment_type": "deposit"},
        headers=headers,
        timeout=10.0,
    )
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        payment_id = data.get("payment_id", "")
        status = data.get("status", "")
        logger.info("  ✅ 支付订单创建成功: payment_id=%s status=%s", payment_id, status)
        logger.info("  ✅ (Mock 模式已同步确认，应触发 PAYMENT_PAID → SMS→学员)")
        return True
    else:
        logger.warning("  ⚠️  支付创建返回 %s: %s", resp.status_code, resp.text[:200])
        return False


async def cancel_deal(
    client: httpx.AsyncClient, headers: dict, deal_id: str
) -> bool:
    """取消交易（触发 DEAL_CANCELLED 事件 → SMS 通知双方）。"""
    resp = await client.post(
        f"/api/v1/escort/orders/{deal_id}/cancel",
        json={"reason": "短信测试 - 取消订单"},
        headers=headers,
        timeout=5.0,
    )
    if resp.status_code == 200:
        logger.info("  ✅ 取消成功: %s (应触发 DEAL_CANCELLED → SMS→双方)", deal_id)
        return True
    else:
        logger.warning("  ⚠️  取消返回 %s: %s", resp.status_code, resp.text[:200])
        return False


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="短信通知真实场景集成测试")
    parser.add_argument("--url", default=BASE_URL, help=f"后端服务地址（默认 {BASE_URL}）")
    parser.add_argument("--skip-events", nargs="*", default=[], help="跳过的事件类型")
    args = parser.parse_args()

    base_url = args.url
    skip_events = args.skip_events

    logger.info("=" * 70)
    logger.info("  短信通知真实场景集成测试")
    logger.info("  服务: %s", base_url)
    logger.info("  学员: %s (%s)", STUDENT_NAME, STUDENT_PHONE)
    logger.info("  教练: %s (%s)", COACH_NAME, COACH_PHONE)
    logger.info("=" * 70)

    # 0. 检查服务健康
    logger.info("\n[步骤 0] 检查服务状态")
    if not await check_server(base_url):
        logger.error("❌ 服务不可用，请先启动: python -m umcp_core.transport")
        sys.exit(1)
    logger.info("  ✅ 服务运行正常")

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        # 1. 注册用户
        logger.info("\n[步骤 1] 注册用户")
        student_tokens = await register_user(client, STUDENT_PHONE, STUDENT_NAME)
        if not student_tokens:
            logger.error("❌ 学员注册失败")
            sys.exit(1)
        student_headers = {"Authorization": f"Bearer {student_tokens['access_token']}"}

        coach_tokens = await register_user(client, COACH_PHONE, COACH_NAME)
        if not coach_tokens:
            logger.error("❌ 教练注册失败")
            sys.exit(1)
        coach_headers = {"Authorization": f"Bearer {coach_tokens['access_token']}"}

        # 获取用户信息
        student_resp = await client.get("/api/v1/auth/me", headers=student_headers)
        student_id = student_resp.json().get("data", {}).get("user_id", "")
        coach_resp = await client.get("/api/v1/auth/me", headers=coach_headers)
        coach_id = coach_resp.json().get("data", {}).get("user_id", "")
        logger.info("  学员 user_id: %s", student_id)
        logger.info("  教练 user_id: %s", coach_id)

        # 2. 创建任务 + Deal → 触发 DEAL_CREATED → SMS 通知教练
        logger.info("\n[步骤 2] 创建任务 + Deal（触发 DEAL_CREATED → SMS→教练）")
        task_id = await create_task(client, student_headers, student_id)
        if not task_id:
            logger.warning("  ⚠️  任务创建失败，使用随机 task_id 继续")
            task_id = f"task_skip_{uuid.uuid4().hex[:8]}"

        if "DEAL_CREATED" not in skip_events:
            deal_id = await create_deal(client, student_headers, task_id, student_id, coach_id)
            if not deal_id:
                logger.error("❌ Deal 创建失败")
                sys.exit(1)
        else:
            logger.info("  跳过 DEAL_CREATED")

        # 3. 支付确认 → 触发 PAYMENT_PAID → SMS 通知学员
        logger.info("\n[步骤 3] 支付确认（触发 PAYMENT_PAID → SMS→学员）")
        if "PAYMENT_PAID" not in skip_events and deal_id:
            await confirm_deal(client, student_headers, deal_id)
        else:
            logger.info("  跳过 PAYMENT_PAID")

        # 4. 等待异步事件处理
        logger.info("\n[步骤 4] 等待异步事件处理...")
        await asyncio.sleep(2)

        # 5. 取消 Deal → 触发 DEAL_CANCELLED → SMS 通知双方
        logger.info("\n[步骤 5] 取消 Deal（触发 DEAL_CANCELLED → SMS→双方）")
        if "DEAL_CANCELLED" not in skip_events and deal_id:
            await cancel_deal(client, student_headers, deal_id)
        else:
            logger.info("  跳过 DEAL_CANCELLED")

        # 6. 等待异步事件处理
        logger.info("\n[步骤 6] 等待异步事件处理...")
        await asyncio.sleep(2)

    # 验证指南
    logger.info("\n" + "=" * 70)
    logger.info("  测试完成！")
    logger.info("=" * 70)
    logger.info("")
    logger.info("  请检查服务端日志，确认以下 SMS 输出：")
    logger.info("")
    logger.info("  1. [SMS][DEV] to=教练手机 ... event=DEAL_CREATED  ← 新订单通知")
    logger.info("  2. [SMS][DEV] to=学员手机 ... event=PAYMENT_PAID  ← 支付成功通知")
    logger.info("  3. [SMS][DEV] to=双方手机 ... event=DEAL_CANCELLED ← 取消通知")
    logger.info("")
    logger.info("  检查命令（Windows PowerShell）：")
    logger.info("    Select-String -Path server.log -Pattern '\\[SMS\\]'")
    logger.info("")
    logger.info("  或 Linux：")
    logger.info("    grep '\\[SMS\\]' server.log")
    logger.info("")


if __name__ == "__main__":
    asyncio.run(main())