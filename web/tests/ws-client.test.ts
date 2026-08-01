import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WSClient } from "@/lib/ws-client";

// Mock WebSocket
class MockWebSocket {
  // 标准 WebSocket readyState 常量
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];
  url: string;
  readyState: number = 0;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    // 模拟异步连接成功
    setTimeout(() => {
      if (this.readyState === 3) return; // 已关闭则不触发 onopen
      this.readyState = 1;
      this.onopen?.(new Event("open"));
    }, 0);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }
}

vi.stubGlobal("WebSocket", MockWebSocket);

describe("ws-client", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
  });

  it("connects with token in URL", () => {
    const ws = new WSClient("ws://localhost:8000/ws/events", "my_token");
    expect(MockWebSocket.instances.length).toBe(1);
    expect(MockWebSocket.instances[0].url).toContain("token=my_token");
    ws.disconnect();
  });

  it("dispatches messages to handlers", () => {
    const ws = new WSClient("ws://localhost:8000/ws/events", "my_token");
    const handler = vi.fn();
    ws.on("task.published", handler);
    const mockWs = MockWebSocket.instances[0];
    mockWs.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          type: "task.published",
          timestamp: "2026-08-01T00:00:00Z",
          data: { task_id: "t1" },
        }),
      })
    );
    expect(handler).toHaveBeenCalledWith({ task_id: "t1" });
    ws.disconnect();
  });

  it("sends ping for keepalive", () => {
    vi.useFakeTimers();
    const ws = new WSClient("ws://localhost:8000/ws/events", "my_token", { heartbeatInterval: 1000 });
    vi.advanceTimersByTime(1000);
    const mockWs = MockWebSocket.instances[0];
    expect(mockWs.sent).toContain("ping");
    ws.disconnect();
    vi.useRealTimers();
  });

  it("reconnects on close with backoff", () => {
    vi.useFakeTimers();
    const ws = new WSClient("ws://localhost:8000/ws/events", "my_token", { reconnectDelay: 100 });
    // 手动关闭连接
    const mockWs = MockWebSocket.instances[0];
    mockWs.readyState = 3;
    mockWs.onclose?.(new CloseEvent("close"));
    // 推进定时器触发重连
    vi.advanceTimersByTime(100);
    expect(MockWebSocket.instances.length).toBe(2);
    ws.disconnect();
    vi.useRealTimers();
  });

  it("disconnect stops reconnection", () => {
    vi.useFakeTimers();
    const ws = new WSClient("ws://localhost:8000/ws/events", "my_token", { reconnectDelay: 100 });
    ws.disconnect();
    const mockWs = MockWebSocket.instances[0];
    mockWs.readyState = 3;
    mockWs.onclose?.(new CloseEvent("close"));
    vi.advanceTimersByTime(500);
    expect(MockWebSocket.instances.length).toBe(1); // 未重连
    vi.useRealTimers();
  });
});
