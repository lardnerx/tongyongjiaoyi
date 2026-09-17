import { describe, it, expect } from "vitest";
import { formatRemaining } from "../payment-page";

describe("formatRemaining utility", () => {
  it("formats 900 seconds as 15:00", () => {
    expect(formatRemaining(900)).toBe("15:00");
  });

  it("formats 0 seconds as 00:00", () => {
    expect(formatRemaining(0)).toBe("00:00");
  });

  it("formats 61 seconds as 01:01", () => {
    expect(formatRemaining(61)).toBe("01:01");
  });

  it("formats 3599 seconds as 59:59", () => {
    expect(formatRemaining(3599)).toBe("59:59");
  });

  it("formats 1 second as 00:01", () => {
    expect(formatRemaining(1)).toBe("00:01");
  });

  it("formats 60 seconds as 01:00", () => {
    expect(formatRemaining(60)).toBe("01:00");
  });

  it("formats 3600 seconds as 60:00", () => {
    expect(formatRemaining(3600)).toBe("60:00");
  });
});