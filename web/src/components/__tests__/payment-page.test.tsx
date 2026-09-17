import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, fireEvent, act, waitFor, cleanup } from "@testing-library/react";
import { PaymentPage } from "../payment-page";

// ================================================================
// Module Mocks
// ================================================================

const mockPush = vi.fn();
const mockBack = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, back: mockBack }),
}));

vi.mock("@/lib/auth-store", () => ({
  useAuthStore: () => ({ user: { user_id: "u1", name: "Test" } }),
}));

// ---- Hook mocks ----
const mockOrderReturn = vi.fn();
const mockDealReturn = vi.fn();
const mockPaymentReturn = vi.fn();
const mockMutateAsync = vi.fn();
const mockIsPending = vi.fn(() => false);

vi.mock("@/hooks/use-orders", () => ({
  useOrder: () => mockOrderReturn(),
}));

vi.mock("@/hooks/use-scheduled", () => ({
  useDeal: () => mockDealReturn(),
  usePayment: () => mockPaymentReturn(),
  useMockPay: () => ({
    mutateAsync: mockMutateAsync,
    get isPending() {
      return mockIsPending();
    },
  }),
}));

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    post: vi.fn(),
  },
}));

import { apiClient } from "@/lib/api-client";

// ================================================================
// Stable mock data (referentially stable across renders)
// ================================================================

const STABLE_ORDER = {
  data: { task_id: "task_1", deal_id: "deal_1", status: "pending" },
  isLoading: false,
};
const STABLE_DEAL = { data: { deal_id: "deal_1", final_amount: 160.0 } };
const STABLE_NO_PAYMENT = { data: null };

// ================================================================
// Tests
// ================================================================

describe("PaymentPage — Loading / Redirect", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("renders loading state when order is still loading", () => {
    mockOrderReturn.mockReturnValue({ data: null, isLoading: true });
    mockDealReturn.mockReturnValue({ data: null });
    mockPaymentReturn.mockReturnValue({ data: null });

    render(<PaymentPage taskId="task_1" />);
    expect(screen.getByText("加载中...")).toBeTruthy();
  });

  it("redirects back when order is null (not found)", () => {
    mockOrderReturn.mockReturnValue({ data: null, isLoading: false });
    mockDealReturn.mockReturnValue({ data: null });
    mockPaymentReturn.mockReturnValue({ data: null });

    render(<PaymentPage taskId="task_1" />);
    expect(mockBack).toHaveBeenCalledTimes(1);
  });

  it("redirects to order detail when payment already exists and is paid", () => {
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue({ data: { status: "paid", amount: 48.0 } });

    render(<PaymentPage taskId="task_1" />);
    expect(mockPush).toHaveBeenCalledWith("/escort/student/orders/task_1");
  });

  it("does not redirect when payment is null (no payment record yet)", () => {
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);

    render(<PaymentPage taskId="task_1" />);
    expect(mockPush).not.toHaveBeenCalled();
    expect(mockBack).not.toHaveBeenCalled();
    expect(screen.getByText("支付定金")).toBeTruthy();
  });
});

describe("PaymentPage — READY state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("renders the payment page header and timeout countdown", () => {
    render(<PaymentPage taskId="task_1" />);
    expect(screen.getByText("支付定金")).toBeTruthy();
    // 900 seconds = 15:00
    expect(screen.getByText("15:00")).toBeTruthy();
  });

  it("renders pay button with correct deposit amount (30% of 160 = 48)", () => {
    render(<PaymentPage taskId="task_1" />);
    expect(screen.getByText("确认支付  ¥48.00")).toBeTruthy();
  });

  it("renders pay button as disabled when mutation is pending", () => {
    mockIsPending.mockReturnValue(true);
    render(<PaymentPage taskId="task_1" />);
    const btn = screen.getByText("支付中...");
    expect(btn).toBeTruthy();
    expect(btn).toBeDisabled();
  });
});

