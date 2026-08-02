"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useRules, useUpdateRule } from "@/hooks/use-rules";
import { useAuthStore } from "@/lib/auth-store";
import { Button } from "@/components/ui/button";
import { RuleEditDialog } from "@/components/rule-edit-dialog";
import { RuleHistoryDrawer } from "@/components/rule-history-drawer";
import type { RuleItem } from "@/types/admin";

export default function AdminRulesPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: rules, isLoading } = useRules();
  const updateRule = useUpdateRule();
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [editRule, setEditRule] = useState<RuleItem | null>(null);
  const [historyKey, setHistoryKey] = useState<string | null>(null);

  // admin 角色校验
  if (user && !user.roles?.includes("admin")) {
    return <div className="p-4">权限不足</div>;
  }

  if (isLoading) return <div className="p-4">加载中...</div>;

  // 按 category 分组
  const grouped: Record<string, RuleItem[]> = {};
  for (const rule of rules ?? []) {
    const cat = rule.category || "default";
    if (filterCategory && cat !== filterCategory) continue;
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(rule);
  }

  const categories = Array.from(new Set((rules ?? []).map((r) => r.category || "default")));

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">规则配置管理</h1>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>返回</Button>
        </div>

        {/* 分类筛选 */}
        <div className="flex gap-2 flex-wrap">
          <Button
            variant={filterCategory === "" ? "default" : "outline"}
            size="sm"
            onClick={() => setFilterCategory("")}
          >
            全部
          </Button>
          {categories.map((cat) => (
            <Button
              key={cat}
              variant={filterCategory === cat ? "default" : "outline"}
              size="sm"
              onClick={() => setFilterCategory(cat)}
            >
              {cat}
            </Button>
          ))}
        </div>

        {/* 规则列表（按分类分组） */}
        {Object.entries(grouped).map(([cat, catRules]) => (
          <div key={cat} className="space-y-2">
            <h2 className="text-sm font-medium text-gray-600">{cat}</h2>
            <div className="space-y-2">
              {catRules.map((rule) => (
                <div
                  key={rule.rule_key}
                  className="bg-white rounded-lg border p-4 flex items-center justify-between"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm">{rule.rule_key}</span>
                      {rule.is_default && (
                        <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded">默认</span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500">
                      v{rule.version} · {rule.updated_at ? new Date(rule.updated_at).toLocaleString("zh-CN") : "未修改"}
                      {rule.updated_by && ` · ${rule.updated_by}`}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {formatValue(rule.rule_value)}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setEditRule(rule)}
                    >
                      编辑
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setHistoryKey(rule.rule_key)}
                    >
                      历史
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <RuleEditDialog
        open={editRule !== null}
        rule={editRule}
        onConfirm={(value, reason) => {
          if (editRule) {
            updateRule.mutate({ ruleKey: editRule.rule_key, value, reason });
            setEditRule(null);
          }
        }}
        onClose={() => setEditRule(null)}
      />
      <RuleHistoryDrawer
        open={historyKey !== null}
        ruleKey={historyKey}
        onClose={() => setHistoryKey(null)}
      />
    </div>
  );
}

function formatValue(value: unknown): string {
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return `[${value.length} 项]`;
  if (typeof value === "object" && value) return JSON.stringify(value);
  return String(value);
}
