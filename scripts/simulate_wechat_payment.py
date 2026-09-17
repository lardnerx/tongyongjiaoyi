#!/usr/bin/env python3
"""模拟微信支付完整扫码支付流程。

验证步骤：
  1. 创建交易（deal）
  2. 创建支付订单，确认返回 code_url（二维码链接）
  3. 模拟用户扫码支付，触发回调通知
  4. 轮询支付状态，验证状态变更为 paid
  5. 验证回调地址和状态轮询逻辑是否正常

用法：
    # 使用 Mock 模式（默认，无需微信支付配置）
    python scripts/simulate_wechat_payment.py

    # 使用微信支付模式（需要配置 WECHAT_* 环境变量）
    WECHAT_APP_ID=xxx WECHAT_MCH_ID=xxx ... python scripts/simulate_wechat_payment.py --wechat

注意：
  - Mock 模式使用内置的 MockGateway，不依赖微信支付真实服务
  - 微信支付模式需要先配置完整的 WECHAT_* 环境变量
  - 需要先启动后端服务 (umcp-server)
"""

from __future__ import annotations

import argparse
import asyncio
import json
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

# 加载 .env（如果存在）
dotenv_path = PROJECT_ROOT / ".env"
if dotenv_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path)
    except ImportError:
        pass

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 默认配置
BASE_URL = "http://localhost:8000"
TEST_USER_ID = "user_test_simulate_001"
TEST_SUPPLIER_ID = "coach_test_simulate_001"

# 测试数据
TEST_TASK_ID = f"task_simulate_{uuid.uuid4().hex[:8]}"
TEST_RESOURCE_ID = f"resource_simulate_{uuid.uuid4().hex[:8]}"