describe("PaymentPage — PROCESSING state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("transitions to PROCESSING when pay button is clicked", () => {
    mockMutateAsync.mockImplementation(() => new Promise(() => {}));
    render(<PaymentPage taskId="task_1" />);

    fireEvent.click(screen.getByText(/确认支付/));
    expect(screen.getByText("支付处理中，请稍候...")).toBeTruthy();
    expect(screen.getByText("请不要关闭页面")).toBeTruthy();
  });

  it("calls mockPay.mutateAsync with correct dealId", () => {
    mockMutateAsync.mockImplementation(() => new Promise(() => {}));
    render(<PaymentPage taskId="task_1" />);

    fireEvent.click(screen.getByText(/确认支付/));
    expect(mockMutateAsync).toHaveBeenCalledWith({ dealId: "deal_1" });
  });
});

describe("PaymentPage — SUCCESS state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("transitions to SUCCESS when payment succeeds", async () => {
    mockMutateAsync.mockResolvedValue({ status: "paid" });
    render(<PaymentPage taskId="task_1" />);

    fireEvent.click(screen.getByText(/确认支付/));

    await waitFor(() => {
      expect(screen.getByText("支付成功")).toBeTruthy();
    });
    expect(screen.getByText("¥48.00")).toBeTruthy();
    expect(screen.getByText("3 秒后自动返回订单详情")).toBeTruthy();
  });

  it("redirects to order detail after 3-second countdown", async () => {
    mockMutateAsync.mockResolvedValue({ status: "paid" });
    render(<PaymentPage taskId="task_1" />);

    fireEvent.click(screen.getByText(/确认支付/));

    await waitFor(() => {
      expect(screen.getByText("支付成功")).toBeTruthy();
    });

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(mockPush).toHaveBeenCalledWith("/escort/student/orders/task_1");
  });

  it("shows countdown decrementing from 3 to 2 after 1 second", async () => {
    mockMutateAsync.mockResolvedValue({ status: "paid" });
    render(<PaymentPage taskId="task_1" />);

    fireEvent.click(screen.getByText(/确认支付/));

    await waitFor(() => {
      expect(screen.getByText("支付成功")).toBeTruthy();
    });

    expect(screen.getByText("3 秒后自动返回订单详情")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.getByText("2 秒后自动返回订单详情")).toBeTruthy();
  });
});

describe("PaymentPage — FAILED state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("transitions to FAILED when payment throws an error", async () => {
    mockMutateAsync.mockRejectedValue(new Error("余额不足"));
    render(<PaymentPage taskId="task_1" />);

    fireEvent.click(screen.getByText(/确认支付/));

    await waitFor(() => {
      expect(screen.getByText("支付失败")).toBeTruthy();
    });
    expect(screen.getByText("余额不足")).toBeTruthy();
    expect(screen.getByText("重新支付")).toBeTruthy();
  });

  it("shows generic error message when error has no message", async () => {
    mockMutateAsync.mockRejectedValue({});
    render(<PaymentPage taskId="task_1" />);

    fireEvent.click(screen.getByText(/确认支付/));

    await waitFor(() => {
      expect(screen.getByText("支付失败，请重试")).toBeTruthy();
    });
  });

  it("transitions back to READY when retry button is clicked", async () => {
    mockMutateAsync.mockRejectedValue(new Error("网络错误"));
    render(<PaymentPage taskId="task_1" />);

    fireEvent.click(screen.getByText(/确认支付/));

    await waitFor(() => {
      expect(screen.getByText("支付失败")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("重新支付"));
    // Should be back in READY state
    expect(screen.getByText("支付定金")).toBeTruthy();
    expect(screen.getByText("确认支付  ¥48.00")).toBeTruthy();
  });
});

