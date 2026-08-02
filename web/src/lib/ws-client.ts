import type { WSMessage } from "@/types/api";

export type MessageHandler = (data: Record<string, unknown>) => void;

export interface WSClientOptions {
  heartbeatInterval?: number;
  reconnectDelay?: number;
  maxReconnectDelay?: number;
}

export class WSClient {
  private ws: WebSocket | null = null;
  private url: string;
  private token: string;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = true;
  private reconnectAttempts = 0;
  private options: Required<WSClientOptions>;

  constructor(url: string, token: string, options: WSClientOptions = {}) {
    this.url = url;
    this.token = token;
    this.options = {
      heartbeatInterval: options.heartbeatInterval ?? 30000,
      reconnectDelay: options.reconnectDelay ?? 1000,
      maxReconnectDelay: options.maxReconnectDelay ?? 30000,
    };
    this.connect();
  }

  private connect(): void {
    const fullUrl = `${this.url}?token=${encodeURIComponent(this.token)}`;
    this.ws = new WebSocket(fullUrl);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.startHeartbeat();
    };

    this.ws.onmessage = (event: MessageEvent) => {
      if (event.data === "pong") return;
      try {
        const msg: WSMessage = JSON.parse(event.data);
        const handlers = this.handlers.get(msg.type);
        if (handlers) {
          handlers.forEach((h) => h(msg.data));
        }
      } catch {
        // 忽略非 JSON 消息
      }
    };

    this.ws.onclose = () => {
      this.stopHeartbeat();
      if (this.shouldReconnect) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // error 后通常跟 close，重连逻辑在 onclose
    };
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send("ping");
      }
    }, this.options.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect(): void {
    const delay = Math.min(
      this.options.reconnectDelay * Math.pow(2, this.reconnectAttempts),
      this.options.maxReconnectDelay
    );
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  on(eventType: string, handler: MessageHandler): void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType)!.add(handler);
  }

  off(eventType: string, handler: MessageHandler): void {
    this.handlers.get(eventType)?.delete(handler);
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
  }
}

// ========== 单例 ==========

let _instance: WSClient | null = null;

export const wsClient = {
  /** 初始化 WebSocket 连接（登录后调用）。 */
  init(url: string, token: string, options?: WSClientOptions): void {
    if (_instance) {
      _instance.disconnect();
    }
    _instance = new WSClient(url, token, options);
  },
  /** 订阅事件（未连接时为 no-op）。 */
  on(eventType: string, handler: MessageHandler): void {
    _instance?.on(eventType, handler);
  },
  /** 取消订阅（未连接时为 no-op）。 */
  off(eventType: string, handler: MessageHandler): void {
    _instance?.off(eventType, handler);
  },
  /** 断开连接（登出时调用）。 */
  disconnect(): void {
    _instance?.disconnect();
    _instance = null;
  },
  /** 是否已连接。 */
  get isConnected(): boolean {
    return _instance !== null;
  },
};
