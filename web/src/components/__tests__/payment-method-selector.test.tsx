import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PaymentMethodSelector } from "../payment-method-selector";

describe("PaymentMethodSelector", () => {
  it("renders both payment methods", () => {
    const onChange = vi.fn();
    render(<PaymentMethodSelector value="alipay" onChange={onChange} />);
    expect(screen.getByText("支付宝")).toBeTruthy();
    expect(screen.getByText("微信支付")).toBeTruthy();
  });

  it("highlights the selected method (alipay) with blue border", () => {
    const onChange = vi.fn();
    const { container } = render(<PaymentMethodSelector value="alipay" onChange={onChange} />);
    const alipayBtn = screen.getByText("支付宝").closest("button");
    expect(alipayBtn?.className).toContain("border-blue-500");
    expect(alipayBtn?.className).toContain("bg-blue-50");
  });

  it("highlights the selected method (wechat) with green border", () => {
    const onChange = vi.fn();
    const { container } = render(<PaymentMethodSelector value="wechat" onChange={onChange} />);
    const wechatBtn = screen.getByText("微信支付").closest("button");
    expect(wechatBtn?.className).toContain("border-green-500");
    expect(wechatBtn?.className).toContain("bg-green-50");
  });

  it("calls onChange when clicking unselected method", () => {
    const onChange = vi.fn();
    render(<PaymentMethodSelector value="alipay" onChange={onChange} />);
    fireEvent.click(screen.getByText("微信支付"));
    expect(onChange).toHaveBeenCalledWith("wechat");
  });

  it("shows checkmark icon on selected method", () => {
    const onChange = vi.fn();
    const { container } = render(<PaymentMethodSelector value="alipay" onChange={onChange} />);
    const alipayBtn = screen.getByText("支付宝").closest("button");
    const svg = alipayBtn?.querySelector("svg");
    expect(svg).toBeTruthy();
  });

  it("does not show checkmark on unselected method", () => {
    const onChange = vi.fn();
    const { container } = render(<PaymentMethodSelector value="alipay" onChange={onChange} />);
    const wechatBtn = screen.getByText("微信支付").closest("button");
    const svg = wechatBtn?.querySelector("svg");
    expect(svg).toBeNull();
  });

  it("calls onChange even when clicking already selected method (component does not guard)", () => {
    const onChange = vi.fn();
    render(<PaymentMethodSelector value="alipay" onChange={onChange} />);
    fireEvent.click(screen.getByText("支付宝"));
    // 组件不对已选支付方式做防重复点击，每次点击都触发 onChange
    expect(onChange).toHaveBeenCalledWith("alipay");
  });
});