describe("PaymentPage — TIMEOUT state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("transitions to TIMEOUT after 900 seconds of inactivity", () => {
    (apiClient.post as Mock).mockResolvedValue({});
    render(<PaymentPage taskId="task_1" />);

    expect(screen.getByText("15:00")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(900000);
    });

    expect(screen.getByText("支付超时")).toBeTruthy();
    expect(screen.getByText("支付已超时，订单已自动取消")).toBeTruthy();
    expect(screen.getByText("返回订单详情")).toBeTruthy();
  });

  it("calls timeout API when transitioning to TIMEOUT", () => {
    (apiClient.post as Mock).mockResolvedValue({});
    render(<PaymentPage taskId="task_1" />);

    act(() => {
      vi.advanceTimersByTime(900000);
    });

    expect(apiClient.post).toHaveBeenCalledWith("/escort/payments/deal_1/timeout", {});
  });

  it("handles timeout API failure gracefully (still shows TIMEOUT)", () => {
    (apiClient.post as Mock).mockRejectedValue(new Error("Network error"));
    render(<PaymentPage taskId="task_1" />);

    act(() => {
      vi.advanceTimersByTime(900000);
    });

    expect(screen.getByText("支付超时")).toBeTruthy();
  });

  it("redirects to order detail when clicking back button after timeout", () => {
    (apiClient.post as Mock).mockResolvedValue({});
    render(<PaymentPage taskId="task_1" />);

    act(() => {
      vi.advanceTimersByTime(900000);
    });

    fireEvent.click(screen.getByText("返回订单详情"));
    expect(mockPush).toHaveBeenCalledWith("/escort/student/orders/task_1");
  });
});

describe("PaymentPage — Timer cleanup", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("clears timeout timer when component unmounts", () => {
    (apiClient.post as Mock).mockResolvedValue({});
    const { unmount } = render(<PaymentPage taskId="task_1" />);

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    unmount();

    act(() => {
      vi.advanceTimersByTime(900000);
    });

    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("clears timeout timer when user clicks pay", () => {
    mockMutateAsync.mockImplementation(() => new Promise(() => {}));
    render(<PaymentPage taskId="task_1" />);

    act(() => {
      vi.advanceTimersByTime(100000);
    });

    fireEvent.click(screen.getByText(/确认支付/));
    expect(screen.getByText("支付处理中，请稍候...")).toBeTruthy();

    (apiClient.post as Mock).mockResolvedValue({});
    act(() => {
      vi.advanceTimersByTime(800000);
    });

    expect(apiClient.post).not.toHaveBeenCalled();
  });
});

describe("PaymentPage — Deposit amount calculation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("calculates deposit as 30% of final_amount", () => {
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue({ data: { deal_id: "deal_1", final_amount: 200.0 } });
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);

    render(<PaymentPage taskId="task_1" />);
    expect(screen.getByText("确认支付  ¥60.00")).toBeTruthy();
  });

  it("handles zero final_amount gracefully", () => {
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue({ data: { deal_id: "deal_1", final_amount: 0 } });
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);

    render(<PaymentPage taskId="task_1" />);
    expect(screen.getByText("确认支付  ¥0.00")).toBeTruthy();
  });

  it("handles fractional amounts with rounding", () => {
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue({ data: { deal_id: "deal_1", final_amount: 99.99 } });
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);

    render(<PaymentPage taskId="task_1" />);
    expect(screen.getByText("确认支付  ¥30.00")).toBeTruthy();
  });
});

describe("PaymentPage — Countdown display during READY", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPush.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockIsPending.mockReset();
    mockIsPending.mockReturnValue(false);
    (apiClient.post as Mock).mockReset();
    mockOrderReturn.mockReturnValue(STABLE_ORDER);
    mockDealReturn.mockReturnValue(STABLE_DEAL);
    mockPaymentReturn.mockReturnValue(STABLE_NO_PAYMENT);
  });

  afterEach(() => {
    vi.clearAllTimers();
    cleanup();
    vi.useRealTimers();
  });

  it("shows decreasing countdown as time passes", () => {
    render(<PaymentPage taskId="task_1" />);

    expect(screen.getByText("15:00")).toBeTruthy();

    act(() => { vi.advanceTimersByTime(60000); });
    expect(screen.getByText("14:00")).toBeTruthy();

    act(() => { vi.advanceTimersByTime(30000); });
    expect(screen.getByText("13:30")).toBeTruthy();

    act(() => { vi.advanceTimersByTime(809000); });
    expect(screen.getByText("00:01")).toBeTruthy();
  });
});