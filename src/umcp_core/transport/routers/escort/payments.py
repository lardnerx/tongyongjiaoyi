"""陪驾支付 router。

支持两种支付网关：
  - Mock 网关（开发模式）：同步创建 + 确认
  - 微信支付 V3（生产模式）：创建 → 用户扫码 → 异步回调 → 确认
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from umcp_core.core.base import User
from umcp_core.core.deal import DealStatus
from umcp_core.server import UMCPServer
from umcp_core.shared.payment.base import PaymentStatusEnum, PaymentType
from umcp_core.shared.payment.wechat import WechatPayGateway
from umcp_core.transport.deps import get_current_user, get_server
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/escort/payments", tags=["escort-payments"])


class CreatePayRequest(BaseModel):
    deal_id: str
    payment_type: str = "deposit"  # deposit | balance | full


class PaymentInfo(BaseModel):
    payment_id: str
    deal_id: str
    user_id: str
    amount: float
    payment_type: str
    status: str
    trade_no: str | None = None
    code_url: str | None = None  # 微信支付 Native 二维码 URL


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _get_payment_service(server: UMCPServer) -> Any:
    """获取支付服务，不存在则抛异常。"""
    svc = getattr(server, "payment_service", None)
    if svc is None:
        raise IllegalStateError(message="支付服务未注册")
    return svc


def _compute_deposit_amount(deal: Any) -> float:
    """计算定金金额（总价 * 30%）。"""
    amount = round((deal.final_amount or 0.0) * 0.3, 2)
    if amount <= 0:
        raise IllegalStateError(message="支付金额必须大于 0")
    return amount


def _is_wechat_gateway(server: UMCPServer) -> bool:
    """判断当前支付网关是否为微信支付。"""
    svc = getattr(server, "payment_service", None)
    if svc is None:
        return False
    return isinstance(svc._gateway, WechatPayGateway)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.post("/create", response_model=Envelope)
async def create_payment(
    req: CreatePayRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """创建支付订单。

    微信支付模式：返回 code_url（二维码链接），前端展示二维码供用户扫码。
    Mock 模式：同步创建并确认支付，直接返回已支付状态。
    """
    logger.info("[PAY_CREATE] entry: deal_id=%s payment_type=%s user=%s",
                req.deal_id, req.payment_type, current_user.user_id)

    deal = server.deal_repo.find_by_id(req.deal_id)
    if deal is None:
        raise NotFoundError(message=f"交易 {req.deal_id} 不存在")

    payment_service = _get_payment_service(server)
    is_wechat = _is_wechat_gateway(server)
    amount = _compute_deposit_amount(deal)
    payment_type = PaymentType(req.payment_type)

    # 创建支付意图
    intent = payment_service.create_payment(
        deal_id=req.deal_id,
        user_id=current_user.user_id,
        amount=amount,
        payment_type=payment_type,
    )
    logger.info("[PAY_CREATE] intent created: payment_id=%s amount=%s gateway=%s",
                intent.payment_id, amount, "wechat" if is_wechat else "mock")

    if is_wechat:
        # 微信支付模式：返回 code_url，前端展示二维码等待用户扫码
        persisted = payment_service.repo.find_by_id(intent.payment_id)
        logger.info("[PAY_CREATE] wechat mode: code_url_len=%s", len(intent.code_url))
        return ok(
            PaymentInfo(
                payment_id=intent.payment_id,
                deal_id=req.deal_id,
                user_id=current_user.user_id,
                amount=amount,
                payment_type=req.payment_type,
                status=persisted["status"] if persisted else "pending",
                code_url=intent.code_url,
            ).model_dump()
        )
    else:
        # Mock 模式：同步确认成功
        payment_service.confirm_payment(
            payment_id=intent.payment_id,
            demander_id=deal.demander_id,
            supplier_id=deal.supplier_id,
        )
        persisted = payment_service.repo.find_by_id(intent.payment_id)
        logger.info("[PAY_CREATE] mock mode: confirmed payment_id=%s status=%s",
                    intent.payment_id, persisted["status"] if persisted else "N/A")
        return ok(
            PaymentInfo(
                payment_id=intent.payment_id,
                deal_id=req.deal_id,
                user_id=current_user.user_id,
                amount=amount,
                payment_type=req.payment_type,
                status=persisted["status"] if persisted else "paid",
                trade_no=persisted.get("trade_no") if persisted else None,
            ).model_dump()
        )


@router.post("/callback", response_model=dict)
async def payment_callback(
    request: Request,
    server: UMCPServer = Depends(get_server),
) -> dict:
    """微信支付回调通知端点。

    微信支付 V3 在用户完成支付后，通过此 URL 异步通知后端。
    仅微信支付模式生效，Mock 模式返回 200 空响应。
    """
    _start = time.perf_counter()
    body = await request.body()
    body_size = len(body)
    client_ip = request.client.host if request.client else "unknown"

    # 读取回调头信息
    wechat_signature = request.headers.get("Wechatpay-Signature", "")
    wechat_timestamp = request.headers.get("Wechatpay-Timestamp", "")
    wechat_nonce = request.headers.get("Wechatpay-Nonce", "")
    wechat_serial = request.headers.get("Wechatpay-Serial", "")

    logger.info(
        "[PAY_CALLBACK] entry: client_ip=%s body_size=%s "
        "Wechatpay-Signature=%s Wechatpay-Timestamp=%s Wechatpay-Nonce=%s Wechatpay-Serial=%s",
        client_ip, body_size,
        wechat_signature[:20] if wechat_signature else "N/A",
        wechat_timestamp, wechat_nonce[:10] if wechat_nonce else "N/A",
        wechat_serial[:10] if wechat_serial else "N/A",
    )

    # 分支 1: Mock 模式，忽略回调
    if not _is_wechat_gateway(server):
        logger.info("[PAY_CALLBACK] branch=MOCK_MODE ignored, elapsed=%.3fs", time.perf_counter() - _start)
        return {"code": "SUCCESS", "message": "mock mode, ignored"}

    gateway: WechatPayGateway = getattr(server, "payment_service", None)._gateway

    # 分支 2: 签名验证
    sig_ok = gateway.verify_callback_signature(
        body, wechat_signature, wechat_timestamp, wechat_nonce, wechat_serial
    )
    if not sig_ok:
        elapsed = time.perf_counter() - _start
        logger.warning(
            "[PAY_CALLBACK] branch=SIGNATURE_FAILED client_ip=%s body_size=%s "
            "serial=%s header_ts=%s nonce=%s elapsed=%.3fs",
            client_ip, body_size, wechat_serial, wechat_timestamp, wechat_nonce, elapsed,
        )
        return {"code": "FAIL", "message": "signature verification failed"}

    logger.info("[PAY_CALLBACK] branch=SIGNATURE_OK serial=%s elapsed=%.3fs",
                wechat_serial, time.perf_counter() - _start)

    # 分支 3: 处理回调内容
    result = gateway.handle_callback(body)
    mapped_status = result.get("status", "unknown")
    logger.info(
        "[PAY_CALLBACK] branch=CALLBACK_HANDLED payment_id=%s trade_no=%s mapped_status=%s event_type=%s elapsed=%.3fs",
        result.get("payment_id", "N/A"), result.get("trade_no", "N/A"),
        mapped_status, result.get("event_type", "N/A"),
        time.perf_counter() - _start,
    )

    # 分支 4: 根据回调状态执行确认/退款
    if mapped_status == "paid":
        payment_service = getattr(server, "payment_service", None)
        if payment_service:
            confirm_pid = result["payment_id"]
            confirm_trade_no = result.get("trade_no", "")
            logger.info(
                "[PAY_CALLBACK] branch=CONFIRM_PAYMENT payment_id=%s trade_no=%s elapsed=%.3fs",
                confirm_pid, confirm_trade_no, time.perf_counter() - _start,
            )
            try:
                payment_service.confirm_payment(
                    payment_id=confirm_pid,
                    trade_no=confirm_trade_no,
                )
                logger.info(
                    "[PAY_CALLBACK] branch=CONFIRM_SUCCESS payment_id=%s elapsed=%.3fs",
                    confirm_pid, time.perf_counter() - _start,
                )
            except Exception as e:
                logger.error(
                    "[PAY_CALLBACK] branch=CONFIRM_FAILED payment_id=%s error=%s elapsed=%.3fs",
                    confirm_pid, e, time.perf_counter() - _start,
                )
    elif mapped_status == "refunded":
        logger.info("[PAY_CALLBACK] branch=REFUNDED payment_id=%s", result.get("payment_id", "N/A"))
    else:
        logger.info(
            "[PAY_CALLBACK] branch=OTHER_STATUS mapped_status=%s payment_id=%s",
            mapped_status, result.get("payment_id", "N/A"),
        )

    _total = time.perf_counter() - _start
    logger.info("[PAY_CALLBACK] exit: client_ip=%s body_size=%s status=%s total=%.3fs",
                client_ip, body_size, mapped_status, _total)
    return {"code": "SUCCESS", "message": "OK"}


@router.get("/{deal_id}", response_model=Envelope)
async def get_payment_by_deal(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """按 deal_id 查询支付状态（返回最新一条）。"""
    payment_service = _get_payment_service(server)
    records = payment_service.repo.find_by_deal(deal_id)
    if not records:
        raise NotFoundError(message=f"交易 {deal_id} 无支付记录")
    latest = records[-1]
    return ok(
        PaymentInfo(
            payment_id=latest["payment_id"],
            deal_id=latest["deal_id"],
            user_id=latest["user_id"],
            amount=latest["amount"],
            payment_type=latest["type"],
            status=latest["status"],
            trade_no=latest.get("trade_no"),
        ).model_dump()
    )


@router.post("/{payment_id}/close", response_model=Envelope)
async def close_payment(
    payment_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """关闭未支付的订单。

    微信支付模式：调用微信关闭订单 API。
    Mock 模式：直接标记为失败。
    """
    logger.info("[PAY_CLOSE] entry: payment_id=%s user=%s", payment_id, current_user.user_id)

    payment_service = _get_payment_service(server)
    record = payment_service.repo.find_by_id(payment_id)
    if record is None:
        raise NotFoundError(message=f"支付记录 {payment_id} 不存在")

    if record["status"] != "pending":
        logger.warning("[PAY_CLOSE] skip non-pending payment: payment_id=%s status=%s", payment_id, record["status"])
        return ok({"payment_id": payment_id, "status": record["status"], "closed": False})

    gateway = payment_service._gateway
    closed = gateway.close_payment(payment_id)

    if closed:
        # 更新仓储状态为 FAILED
        from umcp_core.shared.payment.base import PaymentStatusEnum
        payment_service.repo.update_status(payment_id, PaymentStatusEnum.FAILED)
        logger.info("[PAY_CLOSE] success: payment_id=%s", payment_id)
    else:
        logger.warning("[PAY_CLOSE] close failed: payment_id=%s", payment_id)

    return ok({"payment_id": payment_id, "closed": closed})


@router.post("/{deal_id}/timeout", response_model=Envelope)
async def payment_timeout(
    deal_id: str,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """支付超时：取消 deal 和 task，已支付则退款。"""
    logger.info("[TIMEOUT] entry: deal_id=%s user=%s", deal_id, current_user.user_id)

    deal = server.deal_repo.find_by_id(deal_id)
    if deal is None:
        logger.warning("[TIMEOUT] deal not found: deal_id=%s", deal_id)
        raise NotFoundError(message=f"交易 {deal_id} 不存在")
    logger.info("[TIMEOUT] deal found: deal_id=%s status=%s task_id=%s", deal_id, deal.status, deal.task_id)

    # 取消 deal（仅 PENDING/ACTIVE 可取消）
    if deal.status in ("pending", "active"):
        logger.info("[TIMEOUT] cancelling deal: deal_id=%s current_status=%s", deal_id, deal.status)
        deal.bind_event_bus(server.event_bus)
        try:
            deal.cancel()
            server.deal_repo.save(deal)
            logger.info("[TIMEOUT] deal cancelled: deal_id=%s new_status=%s", deal_id, deal.status)
        except (RuntimeError, ValueError) as e:
            logger.warning("[TIMEOUT] cancel deal failed: deal_id=%s error=%s", deal_id, e)
            raise IllegalStateError(message=f"取消 deal 失败: {e}") from e
    elif DealStatus.is_terminal(deal.status):
        logger.warning("[TIMEOUT] deal already in terminal state: deal_id=%s status=%s", deal_id, deal.status)
        raise IllegalStateError(message=f"交易已处于终态 {deal.status}，无法超时取消")

    # 退款已支付的定金
    payment_service = getattr(server, "payment_service", None)
    if payment_service is not None:
        records = payment_service.repo.find_by_deal(deal_id)
        logger.info("[TIMEOUT] payment records found: deal_id=%s count=%s", deal_id, len(records))
        for record in records:
            if record["status"] == "paid":
                logger.info("[TIMEOUT] refunding paid payment: payment_id=%s amount=%s", record["payment_id"], record["amount"])
                try:
                    payment_service.refund(
                        payment_id=record["payment_id"],
                        amount=record["amount"],
                        reason="支付超时自动取消",
                    )
                    logger.info("[TIMEOUT] refund success: payment_id=%s", record["payment_id"])
                except Exception as e:
                    logger.warning("[TIMEOUT] refund failed(ignored): payment_id=%s error=%s", record["payment_id"], e)
            else:
                logger.info("[TIMEOUT] skipping non-paid record: payment_id=%s status=%s", record["payment_id"], record["status"])
    else:
        logger.warning("[TIMEOUT] payment service not available, skipping refund")

    # 取消关联的 task
    task = server.task_repo.find_by_id(deal.task_id)
    if task is not None and task.status not in ("completed", "cancelled"):
        logger.info("[TIMEOUT] cancelling task: task_id=%s current_status=%s", deal.task_id, task.status)
        try:
            task.bind_event_bus(server.event_bus)
            task.cancel()
            server.task_repo.save(task)
            logger.info("[TIMEOUT] task cancelled: task_id=%s new_status=%s", deal.task_id, task.status)
        except (RuntimeError, ValueError) as e:
            logger.warning("[TIMEOUT] cancel task failed(ignored): task_id=%s error=%s", deal.task_id, e)
    else:
        logger.info("[TIMEOUT] task already terminal or not found: task_id=%s", deal.task_id)

    logger.info("[TIMEOUT] completed: deal_id=%s deal_status=%s task_status=%s", deal_id, deal.status, task.status if task else "N/A")
    return ok({
        "deal_id": deal_id,
        "deal_status": deal.status if deal else "cancelled",
        "task_id": deal.task_id if deal else None,
        "task_status": task.status if task else "cancelled",
    })


# ---------------------------------------------------------------------------
# 兼容端点：旧的 mock-pay 路径，保留以防前端旧版本
# ---------------------------------------------------------------------------
@router.post("/mock-pay", response_model=Envelope, include_in_schema=False)
async def mock_pay_compat(
    req: CreatePayRequest,
    server: UMCPServer = Depends(get_server),
    current_user: User = Depends(get_current_user),
) -> Envelope:
    """兼容旧版 Mock 支付端点（已废弃，请使用 /create）。"""
    logger.warning("[MOCK_PAY_COMPAT] deprecated endpoint called, redirecting to /create")
    return await create_payment(req, server, current_user)