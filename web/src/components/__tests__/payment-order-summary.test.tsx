import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PaymentOrderSummary } from "../payment-order-summary";

const BASE_ORDER = {
  task_id: "task_1",
  deal_id: "deal_1",
  status: "pending",
  order_type: "SCHEDULED",
  car_type: "manual",
  duration_hours: 2,
  assigned_resource_id: "coach_1",
  scheduled_at: "2026-08-10T10:00:00",
};

const BASE_DEAL = {
  deal_id: "deal_1",
  final_amount: 160.0,
};

describe("PaymentOrderSummary", () => {
  it("renders order type, car type, and duration", () => {
    render(<PaymentOrderSummary order={BASE_ORDER} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.getByText("预约单")).toBeTruthy();
    expect(screen.getByText("手动挡")).toBeTruthy();
    expect(screen.getByText("2 小时")).toBeTruthy();
  });

  it("renders coach name when assigned", () => {
    render(<PaymentOrderSummary order={BASE_ORDER} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.getByText("coach_1")).toBeTruthy();
  });

  it("does not render coach section when not assigned", () => {
    const order = { ...BASE_ORDER, assigned_resource_id: undefined };
    render(<PaymentOrderSummary order={order} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.queryByText("coach_1")).toBeNull();
  });

  it("renders scheduled time", () => {
    render(<PaymentOrderSummary order={BASE_ORDER} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.getByText(/2026/)).toBeTruthy();
  });

  it("renders total price from deal", () => {
    render(<PaymentOrderSummary order={BASE_ORDER} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.getByText("¥160.00")).toBeTruthy();
  });

  it("does not render total price when deal is undefined", () => {
    render(<PaymentOrderSummary order={BASE_ORDER} deal={undefined} depositAmount={48.0} />);
    expect(screen.queryByText("¥160.00")).toBeNull();
  });

  it("renders deposit amount prominently", () => {
    render(<PaymentOrderSummary order={BASE_ORDER} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.getByText("¥48.00")).toBeTruthy();
  });

  it("renders zero deposit amount", () => {
    render(<PaymentOrderSummary order={BASE_ORDER} deal={BASE_DEAL} depositAmount={0} />);
    expect(screen.getByText("¥0.00")).toBeTruthy();
  });

  it("renders realtime order type", () => {
    const order = { ...BASE_ORDER, order_type: "REALTIME" };
    render(<PaymentOrderSummary order={order} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.getByText("实时单")).toBeTruthy();
  });

  it("renders automatic car type", () => {
    const order = { ...BASE_ORDER, car_type: "automatic" };
    render(<PaymentOrderSummary order={order} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.getByText("自动挡")).toBeTruthy();
  });

  it("renders with deal having zero final_amount", () => {
    const order = { ...BASE_ORDER };
    const deal = { ...BASE_DEAL, final_amount: 0 };
    render(<PaymentOrderSummary order={order} deal={deal} depositAmount={0} />);
    // final_amount=0 为 falsy，总价不渲染；但定金显示 ¥0.00
    expect(screen.queryByText("应付定金")).toBeTruthy();
    expect(screen.getByText("¥0.00")).toBeTruthy();
  });

  it("renders without scheduled_at field", () => {
    const order = { ...BASE_ORDER, scheduled_at: undefined };
    render(<PaymentOrderSummary order={order} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.queryByText(/2026/)).toBeNull();
  });

  it("renders without assigned_resource_id and without scheduled_at", () => {
    const order = { ...BASE_ORDER, assigned_resource_id: undefined, scheduled_at: undefined };
    render(<PaymentOrderSummary order={order} deal={BASE_DEAL} depositAmount={48.0} />);
    expect(screen.getByText("预约单")).toBeTruthy();
    expect(screen.getByText("手动挡")).toBeTruthy();
    expect(screen.getByText("2 小时")).toBeTruthy();
    expect(screen.getByText("¥48.00")).toBeTruthy();
  });
});