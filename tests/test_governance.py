"""测试 L7 治理与规则层。"""

from __future__ import annotations

import pytest

from umcp_core.core import DomainTag, StandardTask, User
from umcp_core.layers.l7 import (
    Dispute,
    ExpressionAccessRule,
    NoopComplianceModule,
    RuleEngine,
    SimpleArbitrationPolicy,
)
from umcp_core.layers.l7.governance import _safe_eval


class _Task(StandardTask):
    def task_type(self) -> str:
        return "test"


class _User(User):
    def authenticate(self, credential) -> bool:  # type: ignore[override]
        return True


class TestExpressionAccessRule:
    def test_has_credential_passes(self):
        rule = ExpressionAccessRule("hasCredential('driver_license')")
        user = _User(name="alice", metadata={"credentials": ["driver_license"]})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user, task)

    def test_missing_credential_fails(self):
        rule = ExpressionAccessRule("hasCredential('driver_license')")
        user = _User(name="alice", metadata={"credentials": []})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert not rule.check(user, task)

    def test_combined_expression_with_and(self):
        rule = ExpressionAccessRule(
            "hasCredential('driver_license') && trustScore >= 4.0"
        )
        user_ok = _User(
            name="alice",
            metadata={"credentials": ["driver_license"], "trust_score": 4.5},
        )
        user_low_score = _User(
            name="bob",
            metadata={"credentials": ["driver_license"], "trust_score": 3.5},
        )
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user_ok, task)
        assert not rule.check(user_low_score, task)

    def test_combined_expression_with_or(self):
        rule = ExpressionAccessRule(
            "hasCredential('vip') || trustScore >= 4.5"
        )
        user_vip = _User(
            name="alice",
            metadata={"credentials": ["vip"], "trust_score": 2.0},
        )
        user_high_score = _User(
            name="bob",
            metadata={"credentials": [], "trust_score": 4.8},
        )
        user_neither = _User(
            name="carol",
            metadata={"credentials": [], "trust_score": 3.0},
        )
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user_vip, task)
        assert rule.check(user_high_score, task)
        assert not rule.check(user_neither, task)


class TestRuleEngine:
    def test_check_access_all_rules_pass(self):
        engine = RuleEngine()
        engine.add_access_rule(ExpressionAccessRule("hasCredential('a')"))
        engine.add_access_rule(ExpressionAccessRule("hasCredential('b')"))
        user = _User(name="alice", metadata={"credentials": ["a", "b"]})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("test"))
        assert engine.check_access(user, task)

    def test_check_access_any_rule_fails(self):
        engine = RuleEngine()
        engine.add_access_rule(ExpressionAccessRule("hasCredential('a')"))
        engine.add_access_rule(ExpressionAccessRule("hasCredential('b')"))
        user = _User(name="alice", metadata={"credentials": ["a"]})  # 缺 b
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("test"))
        assert not engine.check_access(user, task)

    def test_arbitrate_default_policy(self):
        engine = RuleEngine()
        dispute = Dispute(
            dispute_id="dp1",
            deal_id="d1",
            initiator_id="d1",
            respondent_id="s1",
            reason="服务未完成",
        )
        result = engine.arbitrate(dispute)
        assert result.outcome == "cancelled"

    def test_audit_default_passes(self):
        from umcp_core.core import Deal

        engine = RuleEngine()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        assert engine.audit(deal)


class TestComplianceModule:
    def test_noop_returns_true(self):
        from umcp_core.core import Deal

        module = NoopComplianceModule()
        deal = Deal(
            task_id="t1",
            resource_id="r1",
            demander_id="d1",
            supplier_id="s1",
        )
        assert module.audit(deal)

    def test_noop_required_compliances_empty(self):
        module = NoopComplianceModule()
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("test"))
        assert module.get_required_compliances(task) == []


# ============================================================================
# AST 安全求值器测试
# ============================================================================


class _CredsObj:
    """模拟 credentials 对象，支持 has(name) 方法。"""

    def __init__(self, creds: list[str]) -> None:
        self._creds = creds

    def has(self, name: str) -> bool:
        return name in self._creds


class _ObjWithSecret:
    """带私有属性的对象，用于测试私有属性访问拒绝。"""

    def __init__(self) -> None:
        self._secret = "sensitive"
        self.public = "ok"

    def _private_method(self) -> str:
        return self._secret

    def public_method(self) -> str:
        return self.public


