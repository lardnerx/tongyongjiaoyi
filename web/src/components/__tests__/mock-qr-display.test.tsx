import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MockQrDisplay } from "../mock-qr-display";

describe("MockQrDisplay", () => {
  it("renders alipay QR code with correct label", () => {
    render(<MockQrDisplay method="alipay" amount={48.0} />);
    expect(screen.getByText("扫码支付")).toBeTruthy();
    expect(screen.getByText(/支付宝/)).toBeTruthy();
  });

  it("renders wechat QR code with correct label", () => {
    render(<MockQrDisplay method="wechat" amount={48.0} />);
    expect(screen.getByText("扫码支付")).toBeTruthy();
    expect(screen.getByText(/微信/)).toBeTruthy();
  });

  it("renders QR image with data URI", () => {
    render(<MockQrDisplay method="alipay" amount={48.0} />);
    const img = screen.getByAltText(/Mock 二维码/);
    expect(img).toBeTruthy();
    expect(img.getAttribute("src")).toMatch(/^data:image\/svg\+xml,/);
  });

  it("generates different QR for different amounts", () => {
    const { container: c1 } = render(<MockQrDisplay method="alipay" amount={48.0} />);
    const { container: c2 } = render(<MockQrDisplay method="alipay" amount={99.0} />);
    const img1 = c1.querySelector("img")?.getAttribute("src");
    const img2 = c2.querySelector("img")?.getAttribute("src");
    expect(img1).not.toBe(img2);
  });

  it("generates different QR for different methods with same amount", () => {
    const { container: c1 } = render(<MockQrDisplay method="alipay" amount={48.0} />);
    const { container: c2 } = render(<MockQrDisplay method="wechat" amount={48.0} />);
    const img1 = c1.querySelector("img")?.getAttribute("src");
    const img2 = c2.querySelector("img")?.getAttribute("src");
    expect(img1).not.toBe(img2);
  });

  it("renders deterministic QR for same inputs", () => {
    const { container: c1 } = render(<MockQrDisplay method="alipay" amount={48.0} />);
    const { container: c2 } = render(<MockQrDisplay method="alipay" amount={48.0} />);
    const img1 = c1.querySelector("img")?.getAttribute("src");
    const img2 = c2.querySelector("img")?.getAttribute("src");
    expect(img1).toBe(img2);
  });

  it("renders zero amount QR", () => {
    render(<MockQrDisplay method="alipay" amount={0} />);
    const img = screen.getByAltText(/Mock 二维码/);
    expect(img).toBeTruthy();
  });

  it("shows dev environment hint text", () => {
    render(<MockQrDisplay method="alipay" amount={48.0} />);
    expect(screen.getByText(/开发环境 Mock/)).toBeTruthy();
  });

  it("renders with very large amount", () => {
    render(<MockQrDisplay method="alipay" amount={99999.99} />);
    expect(screen.getByAltText(/Mock 二维码/)).toBeTruthy();
  });

  it("renders with very small amount", () => {
    render(<MockQrDisplay method="wechat" amount={0.01} />);
    expect(screen.getByAltText(/Mock 二维码/)).toBeTruthy();
  });
});