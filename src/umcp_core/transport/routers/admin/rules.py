"""管理员规则配置 router。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from umcp_core.core.base import User
from umcp_core.server import UMCPServer
from umcp_core.transport.deps import get_server, require_admin
from umcp_core.transport.errors import IllegalStateError, NotFoundError
from umcp_core.transport.schemas import Envelope, ok

router = APIRouter(prefix="/api/v1/admin", tags=["admin-rules"])


class RuleItemResponse(BaseModel):
    """规则项响应。"""

    rule_key: str
    rule_value: Any
    description: str | None = None
    category: str
    version: int
    updated_by: str | None = None
    updated_at: str | None = None
    is_default: bool = False


@router.get("/rules", response_model=Envelope)
async def list_rules(
    category: str | None = Query(default=None),
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """列出所有规则（可选按 category 过滤）。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    if category:
        rules = rule_config.list_by_category(category)
    else:
        rules = rule_config.list_all()
    return ok(data=[_to_response(r).model_dump() for r in rules])


@router.get("/rules/{rule_key}", response_model=Envelope)
async def get_rule(
    rule_key: str,
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """查询单个规则详情。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    # 先查仓储
    rule = rule_config.find(rule_key)
    if rule is not None:
        return ok(_to_response({**rule, "is_default": False}).model_dump())
    # 再查默认值
    rules = rule_config.list_all()
    for r in rules:
        if r["rule_key"] == rule_key:
            return ok(_to_response(r).model_dump())
    raise NotFoundError(message=f"规则 {rule_key} 不存在")


class UpdateRuleRequest(BaseModel):
    """更新规则请求。"""

    value: Any
    reason: str = Field(min_length=1)


@router.put("/rules/{rule_key}", response_model=Envelope)
async def update_rule(
    rule_key: str,
    req: UpdateRuleRequest,
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """更新规则值。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    # 获取当前 category（若规则不存在则用 default）
    existing = rule_config.find(rule_key)
    category = existing["category"] if existing else "default"
    description = existing["description"] if existing else None
    rule_config.set(
        key=rule_key,
        value=req.value,
        updated_by=admin.user_id,
        category=category,
        description=description,
        reason=req.reason,
    )
    # 返回更新后的规则
    updated = rule_config.find(rule_key)
    return ok(_to_response({**updated, "is_default": False}).model_dump())


class RuleHistoryResponse(BaseModel):
    """规则历史项响应。"""

    history_id: int
    rule_key: str
    old_value: Any
    new_value: Any
    changed_by: str | None = None
    changed_at: str
    change_reason: str | None = None


class RollbackRequest(BaseModel):
    history_id: int
    reason: str = Field(min_length=1)


@router.get("/rules/{rule_key}/history", response_model=Envelope)
async def get_rule_history(
    rule_key: str,
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """查询规则变更历史。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    history = rule_config.history(rule_key)
    return ok(data=[_to_history_response(h).model_dump() for h in history])


@router.post("/rules/{rule_key}/rollback", response_model=Envelope)
async def rollback_rule(
    rule_key: str,
    req: RollbackRequest,
    server: UMCPServer = Depends(get_server),
    admin: User = Depends(require_admin),
) -> Envelope:
    """回滚规则到指定历史版本。"""
    rule_config = getattr(server, "rule_config", None)
    if rule_config is None:
        raise IllegalStateError(message="规则配置中心未注册")
    history = rule_config.history(rule_key)
    record = next((h for h in history if h["history_id"] == req.history_id), None)
    if record is None:
        raise NotFoundError(message=f"历史记录 {req.history_id} 不存在")
    old_value = record.get("old_value")
    if old_value is None:
        raise IllegalStateError(message="无法回滚到初始版本（无旧值）")
    existing = rule_config.find(rule_key)
    category = existing["category"] if existing else "default"
    description = existing["description"] if existing else None
    rule_config.set(
        key=rule_key,
        value=old_value,
        updated_by=admin.user_id,
        category=category,
        description=description,
        reason=f"回滚: {req.reason}",
    )
    updated = rule_config.find(rule_key)
    return ok(_to_response({**updated, "is_default": False}).model_dump())


def _to_response(rule: dict[str, Any]) -> RuleItemResponse:
    """将规则 dict 转为响应模型。"""
    updated_at = rule.get("updated_at")
    return RuleItemResponse(
        rule_key=rule["rule_key"],
        rule_value=rule["rule_value"],
        description=rule.get("description"),
        category=rule.get("category", "default"),
        version=rule.get("version", 0),
        updated_by=rule.get("updated_by"),
        updated_at=updated_at.isoformat() if updated_at else None,
        is_default=rule.get("is_default", False),
    )


def _to_history_response(h: dict[str, Any]) -> RuleHistoryResponse:
    """将历史 dict 转为响应模型。"""
    changed_at = h.get("changed_at")
    return RuleHistoryResponse(
        history_id=h["history_id"],
        rule_key=h["rule_key"],
        old_value=h.get("old_value"),
        new_value=h.get("new_value"),
        changed_by=h.get("changed_by"),
        changed_at=changed_at.isoformat() if changed_at else "",
        change_reason=h.get("change_reason"),
    )
