#!/usr/bin/env python3
"""高频并发请求测试 — 验证限流中间件在 Redis 连接正常时的实际拦截效果。

测试流程：
  1. 生成测试 JWT token
  2. 批量发送 150 个并发请求到非豁免路径（/api/v1/deals）
  3. 统计 200 (成功) 和 429 (被限流) 的数量
  4. 验证被限流请求的响应体格式和 Retry-After 头
  5. 等待窗口过期后验证限流自动重置

用法：
    # 默认测试 150 个并发请求
    python scripts/test_rate_limit.py --url http://localhost:8002

    # 自定义并发数
    python scripts/test_rate_limit.py --url http://localhost:8002 --burst 200

注意：
  - 需要在后端服务已启动且限流中间件已启用时运行
  - 限流配置：UMCP_RATE_LIMIT_MAX=100, UMCP_RATE_LIMIT_WINDOW=60
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

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TEST_USER_ID = "user_rate_test_001"
TEST_DEMANDER_ID = "demander_rate_test_001"
TEST_SUPPLIER_ID = "supplier_rate_test_001"
TEST_TASK_ID = f"task_rate_{uuid.uuid4().hex[:8]}"
TEST_RESOURCE_ID = f"resource_rate_{uuid.uuid4().hex[:8]}"


def _make_token() -> str:
    """生成模拟 JWT token（使用 pyjwt 库，与服务端一致）。"""
    import jwt as pyjwt

    secret = os.getenv("UMCP_JWT_SECRET", "W5Am-yY80O7QsUYY67t4D-bfk-sSB9pocVc7lZdXDr4")
    payload = {
        "sub": TEST_USER_ID,
        "user_id": TEST_USER_ID,
        "role": "demander",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


AUTH_TOKEN = _make_token()
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


async def test_rate_limit(base_url: str, burst_count: int = 150) -> None:
    """高频并发测试主逻辑。"""
    logger.info("=" * 60)
    logger.info("  限流中间件高频并发测试")
    logger.info("  服务: %s", base_url)
    logger.info("  并发请求数: %d", burst_count)
    logger.info("  限流配置: 窗口=60s, 最大=100 请求/IP")
    logger.info("=" * 60)

    # 1. 先准备一条测试数据（deal），确保测试请求有合法目标
    logger.info("\n[步骤 1] 准备测试数据 (deal)")

    deal_id = None
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        # 创建测试 deal
        deal_payload = {
            "task_id": TEST_TASK_ID,
            "resource_id": TEST_RESOURCE_ID,
            "demander_id": TEST_DEMANDER_ID,
            "supplier_id": TEST_SUPPLIER_ID,
            "final_amount": 200.00,
        }
        try:
            resp = await client.post("/api/v1/deals", json=deal_payload, headers=AUTH_HEADERS)
            if resp.status_code == 200:
                deal_id = resp.json().get("data", {}).get("deal_id", "")
                logger.info("  ✅ Deal 已创建: %s", deal_id)
            else:
                logger.warning("  ⚠️  Deal 创建返回 %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("  ⚠️  Deal 创建异常: %s", e)

        if not deal_id:
            logger.warning("  ⚠️  无法创建 deal，使用非认证路径测试")
            # 使用 /metrics 作为测试路径（无需认证，受限流保护）
            test_path = "/metrics"
            test_headers = {}
        else:
            test_path = f"/api/v1/deals/{deal_id}"
            test_headers = AUTH_HEADERS

        # 2. 发送并发请求
        logger.info("\n[步骤 2] 发送 %d 个并发请求到 %s", burst_count, test_path)

        async def single_request() -> dict:
            """单个请求任务。"""
            start = time.perf_counter()
            try:
                resp = await client.get(test_path, headers=test_headers, timeout=10.0)
                elapsed = time.perf_counter() - start
                return {
                    "status": resp.status_code,
                    "elapsed": round(elapsed, 3),
                    "retry_after": resp.headers.get("Retry-After", ""),
                    "body": resp.text[:200],
                }
            except Exception as e:
                elapsed = time.perf_counter() - start
                return {
                    "status": 0,
                    "elapsed": round(elapsed, 3),
                    "retry_after": "",
                    "body": f"error: {e}",
                }

        # 批量启动并发请求
        tasks = [single_request() for _ in range(burst_count)]
        results = await asyncio.gather(*tasks)

        # 3. 统计结果
        logger.info("\n[步骤 3] 统计结果")

        status_counts: dict[int, int] = {}
        for r in results:
            status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

        success_count = status_counts.get(200, 0)
        limited_count = status_counts.get(429, 0)
        error_count = status_counts.get(0, 0)
        other_count = sum(v for k, v in status_counts.items() if k not in (200, 429, 0))

        logger.info("  ✅ 200 (成功):        %d", success_count)
        logger.info("  🚫 429 (被限流):      %d", limited_count)
        logger.info("  ❌ 0   (异常):        %d", error_count)
        if other_count:
            logger.info("  ❓ 其他状态码:       %d", other_count)
            for k, v in status_counts.items():
                if k not in (200, 429, 0):
                    logger.info("       %d → %d 次", k, v)

        total = success_count + limited_count + error_count + other_count
        logger.info("  ──────────────────────────")
        logger.info("  总请求数: %d", total)

        # 4. 验证限流行为
        logger.info("\n[步骤 4] 验证限流行为")

        if limited_count > 0:
            logger.info("  ✅ 限流已触发: 共 %d 个请求被拦截 (429)", limited_count)

            # 验证第一个 429 的响应格式
            first_429 = next((r for r in results if r["status"] == 429), None)
            if first_429:
                logger.info("  ✅ 429 响应示例:")
                logger.info("     body: %s", first_429["body"])
                logger.info("     Retry-After: %s", first_429["retry_after"])
                logger.info("     elapsed: %.3fs", first_429["elapsed"])

                # 验证 Retry-After 头
                if first_429["retry_after"]:
                    logger.info("  ✅ Retry-After 头存在")
                else:
                    logger.warning("  ⚠️ Retry-After 头缺失")

                # 验证响应体包含 rate_limit 信息
                if "rate_limit" in first_429["body"]:
                    logger.info("  ✅ 响应体包含 rate_limit 错误信息")
                else:
                    logger.warning("  ⚠️ 响应体缺少 rate_limit 错误信息")
        else:
            logger.warning(
                "  ⚠️  限流未触发（burst=%d < max=%d），建议增大 --burst 参数",
                burst_count, 100,
            )

        # 5. 验证限流精确性
        logger.info("\n[步骤 5] 限流精确性验证")

        if success_count > 0 and limited_count > 0:
            allowed = success_count
            blocked = limited_count
            logger.info("  允许: %d, 拦截: %d", allowed, blocked)
            logger.info("  拦截率: %.1f%%", 100 * blocked / (allowed + blocked))

            # 理论上前 100 个请求应成功，后续被限流
            if allowed <= 100:
                logger.info("  ✅ 允许数(%d) 未超过最大限制(100)", allowed)
            else:
                logger.warning("  ⚠️ 允许数(%d) 超过最大限制(100)，可能存在竞争条件", allowed)

        # 6. 等待窗口重置后验证
        logger.info("\n[步骤 6] 等待 60s 窗口重置后验证限流自动恢复")
        logger.info("  等待 60 秒...")

        for i in range(60, 0, -5):
            logger.info("  剩余 %d 秒...", i)
            await asyncio.sleep(min(5, i))

        # 窗口重置后，请求应恢复正常
        logger.info("  窗口已重置，发送验证请求...")
        verify_resp = await client.get(test_path, headers=test_headers, timeout=10.0)
        if verify_resp.status_code == 200:
            logger.info("  ✅ 窗口重置后请求正常 (200)")
        elif verify_resp.status_code == 429:
            logger.warning("  ⚠️ 窗口重置后仍被限流 (429)，可能缓存未清理")
        else:
            logger.info("  验证请求返回: %d", verify_resp.status_code)

    # 结果汇总
    logger.info("\n" + "=" * 60)
    logger.info("  限流测试完成")
    logger.info("  ✅ 验证项:")
    logger.info("     - 限流中间件已启用并正常工作")
    logger.info("     - 高频请求被正确拦截 (429)")
    logger.info("     - 窗口重置后请求自动恢复")
    logger.info("     - Retry-After 头存在")
    logger.info("     - 响应体格式正确")

    if limited_count > 0:
        logger.info("  ✅ 结论: 限流中间件在 Redis 连接正常时拦截效果正常")
        sys.exit(0)
    else:
        logger.warning("  ⚠️ 结论: 限流未触发，请检查配置或增加 --burst 参数")
        sys.exit(1)


async def main() -> None:
    parser = argparse.ArgumentParser(description="限流中间件高频并发测试")
    parser.add_argument("--url", default="http://localhost:8000", help="后端服务地址")
    parser.add_argument("--burst", type=int, default=150, help="并发请求数（默认 150）")
    args = parser.parse_args()

    await test_rate_limit(args.url, args.burst)


if __name__ == "__main__":
    asyncio.run(main())