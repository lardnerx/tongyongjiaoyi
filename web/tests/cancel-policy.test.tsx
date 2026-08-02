import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useCancelRules } from "@/hooks/use-cancel-rules";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

describe("useCancelRules", () => {
  beforeEach(() => {
    (apiClient.get as any).mockReset();
  });

  it("应获取取消规则", async () => {
    (apiClient.get as any).mockResolvedValue({
      timeout_seconds: 60,
      expand_after_seconds: 30,
      penalty_tiers: [
        { hours_before: 24, penalty: 0.2 },
        { hours_before: 0, penalty: 2.0 },
      ],
    });
    const { result } = renderHook(() => useCancelRules(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.timeout_seconds).toBe(60);
    expect(result.current.data?.penalty_tiers).toHaveLength(2);
  });

  it("应提供 calculatePenalty 函数", async () => {
    (apiClient.get as any).mockResolvedValue({
      timeout_seconds: 60,
      expand_after_seconds: 30,
      penalty_tiers: [
        { hours_before: 24, penalty: 0.2 },
        { hours_before: 12, penalty: 0.5 },
        { hours_before: 0, penalty: 2.0 },
      ],
    });
    const { result } = renderHook(() => useCancelRules(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const now = new Date("2026-08-03T10:00:00Z");
    // 提前 25 小时 → 命中 hours_before=24 档 → 0.2
    const far = new Date("2026-08-04T11:00:00Z");
    expect(result.current.calculatePenalty(far, now)).toBe(0.2);
    // 提前 1 小时 → 命中 hours_before=0 档 → 2.0
    const near = new Date("2026-08-03T11:00:00Z");
    expect(result.current.calculatePenalty(near, now)).toBe(2.0);
  });
});
