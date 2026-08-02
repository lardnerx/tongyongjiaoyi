"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import type { RuleItem } from "@/types/admin";

interface RuleEditDialogProps {
  open: boolean;
  rule: RuleItem | null;
  onConfirm: (value: unknown, reason: string) => void;
  onClose: () => void;
}

export function RuleEditDialog({ open, rule, onConfirm, onClose }: RuleEditDialogProps) {
  const [reason, setReason] = useState("");
  const [numValue, setNumValue] = useState<number>(0);
  const [tiers, setTiers] = useState<{ hours_before: number; penalty: number }[]>([]);
  const [jsonValue, setJsonValue] = useState("");

  useEffect(() => {
    if (!rule) return;
    setReason("");
    const key = rule.rule_key;
    const val = rule.rule_value;
    if (key.endsWith("_seconds")) {
      setNumValue(typeof val === "number" ? val : 0);
    } else if (key.endsWith("_penalty_tiers")) {
      setTiers(Array.isArray(val) ? val : []);
    } else {
      setJsonValue(JSON.stringify(val, null, 2));
    }
  }, [rule]);

  if (!open || !rule) return null;

  const isNumber = rule.rule_key.endsWith("_seconds");
  const isTiers = rule.rule_key.endsWith("_penalty_tiers");

  const handleConfirm = () => {
    if (!reason.trim()) return;
    if (isNumber) {
      onConfirm(numValue, reason);
    } else if (isTiers) {
      onConfirm(tiers, reason);
    } else {
      try {
        onConfirm(JSON.parse(jsonValue), reason);
      } catch {
        alert("JSON 格式错误");
        return;
      }
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-lg w-full mx-4 space-y-4">
        <h3 className="text-lg font-medium">编辑规则</h3>
        <p className="text-sm font-mono text-gray-600">{rule.rule_key}</p>

        {isNumber && (
          <div className="space-y-2">
            <label className="text-sm text-gray-600">数值</label>
            <input
              type="number"
              className="w-full rounded-md border border-gray-300 p-2"
              value={numValue}
              onChange={(e) => setNumValue(Number(e.target.value))}
            />
          </div>
        )}

        {isTiers && (
          <div className="space-y-2">
            <label className="text-sm text-gray-600">罚分梯度</label>
            {tiers.map((tier, i) => (
              <div key={i} className="flex gap-2 items-center">
                <span className="text-xs text-gray-500">提前</span>
                <input
                  type="number"
                  className="w-20 rounded-md border border-gray-300 p-1 text-sm"
                  value={tier.hours_before}
                  onChange={(e) => {
                    const next = [...tiers];
                    next[i] = { ...tier, hours_before: Number(e.target.value) };
                    setTiers(next);
                  }}
                />
                <span className="text-xs text-gray-500">小时，扣</span>
                <input
                  type="number"
                  step="0.1"
                  className="w-20 rounded-md border border-gray-300 p-1 text-sm"
                  value={tier.penalty}
                  onChange={(e) => {
                    const next = [...tiers];
                    next[i] = { ...tier, penalty: Number(e.target.value) };
                    setTiers(next);
                  }}
                />
                <span className="text-xs text-gray-500">分</span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setTiers(tiers.filter((_, idx) => idx !== i))}
                >
                  删除
                </Button>
              </div>
            ))}
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTiers([...tiers, { hours_before: 0, penalty: 0 }])}
            >
              添加档位
            </Button>
          </div>
        )}

        {!isNumber && !isTiers && (
          <div className="space-y-2">
            <label className="text-sm text-gray-600">JSON 值</label>
            <textarea
              className="w-full rounded-md border border-gray-300 p-2 font-mono text-sm"
              rows={6}
              value={jsonValue}
              onChange={(e) => setJsonValue(e.target.value)}
            />
          </div>
        )}

        <div className="space-y-2">
          <label className="text-sm text-gray-600">变更原因（必填）</label>
          <input
            type="text"
            className="w-full rounded-md border border-gray-300 p-2"
            placeholder="请说明变更原因"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <div className="flex gap-2 justify-end">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button variant="destructive" onClick={handleConfirm} disabled={!reason.trim()}>
            确认更新
          </Button>
        </div>
      </div>
    </div>
  );
}
