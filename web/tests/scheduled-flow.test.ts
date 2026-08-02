import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useCreateScheduledOrder, useSelectCoach, useMockPay, useConfirmDeal, useRejectDeal } from "@/hooks/use-scheduled";

// Mock apiClient
vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { apiClient } from "@/lib/api-client";

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

describe("Scheduled flow hooks", () => {
  beforeEach(() => {
    (apiClient.post as any).mockReset();
    (apiClient.get as any).mockReset();
  });

  it("useCreateScheduledOrder calls POST /escort/orders", async () => {
    (apiClient.post as any).mockResolvedValue({
      task_id: "task_1",
      order_type: "SCHEDULED",
      candidates: ["coach_1", "coach_2"],
    });
    const { result } = renderHook(() => useCreateScheduledOrder(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({
        demander_id: "u1",
        origin_lat: 39.9,
        origin_lng: 116.4,
        car_type: "manual",
        duration_hours: 2,
        scheduled_at: "2026-08-10T10:00:00",
        coach_level_pref: "ANY",
      });
    });
    expect(apiClient.post).toHaveBeenCalledWith("/escort/orders", expect.objectContaining({
      order_type: "SCHEDULED",
    }));
  });

  it("useSelectCoach calls POST /escort/orders/{id}/select-coach", async () => {
    (apiClient.post as any).mockResolvedValue({
      deal_id: "deal_1",
      task_id: "task_1",
      resource_id: "coach_1",
      status: "pending",
      deposit_amount: 48.0,
    });
    const { result } = renderHook(() => useSelectCoach(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({ taskId: "task_1", resourceId: "coach_1" });
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/escort/orders/task_1/select-coach",
      { resource_id: "coach_1" }
    );
  });

  it("useMockPay calls POST /escort/payments/mock-pay", async () => {
    (apiClient.post as any).mockResolvedValue({
      payment_id: "pay_1",
      deal_id: "deal_1",
      user_id: "u1",
      amount: 48.0,
      payment_type: "deposit",
      status: "paid",
      trade_no: "mock_trade_pay_1",
    });
    const { result } = renderHook(() => useMockPay(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({ dealId: "deal_1" });
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/escort/payments/mock-pay",
      { deal_id: "deal_1", payment_type: "deposit" }
    );
  });

  it("useConfirmDeal calls POST /escort/deals/{id}/confirm", async () => {
    (apiClient.post as any).mockResolvedValue({
      deal_id: "deal_1",
      status: "active",
      task_id: "task_1",
    });
    const { result } = renderHook(() => useConfirmDeal(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({ dealId: "deal_1", coachId: "coach_1" });
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/escort/deals/deal_1/confirm",
      { coach_id: "coach_1" }
    );
  });

  it("useRejectDeal calls POST /escort/deals/{id}/reject", async () => {
    (apiClient.post as any).mockResolvedValue({
      deal_id: "deal_1",
      status: "cancelled",
      task_id: "task_1",
    });
    const { result } = renderHook(() => useRejectDeal(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({ dealId: "deal_1", coachId: "coach_1", reason: "时间冲突" });
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/escort/deals/deal_1/reject",
      { coach_id: "coach_1", reason: "时间冲突" }
    );
  });
});
