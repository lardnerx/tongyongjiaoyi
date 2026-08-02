"use client";

import { Button } from "@/components/ui/button";
import { useRuleHistory, useRollbackRule } from "@/hooks/use-rules";

interface RuleHistoryDrawerProps {
  open: boolean;
  ruleKey: string | null;
  onClose: () => void;
}

export function RuleHistoryDrawer({ open, ruleKey, onClose }: RuleHistoryDrawerProps) {
  const { data: history, isLoading } = useRuleHistory(open ? ruleKey ?? undefined : undefined);
  const rollback = useRollbackRule();

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex justify-end z-50">
      <div className="bg-white w-96 h-full overflow-y-auto p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium">变更历史</h3>
          <Button variant="ghost" onClick={onClose}>关闭</Button>
        </div>
        {ruleKey && (
          <p className="text-sm font-mono text-gray-600">{ruleKey}</p>
        )}
        {isLoading && <p className="text-sm text-gray-500">加载中...</p>}
        {!isLoading && history && history.length === 0 && (
          <p className="text-sm text-gray-500">暂无历史记录</p>
        )}
        <div className="space-y-3">
          {history?.map((h) => (
            <div key={h.history_id} className="border rounded-lg p-3 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">
                  {new Date(h.changed_at).toLocaleString("zh-CN")}
                </span>
                {h.changed_by && (
                  <span className="text-xs text-gray-400">{h.changed_by}</span>
                )}
              </div>
              <div className="text-sm">
                <span className="text-gray-500">旧值: </span>
                <span className="font-mono">
                  {h.old_value === null ? "无" : JSON.stringify(h.old_value)}
                </span>
              </div>
              <div className="text-sm">
                <span className="text-gray-500">新值: </span>
                <span className="font-mono">
                  {h.new_value === null ? "无" : JSON.stringify(h.new_value)}
                </span>
              </div>
              {h.change_reason && (
                <p className="text-xs text-gray-600">原因: {h.change_reason}</p>
              )}
              {h.old_value !== null && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={rollback.isPending}
                  onClick={() => {
                    if (!ruleKey) return;
                    const reason = prompt("请输入回滚原因");
                    if (reason) {
                      rollback.mutate({ ruleKey, historyId: h.history_id, reason });
                    }
                  }}
                >
                  回滚到此版本
                </Button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
