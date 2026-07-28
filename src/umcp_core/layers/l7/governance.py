"""L7 治理与规则层：准入控制、定价上限、仲裁规则、合规。"""

from __future__ import annotations

import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from umcp_core.core.base import User
from umcp_core.core.deal import Deal
from umcp_core.core.task import Task
from umcp_core.layers.l5 import TrustEngine


class AccessRule(ABC):
    """准入规则接口。"""

    @abstractmethod
    def check(self, user: User, task: Task) -> bool:
        """检查用户是否有资格接此任务。"""


class ExpressionAccessRule(AccessRule):
    """基于表达式的准入规则。

    支持简化的表达式语法，例：
      hasCredential('driver_license') && trustScore >= 4.0

    当由 RuleEngine.check_access 调用时，会通过 bind_trust_engine_lookup
    注入 domain→TrustEngine 路由能力，使 trustScore 按 task.domain_tag
    路由到对应 engine 取值。未绑定时 trustScore 读 user.metadata。
    """

    def __init__(self, expression: str) -> None:
        self.expression: str = expression
        self._trust_engine_lookup: Callable[[str], TrustEngine | None] | None = None

    def bind_trust_engine_lookup(
        self, lookup: Callable[[str], TrustEngine | None]
    ) -> None:
        """由 RuleEngine 在 check_access 前注入 domain→engine 路由能力。

        幂等：重复调用不会覆盖已绑定的 lookup。
        """
        if self._trust_engine_lookup is None:
            self._trust_engine_lookup = lookup

    def check(self, user: User, task: Task) -> bool:
        ctx = RuleContext(
            user=user,
            task=task,
            trust_engine_for_domain=self._trust_engine_lookup,
        )
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
    # 可选：domain → TrustEngine 路由回调
    # 注入后，trust_score 会按 task.domain_tag 路由到对应 engine 取值；
    # 未注入（None）时回退到 user.metadata['trust_score']（向后兼容）。
    trust_engine_for_domain: Callable[[str], TrustEngine | None] | None = None

    def has_credential(self, name: str) -> bool:
        # 简化：检查用户 metadata 中的 credentials 列表
        creds = self.user.metadata.get("credentials", [])
        return name in creds

    @property
    def trust_score(self) -> float:
        """按 task.domain_tag 路由到对应 TrustEngine 读取 trust_score。

        - 若 trust_engine_for_domain 已注入且能查到 domain 对应的 engine：
          返回 engine.evaluate(user_id).overall_score
        - 否则回退到 user.metadata['trust_score']（向后兼容）
        """
        if self.trust_engine_for_domain is not None:
            engine = self.trust_engine_for_domain(self.task.domain_tag.value)
            if engine is not None:
                return engine.evaluate(self.user.user_id).overall_score
        return float(self.user.metadata.get("trust_score", 0.0))


class _CredentialsView:
    """暴露给表达式求值器的凭证视图对象。

    支持 `credentials.has(name)` 调用语法；私有属性 `_ctx`
    会被 AST 求值器的私有属性访问禁令拦截。
    """

    def __init__(self, ctx: RuleContext) -> None:
        self._ctx = ctx

    def has(self, name: str) -> bool:
        return self._ctx.has_credential(name)


