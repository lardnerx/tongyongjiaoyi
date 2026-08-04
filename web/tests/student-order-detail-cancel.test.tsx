import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// mock 路由参数与 hooks
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "task_1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/auth-store", () => ({
  useAuthStore: () => ({ user: { user_id: "student1" } }),
}));

vi.mock("@/hooks/use-orders", () => ({
  useOrder: () => ({
    data: {
      task_id: "task_1",
      order_type: "REALTIME",
      status: "published",
      demander_id: "student1",
      car_type: "auto",
      duration_hours: 1,
      cancel_penalty: 0,
    },
    isLoading: false,
  }),
  useReviews: () => ({ data: [] }),
  useInvalidateOrder: () => vi.fn(),
}));

vi.mock("@/hooks/use-cancel-rules", () => ({
  useCancelRules: () => ({
    data: {
      timeout_seconds: 60,
      expand_after_seconds: 30,
      penalty_tiers: [],
    },
    calculatePenalty: () => 0,
  }),
}));

vi.mock("@/hooks/use-scheduled", () => ({
  useDeal: () => ({ data: null }),
  usePayment: () => ({ data: null }),
}));

vi.mock("@/hooks/use-ws-events", () => ({
  useWsEvent: () => {},
}));

vi.mock("@/hooks/use-friends", () => ({
  useSendFriendRequest: () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

vi.mock("@/lib/order-realtime-store", () => ({
  useOrderRealtimeStore: () => ({ orderStatusUpdates: {} }),
}));

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({}),
    get: vi.fn(),
  },
}));

import StudentOrderDetail from "@/app/(protected)/escort/student/orders/[id]/page";

describe("StudentOrderDetail 取消功能", () => {
  it("实时单 published 状态应显示倒计时与取消按钮", () => {
    render(<StudentOrderDetail />);
    expect(screen.getByText(/剩余/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /取消订单/ })).toBeTruthy();
  });

  it("点击取消按钮应弹出确认对话框", async () => {
    render(<StudentOrderDetail />);
    fireEvent.click(screen.getByRole("button", { name: /取消订单/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /确认取消/ })).toBeTruthy(),
    );
  });
});
