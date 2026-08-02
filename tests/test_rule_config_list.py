"""验证 RuleConfig 的 list_all/list_by_category/history/find 方法。"""
from __future__ import annotations

from umcp_core.shared.rules.config import RuleConfig
from umcp_core.shared.rules.repository import InMemoryRuleRepository


def test_list_all_includes_defaults_and_overrides():
    """list_all 应合并默认值与仓储值。"""
    repo = InMemoryRuleRepository()
    config = RuleConfig(repo=repo)
    config.set_defaults({
        "key1": 60,
        "key2": 30,
    })
    # 覆盖 key1
    config.set("key1", 120, updated_by="admin", category="escort.cancel")

    rules = config.list_all()
    rule_map = {r["rule_key"]: r for r in rules}

    assert rule_map["key1"]["rule_value"] == 120
    assert rule_map["key1"]["is_default"] is False
    assert rule_map["key1"]["category"] == "escort.cancel"

    assert rule_map["key2"]["rule_value"] == 30
    assert rule_map["key2"]["is_default"] is True


def test_list_by_category_filters():
    """list_by_category 应按分类过滤。"""
    repo = InMemoryRuleRepository()
    config = RuleConfig(repo=repo)
    config.set("key1", 120, updated_by="admin", category="escort.cancel")
    config.set("key2", "val", updated_by="admin", category="escort.review")

    rules = config.list_by_category("escort.cancel")
    assert len(rules) == 1
    assert rules[0]["rule_key"] == "key1"


def test_history_returns_change_records():
    """history 应返回变更历史。"""
    repo = InMemoryRuleRepository()
    config = RuleConfig(repo=repo)
    config.set("key1", 60, updated_by="admin", category="test", reason="初始")
    config.set("key1", 120, updated_by="admin", category="test", reason="调整")

    history = config.history("key1")
    assert len(history) == 2
    assert history[0]["new_value"] == 60
    assert history[1]["old_value"] == 60
    assert history[1]["new_value"] == 120


def test_find_returns_rule_dict():
    """find 应返回完整规则 dict（未设置返回 None）。"""
    repo = InMemoryRuleRepository()
    config = RuleConfig(repo=repo)
    config.set("key1", 60, updated_by="admin", category="test")

    rule = config.find("key1")
    assert rule is not None
    assert rule["rule_value"] == 60
    assert rule["version"] == 1

    assert config.find("nonexistent") is None
