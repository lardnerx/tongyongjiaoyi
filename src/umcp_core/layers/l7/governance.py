"""L7 治理与规则层：准入控制、定价上限、仲裁规则、合规。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from umcp_core.core.base import User
from umcp_core.core.deal import Deal
from umcp_core.core.task import Task


class AccessRule(ABC):
    """准入规则接口。"""

    @abstractmethod
    def check(self, user: User, task: Task) -> bool:
        """检查用户是否有资格接此任务。"""


class ExpressionAccessRule(AccessRule):
    """基于表达式的准入规则。

    支持简化的表达式语法，例：
      hasCredential('driver_license') && trustScore >= 4.0
    """

    def __init__(self, expression: str) -> None:
        self.expression: str = expression

    def check(self, user: User, task: Task) -> bool:
        # 简化实现：解析常见模式
        # 生产环境应替换为完整的规则引擎（如 durable-rules、python-rule-engine）
        ctx = RuleContext(user, task)
        return _evaluate_expression(self.expression, ctx)


@dataclass
class Dispute:
    """争议记录。"""

    dispute_id: str
    deal_id: str
    initiator_id: str
    respondent_id: str
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "open"  # open, resolved


@dataclass
class ArbitrationResult:
    """仲裁结果。"""

    dispute_id: str
    outcome: str  # "completed", "cancelled", "partial_refund"
    refund_amount: float = 0.0
    penalty: float = 0.0
    reason: str = ""


class ArbitrationPolicy(ABC):
    """仲裁策略接口。"""

    @abstractmethod
    def arbitrate(self, dispute: Dispute) -> ArbitrationResult:
        """对争议进行仲裁。"""


class SimpleArbitrationPolicy(ArbitrationPolicy):
    """简单仲裁策略：默认判决发起人胜诉，全额退款。"""

    def arbitrate(self, dispute: Dispute) -> ArbitrationResult:
        return ArbitrationResult(
            dispute_id=dispute.dispute_id,
            outcome="cancelled",
            refund_amount=0.0,  # 由 RefundPolicy 计算
            reason="默认仲裁：发起方胜诉",
        )


class ComplianceModule(ABC):
    """合规模块接口。"""

    @abstractmethod
    def audit(self, deal: Deal) -> bool:
        """审计交易是否合规。"""

    @abstractmethod
    def get_required_compliances(self, task: Task) -> list[str]:
        """返回任务所需的合规项列表。"""


class NoopComplianceModule(ComplianceModule):
    """空实现：无合规要求时的占位符。"""

    def audit(self, deal: Deal) -> bool:
        return True

    def get_required_compliances(self, task: Task) -> list[str]:
        return []


@dataclass
class RuleContext:
    """规则求值上下文。"""

    user: User
    task: Task

    def has_credential(self, name: str) -> bool:
        # 简化：检查用户 metadata 中的 credentials 列表
        creds = self.user.metadata.get("credentials", [])
        return name in creds

    @property
    def trust_score(self) -> float:
        return float(self.user.metadata.get("trust_score", 0.0))


def _evaluate_expression(expr: str, ctx: RuleContext) -> bool:
    """简化的表达式求值器。

    支持：
    - hasCredential('xxx')
    - trustScore >= N / > N / <= N / < N / == N
    - && / ||
    """
    # 处理 hasCredential('xxx')
    def _cred_repl(m: re.Match) -> str:
        cred_name = m.group(1)
        return "True" if ctx.has_credential(cred_name) else "False"

    expr = re.sub(r"hasCredential\(\s*['\"]([^'\"]+)['\"]\s*\)", _cred_repl, expr)

    # 处理 trustScore
    expr = re.sub(r"trustScore", str(ctx.trust_score), expr)

    # 替换逻辑运算符为 Python 语法
    expr = expr.replace("&&", " and ").replace("||", " or ")

    try:
        # 安全的 eval：仅允许比较运算
        allowed_names: dict[str, Any] = {}
        result = eval(expr, {"__builtins__": {}}, allowed_names)  # noqa: S307
        return bool(result)
    except Exception:
        return False


class RuleEngine:
    """规则引擎：跨层规则注入总线。

    L7 是协议栈的"大脑皮层"和"宪法"，与其他所有层交叉，
    将各阶段积累的隐性治理规则抽象为可配置、可审计的元规则。

    支持按 domain 隔离 access_rules：domain-scoped 规则只对对应 domain 的 task 生效，
    全局规则（无 domain）对所有 task 生效。
    """

    def __init__(self) -> None:
        self._access_rules: list[AccessRule] = []  # 全局兜底
        self._domain_access_rules: dict[str, list[AccessRule]] = {}  # 按 domain
        self._arbitration_policy: ArbitrationPolicy = SimpleArbitrationPolicy()
        self._compliance: ComplianceModule = NoopComplianceModule()

    def add_access_rule(self, rule: AccessRule, domain: str | None = None) -> None:
        """注册准入规则。

        domain 为 None 时注册为全局规则（对所有 task 生效）；
        否则只对该 domain 的 task 生效。
        """
        if domain is None:
            self._access_rules.append(rule)
        else:
            self._domain_access_rules.setdefault(domain, []).append(rule)

    def set_arbitration_policy(self, policy: ArbitrationPolicy) -> None:
        self._arbitration_policy = policy

    def set_compliance_module(self, module: ComplianceModule) -> None:
        self._compliance = module

    def check_access(self, user: User, task: Task) -> bool:
        """检查所有准入规则。任一不通过则拒绝。

        优先校验 task.domain_tag 对应的 domain 规则，再校验全局规则。
        """
        domain = task.domain_tag.value
        rules = self._domain_access_rules.get(domain, []) + self._access_rules
        return all(rule.check(user, task) for rule in rules)

    def arbitrate(self, dispute: Dispute) -> ArbitrationResult:
        return self._arbitration_policy.arbitrate(dispute)

    def audit(self, deal: Deal) -> bool:
        return self._compliance.audit(deal)

    def get_required_compliances(self, task: Task) -> list[str]:
        return self._compliance.get_required_compliances(task)
