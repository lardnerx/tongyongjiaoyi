import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CountdownTimer } from "@/components/countdown-timer";
import { CancelDialog } from "@/components/cancel-dialog";

describe("CountdownTimer", () => {
  it("应显示剩余秒数", () => {
    const now = new Date("2026-08-03T10:00:30Z");
    const created = new Date("2026-08-03T10:00:00Z"); // 30 秒前下单
    vi.useFakeTimers().setSystemTime(now);
    render(<CountdownTimer createdAt={created} timeoutSeconds={60} />);
    // 剩余 30 秒
    expect(screen.getByText(/30/)).toBeTruthy();
    vi.useRealTimers();
  });

  it("超时后应显示已超时", () => {
    const now = new Date("2026-08-03T10:02:00Z");
    const created = new Date("2026-08-03T10:00:00Z"); // 120 秒前下单
    vi.useFakeTimers().setSystemTime(now);
    render(<CountdownTimer createdAt={created} timeoutSeconds={60} />);
    expect(screen.getByText(/已超时/)).toBeTruthy();
    vi.useRealTimers();
  });
});

describe("CancelDialog", () => {
  it("实时单不显示罚分提示", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <CancelDialog
        open={true}
        orderType="REALTIME"
        penalty={0}
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );
    expect(screen.queryByText(/扣/)).toBeNull();
    expect(screen.getByRole("heading", { name: /取消订单/ })).toBeTruthy();
  });

  it("预约单显示罚分提示", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <CancelDialog
        open={true}
        orderType="SCHEDULED"
        penalty={2.0}
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );
    expect(screen.getByText(/扣.*2.*分/)).toBeTruthy();
  });

  it("点击确认调用 onConfirm", async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <CancelDialog
        open={true}
        orderType="REALTIME"
        penalty={0}
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /确认取消/ }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalled());
  });
});