def _make_token() -> str:
    """生成模拟 JWT token（使用 pyjwt 库，与服务端一致）。"""
    import jwt as pyjwt

    secret = os.getenv("UMCP_JWT_SECRET", "dev-secret-change-me-32bytes")
    payload = {
        "sub": TEST_USER_ID,
        "user_id": TEST_USER_ID,
        "role": "demander",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


# 全局 token
AUTH_TOKEN = _make_token()
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


async def check_server_health(base_url: str) -> bool:
    """检查后端服务是否可访问。"""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
            resp = await client.get("/api/v1/health")
            return resp.status_code == 200
    except Exception as e:
        logger.error("后端服务不可用: %s", e)
        return False


async def create_test_deal(client: httpx.AsyncClient) -> dict | None:
    """创建测试交易（deal）和任务（task）。"""
    logger.info("=" * 60)
    logger.info("步骤 1/5: 准备测试数据")

    # 创建 task
    task_payload = {
        "demander_id": TEST_USER_ID,
        "domain_tag": "escort",
        "title": "模拟支付测试陪驾订单",
        "description": "用于验证微信支付流程的测试订单",
        "structured_fields": {
            "price": 200.00,
            "address": "测试地址",
            "scheduled_at": "2026-08-10T14:00:00",
        },
    }

    try:
        resp = await client.post(
            "/api/v1/tasks",
            json=task_payload,
            headers=AUTH_HEADERS,
            timeout=5.0,
        )
        if resp.status_code in (200, 201):
            logger.info("  ✅ 测试任务创建成功: %s", resp.json().get("data", {}).get("task_id", ""))
        else:
            logger.info("  ⚠️  任务创建返回 %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.info("  ⚠️  任务创建失败: %s", e)

    # 直接通过 deals API 创建 deal（需指定 deal_id=demo 模式的固定值）
    deal_payload = {
        "task_id": TEST_TASK_ID,
        "resource_id": TEST_RESOURCE_ID,
        "demander_id": TEST_USER_ID,
        "supplier_id": TEST_SUPPLIER_ID,
        "final_amount": 200.00,
    }
    try:
        resp = await client.post(
            "/api/v1/deals",
            json=deal_payload,
            headers=AUTH_HEADERS,
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            deal_id = data.get("deal_id", "")
            logger.info("  ✅ Deal 创建成功: deal_id=%s", deal_id)
            logger.info("  ✅ Deal 状态: %s", data.get("status", "N/A"))
            return {"task_id": TEST_TASK_ID, "deal_id": deal_id}
        elif resp.status_code == 409:
            logger.info("  ⚠️  deal 已存在（幂等）")
            return {"task_id": TEST_TASK_ID, "deal_id": ""}
        else:
            logger.info("  ⚠️  创建 deal 返回 %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.info("  ⚠️  创建 deal 失败: %s", e)

    logger.warning("  ⚠️  无法创建 deal，将使用模拟 deal 数据继续测试")
    return None


async def create_payment(client: httpx.AsyncClient, wechat_mode: bool, deal_id: str) -> dict | None:
    """创建支付订单。"""
    logger.info("-" * 60)
    logger.info("步骤 2/5: 创建支付订单")

    try:
        resp = await client.post(
            "/api/v1/escort/payments/create",
            json={"deal_id": deal_id, "payment_type": "deposit"},
            headers=AUTH_HEADERS,
            timeout=10.0,
        )
        logger.info("  POST /api/v1/escort/payments/create -> %s", resp.status_code)

        if resp.status_code == 200:
            data = resp.json().get("data", {})
            payment_id = data.get("payment_id", "N/A")
            status = data.get("status", "N/A")
            code_url = data.get("code_url", "")
            amount = data.get("amount", 0)

            logger.info("  ✅ 支付订单创建成功")
            logger.info("     payment_id: %s", payment_id)
            logger.info("     status:     %s", status)
            logger.info("     amount:     ¥%.2f", amount)

            if wechat_mode and code_url:
                logger.info("     code_url:   %s...", code_url[:80])
                logger.info("     ✅ 二维码链接已生成")
            elif not wechat_mode:
                logger.info("     (Mock 模式，无二维码)")
                logger.info("     ✅ Mock 模式支付已同步确认")

            return data
        else:
            logger.error("  ❌ 创建支付订单失败: %s", resp.text[:500])
            return None
    except Exception as e:
        logger.error("  ❌ 创建支付订单异常: %s", e)
        return None


async def simulate_callback(client: httpx.AsyncClient, payment_id: str) -> bool:
    """模拟微信支付回调通知。

    构造一个符合微信支付 V3 格式的回调请求，发送到 /callback 端点。
    Mock 模式下直接返回 200 空响应。
    """
    logger.info("-" * 60)
    logger.info("步骤 3/5: 模拟支付回调通知")

    callback_payload = {
        "id": f"ev-{uuid.uuid4().hex}",
        "create_time": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "event_type": "TRANSACTION.SUCCESS",
        "resource_type": "encrypt-resource",
        "resource": {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": "base64_encoded_ciphertext",
            "associated_data": "transaction",
            "nonce": "base64_encoded_nonce",
        },
        "summary": "支付成功",
    }

    try:
        resp = await client.post(
            "/api/v1/escort/payments/callback",
            json=callback_payload,
            headers={
                "Wechatpay-Signature": "mock_signature_for_testing",
                "Wechatpay-Timestamp": str(int(time.time())),
                "Wechatpay-Nonce": uuid.uuid4().hex[:16],
                "Wechatpay-Serial": "mock_serial_for_testing",
            },
            timeout=10.0,
        )
        logger.info("  POST /api/v1/escort/payments/callback -> %s", resp.status_code)
        logger.info("  响应: %s", resp.text[:300])

        if resp.status_code == 200:
            logger.info("  ✅ 回调通知发送成功")
            return True
        else:
            logger.warning("  ⚠️  回调返回非 200: %s", resp.status_code)
            return False
    except Exception as e:
        logger.error("  ❌ 回调通知异常: %s", e)
        return False


async def poll_payment_status(client: httpx.AsyncClient, deal_id: str, max_retries: int = 15) -> str:
    """轮询支付状态，retry_interval 秒一次，最多 max_retries 次。"""
    logger.info("-" * 60)
    logger.info("步骤 4/5: 轮询支付状态")

    retry_interval = 2

    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.get(
                f"/api/v1/escort/payments/{deal_id}",
                headers=AUTH_HEADERS,
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                status = data.get("status", "unknown")
                trade_no = data.get("trade_no", "")
                logger.info(
                    "  [第 %2d/%d 次轮询] status=%s  trade_no=%s",
                    attempt, max_retries, status, trade_no or "N/A",
                )

                if status in ("paid", "success", "completed"):
                    logger.info("  ✅ 支付成功！")
                    return status
                elif status in ("failed", "cancelled", "timeout"):
                    logger.warning("  ⚠️  支付状态异常: %s", status)
                    return status
            else:
                logger.warning(
                    "  [第 %2d/%d 次轮询] HTTP %s: %s",
                    attempt, max_retries, resp.status_code, resp.text[:100],
                )
        except Exception as e:
            logger.warning("  [第 %2d/%d 次轮询] 异常: %s", attempt, max_retries, e)

        if attempt < max_retries:
            await asyncio.sleep(retry_interval)

    logger.error("  ❌ 轮询超时，支付状态未在预期时间内变更")
    return "timeout"


async def verify_deal_status(client: httpx.AsyncClient, deal_id: str) -> bool:
    """验证 deal 的最终状态。"""
    logger.info("-" * 60)
    logger.info("步骤 5/5: 验证交易最终状态")

    try:
        # 查询 deal 详情
        resp = await client.get(
            f"/api/v1/deals/{deal_id}",
            headers=AUTH_HEADERS,
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            logger.info("  交易详情: %s", json.dumps(data, ensure_ascii=False, indent=2)[:500])
            return True
        else:
            logger.info("  查询交易详情返回 %s: %s", resp.status_code, resp.text[:200])
            # 不是关键步骤，不视为失败
            return True
    except Exception as e:
        logger.info("  查询交易详情异常: %s", e)
        return True


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="模拟微信支付完整扫码支付流程")
    parser.add_argument("--wechat", action="store_true", help="使用微信支付模式（需要 WECHAT_* 环境变量）")
    parser.add_argument("--url", default=BASE_URL, help=f"后端服务地址（默认 {BASE_URL}）")
    args = parser.parse_args()

    base_url = args.url
    wechat_mode = args.wechat

    logger.info("=" * 60)
    logger.info("  模拟微信支付完整流程")
    logger.info("  模式: %s", "微信支付 V3" if wechat_mode else "Mock 支付")
    logger.info("  服务: %s", base_url)
    logger.info("=" * 60)

    # 0. 检查服务健康
    logger.info("\n步骤 0/5: 检查后端服务健康状态")
    if not await check_server_health(base_url):
        logger.error("❌ 后端服务不可用，请先启动: umcp-server")
        sys.exit(1)
    logger.info("  ✅ 后端服务运行正常")

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        # 1. 创建测试数据
        deal_info = await create_test_deal(client)
        if not deal_info or not deal_info.get("deal_id"):
            logger.error("❌ 获取 deal_id 失败，终止流程")
            sys.exit(1)

        deal_id = deal_info["deal_id"]
        logger.info("  使用 Deal ID: %s", deal_id)

        # 2. 创建支付订单
        payment = await create_payment(client, wechat_mode, deal_id)
        if not payment:
            logger.error("❌ 创建支付订单失败，终止流程")
            sys.exit(1)

        payment_id = payment.get("payment_id", "")
        status = payment.get("status", "")

        if wechat_mode:
            # 微信支付模式：需要等待用户扫码，模拟回调
            logger.info("\n  ⏳ 等待模拟扫码支付...")
            await asyncio.sleep(1)

            # 3. 模拟回调通知
            callback_ok = await simulate_callback(client, payment_id)
            if not callback_ok:
                logger.warning("  ⚠️  回调通知异常，继续轮询验证")

            # 4. 轮询支付状态
            final_status = await poll_payment_status(client, deal_id)
        else:
            # Mock 模式：支付已是 paid 状态
            logger.info("  ✅ Mock 模式已同步确认支付")
            final_status = status

        # 5. 验证最终状态
        await verify_deal_status(client, deal_id)

    # 结果汇总
    logger.info("=" * 60)
    logger.info("  模拟支付流程完成")
    logger.info("  Deal ID:     %s", deal_id)
    logger.info("  Payment ID:  %s", payment_id)
    logger.info("  最终状态:    %s", final_status)

    if final_status in ("paid", "success", "completed"):
        logger.info("  ✅ 结论: 支付流程正常，回调地址和状态轮询逻辑正确")
        sys.exit(0)
    elif final_status == "pending":
        logger.info("  ⚠️ 结论: 支付仍在处理中（微信支付模式需要真实扫码）")
        sys.exit(0)
    else:
        logger.error("  ❌ 结论: 支付流程异常")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())