"""规则配置中心测试。"""
from __future__ import annotations

import pytest


@pytest.fixture
def rule_repo():
    """内存版 RuleRepository，便于无 PG 环境测试。"""
    from umcp_core.shared.rules.repository import InMemoryRuleRepository
    return InMemoryRuleRepository()


def test_rule_repo_find_by_key_returns_none_when_absent(rule_repo):
    assert rule_repo.find_by_key("nonexistent") is None


def test_rule_repo_upsert_and_find(rule_repo):
    rule_repo.upsert("escort.cancel.policy", {"window_minutes": 5}, "admin_1", "cancel")
    rule = rule_repo.find_by_key("escort.cancel.policy")
    assert rule is not None
    assert rule["rule_value"] == {"window_minutes": 5}
    assert rule["category"] == "cancel"
    assert rule["version"] == 1


def test_rule_repo_upsert_increments_version(rule_repo):
    rule_repo.upsert("k", {"v": 1}, "admin", "cat")
    rule_repo.upsert("k", {"v": 2}, "admin", "cat")
    rule = rule_repo.find_by_key("k")
    assert rule["rule_value"] == {"v": 2}
    assert rule["version"] == 2


def test_rule_repo_list_by_category(rule_repo):
    rule_repo.upsert("a", {"v": 1}, "admin", "cancel")
    rule_repo.upsert("b", {"v": 2}, "admin", "cancel")
    rule_repo.upsert("c", {"v": 3}, "admin", "coach")
    items = rule_repo.list_by_category("cancel")
    assert len(items) == 2


def test_rule_repo_list_all(rule_repo):
    rule_repo.upsert("a", {}, "admin", "cat")
    rule_repo.upsert("b", {}, "admin", "cat")
    assert len(rule_repo.list_all()) == 2


def test_rule_repo_append_history(rule_repo):
    rule_repo.upsert("k", {"v": 1}, "admin_1", "cat")
    rule_repo.upsert("k", {"v": 2}, "admin_2", "cat", reason="调整参数")
    history = rule_repo.history("k")
    assert len(history) == 2
    assert history[0]["old_value"] is None
    assert history[0]["new_value"] == {"v": 1}
    assert history[1]["old_value"] == {"v": 1}
    assert history[1]["new_value"] == {"v": 2}
    assert history[1]["changed_by"] == "admin_2"
    assert history[1]["change_reason"] == "调整参数"