class _SafeExpressionEvaluator(ast.NodeVisitor):
    """基于 AST 的白名单表达式求值器。

    仅支持以下节点类型，其余一律拒绝：
    - Expression / BoolOp / Compare / BinOp / UnaryOp
    - Name / Constant / Call / Attribute

    安全策略：
    - Attribute：禁止访问 `_` 开头的属性
    - Call：只允许对象方法调用（func 必须是 Attribute），禁止全局函数调用
    - 任何未识别节点 → ValueError
    """

    _BINOP_MAP: dict[type, Any] = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Mod: lambda a, b: a % b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Pow: lambda a, b: a ** b,
    }

    _UNARYOP_MAP: dict[type, Any] = {
        ast.UAdd: lambda a: +a,
        ast.USub: lambda a: -a,
        ast.Not: lambda a: not a,
    }

    _CMPOP_MAP: dict[type, Any] = {
        ast.Eq: lambda a, b: a == b,
        ast.NotEq: lambda a, b: a != b,
        ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b,
        ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b,
    }

    def __init__(self, context: dict[str, Any]) -> None:
        self._context = context

    def evaluate(self, expr: str) -> Any:
        tree = ast.parse(expr, mode="eval")
        return self.visit(tree.body)

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.And):
            result: Any = True
            for value_node in node.values:
                result = self.visit(value_node)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value_node in node.values:
                result = self.visit(value_node)
                if result:
                    return result
            return result
        raise ValueError(
            f"Unsupported bool op: {type(node.op).__name__}"
        )

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            op_func = self._CMPOP_MAP.get(type(op))
            if op_func is None:
                raise ValueError(
                    f"Unsupported comparison op: {type(op).__name__}"
                )
            right = self.visit(comparator)
            if not op_func(left, right):
                return False
            left = right
        return True

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        op_func = self._BINOP_MAP.get(type(node.op))
        if op_func is None:
            raise ValueError(
                f"Unsupported binary op: {type(node.op).__name__}"
            )
        left = self.visit(node.left)
        right = self.visit(node.right)
        return op_func(left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        op_func = self._UNARYOP_MAP.get(type(node.op))
        if op_func is None:
            raise ValueError(
                f"Unsupported unary op: {type(node.op).__name__}"
            )
        operand = self.visit(node.operand)
        return op_func(operand)

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id not in self._context:
            raise ValueError(f"Undefined variable: {node.id}")
        return self._context[node.id]

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        # 禁止访问下划线开头的私有属性
        if node.attr.startswith("_"):
            raise ValueError(
                f"Access to private attribute forbidden: {node.attr}"
            )
        obj = self.visit(node.value)
        return getattr(obj, node.attr)

    def visit_Call(self, node: ast.Call) -> Any:
        # 仅允许对象方法调用（func 必须是 ast.Attribute）
        if not isinstance(node.func, ast.Attribute):
            raise ValueError("Only method calls on objects are allowed")
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise ValueError("Starred args not allowed")
        if node.keywords:
            raise ValueError("Keyword args not allowed")
        # 取目标对象并校验方法名非私有
        obj = self.visit(node.func.value)
        method_name = node.func.attr
        if method_name.startswith("_"):
            raise ValueError(
                f"Calling private method forbidden: {method_name}"
            )
        method = getattr(obj, method_name, None)
        if method is None or not callable(method):
            raise ValueError(f"Method not callable: {method_name}")
        args = [self.visit(a) for a in node.args]
        return method(*args)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(
            f"Unsupported expression node: {type(node).__name__}"
        )


def _safe_eval(expr: str, context: dict[str, Any]) -> Any:
    """用 AST 白名单求值器安全求值表达式。

    语法错误或不支持的节点会抛异常（由调用方捕获）。
    """
    evaluator = _SafeExpressionEvaluator(context)
    return evaluator.evaluate(expr)


def _evaluate_expression(expr: str, ctx: RuleContext) -> bool:
    """简化的表达式求值器（AST 安全求值版）。

    支持：
    - hasCredential('xxx')（向后兼容，regex 预处理为 True/False）
    - credentials.has('xxx')（新语法，AST 方法调用）
    - trustScore >= N / > N / <= N / < N / == N / != N
    - && / ||（向后兼容，regex 替换为 and / or）
    - and / or / not（Python 原生语法）
    - + - * / 等二元运算、一元运算
    """
    # 向后兼容：预处理 hasCredential('xxx') → True/False
    def _cred_repl(m: re.Match) -> str:
        cred_name = m.group(1)
        return "True" if ctx.has_credential(cred_name) else "False"

    expr = re.sub(r"hasCredential\(\s*['\"]([^'\"]+)['\"]\s*\)", _cred_repl, expr)

    # 向后兼容：&& / || → and / or
    expr = expr.replace("&&", " and ").replace("||", " or ")

    # 构造 AST 求值上下文：trustScore 作为变量、credentials 作为对象
    context: dict[str, Any] = {
        "trustScore": ctx.trust_score,
        "credentials": _CredentialsView(ctx),
    }

    try:
        result = _safe_eval(expr, context)
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
        # domain → TrustEngine 映射，供 RuleContext.trust_score 路由
        self._domain_trust_engines: dict[str, TrustEngine] = {}
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

    def register_trust_engine(self, domain: str, engine: TrustEngine) -> None:
        """注册 domain 对应的 TrustEngine，供 RuleContext.trust_score 路由。

        domain 统一小写化存储，与 DomainTag.of(...).value 保持一致。
        """
        self._domain_trust_engines[domain.lower()] = engine

    def set_arbitration_policy(self, policy: ArbitrationPolicy) -> None:
        self._arbitration_policy = policy

    def set_compliance_module(self, module: ComplianceModule) -> None:
        self._compliance = module

    def check_access(self, user: User, task: Task) -> bool:
        """检查所有准入规则。任一不通过则拒绝。

        优先校验 task.domain_tag 对应的 domain 规则，再校验全局规则。
        同时向 ExpressionAccessRule 注入 domain→TrustEngine 路由能力
        （幂等：仅当 rule 未绑定时注入），使 trustScore 按 task.domain 取值。
        """
        domain = task.domain_tag.value
        rules = self._domain_access_rules.get(domain, []) + self._access_rules
        # 注入 domain→engine 路由能力到 ExpressionAccessRule（仅一次，幂等）
        for rule in rules:
            if isinstance(rule, ExpressionAccessRule) and rule._trust_engine_lookup is None:
                rule.bind_trust_engine_lookup(
                    lambda d: self._domain_trust_engines.get(d)
                )
        return all(rule.check(user, task) for rule in rules)

    def arbitrate(self, dispute: Dispute) -> ArbitrationResult:
        return self._arbitration_policy.arbitrate(dispute)

    def audit(self, deal: Deal) -> bool:
        return self._compliance.audit(deal)

    def get_required_compliances(self, task: Task) -> list[str]:
        return self._compliance.get_required_compliances(task)
