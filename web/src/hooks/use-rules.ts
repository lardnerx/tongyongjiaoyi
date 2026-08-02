"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { RuleItem, RuleHistoryItem } from "@/types/admin";

export function useRules(category?: string) {
  return useQuery({
    queryKey: ["admin-rules", category],
    queryFn: () =>
      apiClient.get<RuleItem[]>(
        `/admin/rules${category ? `?category=${category}` : ""}`,
      ),
  });
}

export function useRule(ruleKey: string | undefined) {
  return useQuery({
    queryKey: ["admin-rule", ruleKey],
    queryFn: () => apiClient.get<RuleItem>(`/admin/rules/${ruleKey}`),
    enabled: !!ruleKey,
  });
}

export function useUpdateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { ruleKey: string; value: unknown; reason: string }) =>
      apiClient.put<RuleItem>(`/admin/rules/${params.ruleKey}`, {
        value: params.value,
        reason: params.reason,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-rules"] });
      qc.invalidateQueries({ queryKey: ["admin-rule"] });
    },
  });
}

export function useRuleHistory(ruleKey: string | undefined) {
  return useQuery({
    queryKey: ["rule-history", ruleKey],
    queryFn: () =>
      apiClient.get<RuleHistoryItem[]>(`/admin/rules/${ruleKey}/history`),
    enabled: !!ruleKey,
  });
}

export function useRollbackRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { ruleKey: string; historyId: number; reason: string }) =>
      apiClient.post<RuleItem>(`/admin/rules/${params.ruleKey}/rollback`, {
        history_id: params.historyId,
        reason: params.reason,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-rules"] });
      qc.invalidateQueries({ queryKey: ["admin-rule"] });
      qc.invalidateQueries({ queryKey: ["rule-history"] });
    },
  });
}
