import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  PaymentProcessing,
  PaymentSuccess,
  PaymentFailed,
  PaymentTimeout,
} from "../payment-status-card";

describe("PaymentProcessing", () => {
  it("renders default message", () => {
    render(<PaymentProcessing />);
    expect(screen.getByText("支付处理中，请稍候...")).toBeTruthy();
    expect(screen.getByText("请不要关闭页面")).toBeTruthy();
  });

  it("renders custom message", () => {
    render(<PaymentProcessing message="正在验证支付..." />);
    expect(screen.getByText("正在验证支付...")).toBeTruthy();
  });

  it("renders spinner element", () => {
    const { container } = render(<PaymentProcessing />);
    const svg = container.querySelector("svg.animate-spin");
    expect(svg).toBeTruthy();
  });
});

describe("PaymentSuccess", () => {
  it("renders amount and countdown", () => {
    render(<PaymentSuccess amount={48.0} countdown={3} />);
    expect(screen.getByText("支付成功")).toBeTruthy();
    expect(screen.getByText("¥48.00")).toBeTruthy();
    expect(screen.getByText("3 秒后自动返回订单详情")).toBeTruthy();
  });

  it("renders zero amount correctly", () => {
    render(<PaymentSuccess amount={0} countdown={0} />);
    expect(screen.getByText("¥0.00")).toBeTruthy();
    expect(screen.getByText("0 秒后自动返回订单详情")).toBeTruthy();
  });

  it("renders large amount with correct formatting", () => {
    render(<PaymentSuccess amount={9999.99} countdown={5} />);
    expect(screen.getByText("¥9999.99")).toBeTruthy();
  });

  it("renders checkmark icon", () => {
    const { container } = render(<PaymentSuccess amount={10} countdown={3} />);
    const checkmark = container.querySelector("svg");
    expect(checkmark).toBeTruthy();
  });

  it("renders negative amount correctly", () => {
    render(<PaymentSuccess amount={-10.5} countdown={3} />);
    expect(screen.getByText("¥-10.50")).toBeTruthy();
  });
});

describe("PaymentFailed", () => {
  it("renders error message and retry button", () => {
    const onRetry = vi.fn();
    render(<PaymentFailed error="余额不足" onRetry={onRetry} />);
    expect(screen.getByText("支付失败")).toBeTruthy();
    expect(screen.getByText("余额不足")).toBeTruthy();
    expect(screen.getByText("重新支付")).toBeTruthy();
  });

  it("calls onRetry when retry button is clicked", () => {
    const onRetry = vi.fn();
    render(<PaymentFailed error="网络错误" onRetry={onRetry} />);
    fireEvent.click(screen.getByText("重新支付"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders error message with API error", () => {
    const onRetry = vi.fn();
    render(
      <PaymentFailed
        error="支付网关超时，请稍后重试"
        onRetry={onRetry}
      />
    );
    expect(screen.getByText("支付网关超时，请稍后重试")).toBeTruthy();
  });

  it("renders cross icon for failure state", () => {
    const { container } = render(
      <PaymentFailed error="失败" onRetry={vi.fn()} />
    );
    const crossIcon = container.querySelector("svg");
    expect(crossIcon).toBeTruthy();
  });
});

describe("PaymentTimeout", () => {
  it("renders timeout message and back button", () => {
    const onBack = vi.fn();
    render(<PaymentTimeout onBack={onBack} />);
    expect(screen.getByText("支付超时")).toBeTruthy();
    expect(screen.getByText("支付已超时，订单已自动取消")).toBeTruthy();
    expect(screen.getByText("返回订单详情")).toBeTruthy();
  });

  it("calls onBack when back button is clicked", () => {
    const onBack = vi.fn();
    render(<PaymentTimeout onBack={onBack} />);
    fireEvent.click(screen.getByText("返回订单详情"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("renders clock icon", () => {
    const { container } = render(<PaymentTimeout onBack={vi.fn()} />);
    const clockIcon = container.querySelector("svg");
    expect(clockIcon).toBeTruthy();
  });

  it("calls onBack multiple times", () => {
    const onBack = vi.fn();
    render(<PaymentTimeout onBack={onBack} />);
    fireEvent.click(screen.getByText("返回订单详情"));
    fireEvent.click(screen.getByText("返回订单详情"));
    expect(onBack).toHaveBeenCalledTimes(2);
  });
});