class TestSafeExpressionEvaluator:
    """_safe_eval AST 求值器测试。"""

    # --- 基本功能 ---

    def test_basic_comparison_ge(self):
        """trustScore >= 0.8 基本比较。"""
        assert _safe_eval("trustScore >= 0.8", {"trustScore": 0.9}) is True
        assert _safe_eval("trustScore >= 0.8", {"trustScore": 0.7}) is False
        assert _safe_eval("trustScore >= 0.8", {"trustScore": 0.8}) is True

    def test_basic_comparison_all_ops(self):
        """覆盖 >= <= > < == != 全部比较运算符。"""
        ctx = {"trustScore": 4.0}
        assert _safe_eval("trustScore == 4.0", ctx) is True
        assert _safe_eval("trustScore != 3.0", ctx) is True
        assert _safe_eval("trustScore > 3.0", ctx) is True
        assert _safe_eval("trustScore < 5.0", ctx) is True
        assert _safe_eval("trustScore <= 4.0", ctx) is True
        assert _safe_eval("trustScore >= 4.0", ctx) is True

    def test_boolean_and_combination(self):
        """trustScore >= 0.8 and credentials.has('business_license') 布尔组合。"""
        creds = _CredsObj(["business_license"])
        ctx_pass = {"trustScore": 0.9, "credentials": creds}
        ctx_low = {"trustScore": 0.7, "credentials": creds}
        creds_no = _CredsObj([])
        ctx_no_cred = {"trustScore": 0.9, "credentials": creds_no}

        assert _safe_eval(
            "trustScore >= 0.8 and credentials.has('business_license')", ctx_pass
        ) is True
        assert _safe_eval(
            "trustScore >= 0.8 and credentials.has('business_license')", ctx_low
        ) is False
        assert _safe_eval(
            "trustScore >= 0.8 and credentials.has('business_license')", ctx_no_cred
        ) is False

    def test_boolean_or_combination(self):
        """or 布尔组合。"""
        creds = _CredsObj([])
        ctx = {"trustScore": 0.9, "credentials": creds}
        assert _safe_eval(
            "trustScore >= 0.8 or credentials.has('business_license')", ctx
        ) is True

    def test_method_call_credentials_has(self):
        """credentials.has('business_license') 方法调用。"""
        creds_yes = _CredsObj(["business_license"])
        creds_no = _CredsObj([])
        assert _safe_eval(
            "credentials.has('business_license')", {"credentials": creds_yes}
        ) is True
        assert _safe_eval(
            "credentials.has('business_license')", {"credentials": creds_no}
        ) is False

    def test_string_literal_comparison(self):
        """字符串字面量比较 name == 'ride'。"""
        ctx = {"name": "ride"}
        assert _safe_eval("name == 'ride'", ctx) is True
        assert _safe_eval("name == 'escort'", ctx) is False
        assert _safe_eval("name != 'escort'", ctx) is True

    def test_not_operator(self):
        """一元 not 运算。"""
        assert _safe_eval("not False", {}) is True
        assert _safe_eval("not True", {}) is False
        creds = _CredsObj([])
        assert _safe_eval(
            "not credentials.has('missing')", {"credentials": creds}
        ) is True

    def test_binop_arithmetic(self):
        """二元算术运算。"""
        assert _safe_eval("1 + 2", {}) == 3
        assert _safe_eval("10 - 4", {}) == 6
        assert _safe_eval("3 * 4", {}) == 12
        assert _safe_eval("10 / 4", {}) == 2.5
        # 在表达式中组合使用
        ctx = {"trustScore": 4.0}
        assert _safe_eval("trustScore + 1.0 >= 4.5", ctx) is True
        assert _safe_eval("trustScore * 2 == 8.0", ctx) is True

    def test_chained_comparison(self):
        """链式比较 0 < trustScore < 5。"""
        ctx = {"trustScore": 3.0}
        assert _safe_eval("0 < trustScore < 5", ctx) is True
        ctx_edge = {"trustScore": 5.0}
        assert _safe_eval("0 < trustScore < 5", ctx_edge) is False

    # --- 安全拒绝 ---

    def test_private_attribute_access_rejected(self):
        """访问私有属性 obj._secret 应抛异常。"""
        obj = _ObjWithSecret()
        ctx = {"obj": obj}
        with pytest.raises(ValueError):
            _safe_eval("obj._secret", ctx)

    def test_private_attribute_in_chain_rejected(self):
        """通过方法链访问私有属性也应拒绝。"""
        creds = _CredsObj([])
        ctx = {"credentials": creds}
        with pytest.raises(ValueError):
            _safe_eval("credentials._creds", ctx)

    def test_global_function_call_rejected(self):
        """调用全局函数 __import__('os') 应抛异常。"""
        # __import__ 作为 Name 节点（全局函数），visit_Call 拒绝非 Attribute func
        with pytest.raises(ValueError):
            _safe_eval("__import__('os')", {})

    def test_builtin_name_rejected(self):
        """未在 context 中的 Name（如 len）应抛异常。"""
        with pytest.raises(ValueError):
            _safe_eval("len([1, 2, 3])", {})

    def test_list_comprehension_rejected(self):
        """列表推导应被拒绝。"""
        with pytest.raises(ValueError):
            _safe_eval("[x for x in range(10)]", {})

    def test_lambda_rejected(self):
        """lambda 表达式应被拒绝。"""
        with pytest.raises(ValueError):
            _safe_eval("(lambda: 1)()", {})

    def test_dict_literal_rejected(self):
        """字典字面量应被拒绝。"""
        with pytest.raises(ValueError):
            _safe_eval("{'a': 1}", {})

    def test_subscript_rejected(self):
        """下标访问 obj[0] 应被拒绝。"""
        ctx = {"obj": [1, 2, 3]}
        with pytest.raises(ValueError):
            _safe_eval("obj[0]", ctx)

    def test_starred_args_rejected(self):
        """星号参数展开应被拒绝。"""
        creds = _CredsObj([])
        ctx = {"credentials": creds, "args": ["a"]}
        with pytest.raises(ValueError):
            _safe_eval("credentials.has(*args)", ctx)

    def test_keyword_args_rejected(self):
        """关键字参数应被拒绝。"""
        creds = _CredsObj(["a"])
        ctx = {"credentials": creds}
        with pytest.raises(ValueError):
            _safe_eval("credentials.has(name='a')", ctx)

    def test_private_method_call_rejected(self):
        """调用私有方法 obj._private_method() 应抛异常。"""
        obj = _ObjWithSecret()
        ctx = {"obj": obj}
        with pytest.raises(ValueError):
            _safe_eval("obj._private_method()", ctx)

    def test_public_method_call_allowed(self):
        """调用公共方法 obj.public_method() 应正常工作。"""
        obj = _ObjWithSecret()
        ctx = {"obj": obj}
        assert _safe_eval("obj.public_method()", ctx) == "ok"

    # --- 错误处理 ---

    def test_syntax_error_raises(self):
        """语法错误应抛 SyntaxError（由调用方捕获返回 False）。"""
        with pytest.raises(SyntaxError):
            _safe_eval("trustScore >>>=", {"trustScore": 1.0})

    def test_undefined_variable_raises(self):
        """不存在的变量应抛 ValueError。"""
        with pytest.raises(ValueError):
            _safe_eval("undefined_var >= 1.0", {})

    def test_evaluate_expression_returns_false_on_syntax_error(self):
        """_evaluate_expression 对语法错误返回 False。"""
        rule = ExpressionAccessRule("trustScore >>> 1.0")
        user = _User(name="alice", metadata={"trust_score": 4.5})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user, task) is False

    def test_evaluate_expression_returns_false_on_undefined_var(self):
        """_evaluate_expression 对不存在的变量返回 False。"""
        rule = ExpressionAccessRule("undefined_var >= 1.0")
        user = _User(name="alice", metadata={})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user, task) is False

    # --- 通过 ExpressionAccessRule 验证新语法端到端 ---

    def test_expression_rule_with_credentials_has_syntax(self):
        """ExpressionAccessRule 支持 credentials.has('xxx') 新语法。"""
        rule = ExpressionAccessRule("credentials.has('business_license')")
        user_with = _User(
            name="alice", metadata={"credentials": ["business_license"]}
        )
        user_without = _User(name="bob", metadata={"credentials": []})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user_with, task) is True
        assert rule.check(user_without, task) is False

    def test_expression_rule_with_and_new_syntax(self):
        """ExpressionAccessRule 支持 and + credentials.has 新语法组合。"""
        rule = ExpressionAccessRule(
            "trustScore >= 0.8 and credentials.has('business_license')"
        )
        user_ok = _User(
            name="alice",
            metadata={"credentials": ["business_license"], "trust_score": 0.9},
        )
        user_low = _User(
            name="bob",
            metadata={"credentials": ["business_license"], "trust_score": 0.7},
        )
        user_no_cred = _User(
            name="carol",
            metadata={"credentials": [], "trust_score": 0.9},
        )
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user_ok, task) is True
        assert rule.check(user_low, task) is False
        assert rule.check(user_no_cred, task) is False

    def test_expression_rule_injection_attack_blocked(self):
        """表达式注入攻击应被阻断：构造恶意表达式应返回 False。"""
        # 尝试通过列表推导执行代码
        rule = ExpressionAccessRule("[x for x in range(10)]")
        user = _User(name="alice", metadata={})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user, task) is False

    def test_expression_rule_attribute_access_blocked(self):
        """访问对象私有属性的表达式应返回 False。"""
        rule = ExpressionAccessRule("credentials._ctx")
        user = _User(name="alice", metadata={"credentials": ["a"]})
        task = _Task(demander_id="d1", domain_tag=DomainTag.of("ride"))
        assert rule.check(user, task) is False
