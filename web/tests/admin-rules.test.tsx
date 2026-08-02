import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useRules, useRule, useUpdateRule, useRuleHistory, useRollbackRule } from "@/hooks/use-rules";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

describe("useRules hooks", () => {
  beforeEach(() => {
    (apiClient.get as any).mockReset();
    (apiClient.post as any).mockReset();
    (apiClient.put as any).mockReset();
  });

  it("useRules 获取规则列表", async () => {
    (apiClient.get as any).mockResolvedValue([
      { rule_key: "key1", rule_value: 60, category: "escort.cancel", version: 1, is_default: false },
    ]);
    const { result } = renderHook(() => useRules(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].rule_key).toBe("key1");
  });

  it("useRule 获取单个规则", async () => {
    (apiClient.get as any).mockResolvedValue({
      rule_key: "key1", rule_value: 60, category: "test", version: 1, is_default: false,
    });
    const { result } = renderHook(() => useRule("key1"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.rule_value).toBe(60);
  });

  it("useUpdateRule 调用 PUT", async () => {
    (apiClient.put as any).mockResolvedValue({ rule_key: "key1", rule_value: 120 });
    const { result } = renderHook(() => useUpdateRule(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ ruleKey: "key1", value: 120, reason: "测试" });
    expect(apiClient.put).toHaveBeenCalledWith("/admin/rules/key1", { value: 120, reason: "测试" });
  });

  it("useRuleHistory 获取历史", async () => {
    (apiClient.get as any).mockResolvedValue([
      { history_id: 1, rule_key: "key1", old_value: null, new_value: 60, change_reason: "初始" },
    ]);
    const { result } = renderHook(() => useRuleHistory("key1"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(1);
  });

  it("useRollbackRule 调用 POST rollback", async () => {
    (apiClient.post as any).mockResolvedValue({ rule_key: "key1", rule_value: 60 });
    const { result } = renderHook(() => useRollbackRule(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ ruleKey: "key1", historyId: 1, reason: "回滚" });
    expect(apiClient.post).toHaveBeenCalledWith("/admin/rules/key1/rollback", {
      history_id: 1, reason: "回滚",
    });
  });
});
