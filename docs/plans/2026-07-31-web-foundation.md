# 陪驾 Web 应用 - 阶段二：前端基础（项目搭建 + 身份层 + 路由守卫）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 搭建 Next.js 14 前端项目骨架，实现 API 客户端（JWT 自动刷新）、WebSocket 客户端、认证状态管理、登录页面与路由守卫，产出可登录并访问受保护页面的最小前端应用。

**架构：** Next.js 14 App Router + TypeScript。API 客户端封装 fetch + JWT 拦截器（401 自动刷新 + 令牌轮换），Zustand 管理认证状态，WebSocket 客户端支持指数退避重连和心跳保活。登录页调用后端 `/api/v1/auth/login`（手机号登录），middleware.ts 实现路由守卫。

**技术栈：** Next.js 14、React 18、TypeScript、Tailwind CSS、shadcn/ui、Zustand、React Query、Vitest

---

## 后端 API 接口摘要（实现依据）

### 统一响应信封

成功：`{"code": 0, "data": <T | null>, "message": "ok"}`
错误：`{"code": <int>, "message": <str>, "details": <any | null>}`

### Auth 端点

| 端点 | 方法 | 请求体 | 响应 data |
|------|------|--------|-----------|
| `/api/v1/auth/login` | POST | `{"credential_type":"phone","token":"<手机号>"}` | `{"access_token":"<JWT>","refresh_token":"<JWT>","token_type":"Bearer","expires_in":3600}` |
| `/api/v1/auth/refresh` | POST | `{"refresh_token":"<JWT>"}` | 同 login 响应（令牌轮换，旧 refresh 立即失效） |
| `/api/v1/auth/logout` | POST | 无（需 Authorization 头） | `null` |
| `/api/v1/auth/me` | GET | 无（需 Authorization 头） | `{"user_id":"<str>","name":"<str>","roles":["demander","supplier"],"active_role":"demander"}` |

### WebSocket

连接：`ws://<host>:8000/api/v1/ws/events?token=<access_token>`
客户端发 `"ping"` → 服务端回 `{"type":"pong"}`
服务端推送：`{"type":"<EventType>","timestamp":"<ISO8601>","data":{...}}`

### 关键错误码

| code | HTTP | 含义 |
|------|------|------|
| 1001 | 401 | 无效凭据/token 无效/已吊销 |
| 1002 | 401 | token 已过期 |

---

## 文件结构

```
web/
├── package.json                      # 依赖与脚本
├── tsconfig.json                     # TypeScript 配置
├── next.config.js                    # Next.js 配置
├── tailwind.config.ts                # Tailwind 配置
├── postcss.config.js                 # PostCSS 配置
├── .env.local                        # 环境变量（API 地址等）
├── vitest.config.ts                  # 测试配置
├── src/
│   ├── app/
│   │   ├── layout.tsx                # 根布局（Provider 注入）
│   │   ├── page.tsx                  # 首页（重定向到登录或仪表盘）
│   │   ├── globals.css               # 全局样式（Tailwind）
│   │   ├── (auth)/
│   │   │   └── login/
│   │   │       └── page.tsx          # 登录页
│   │   └── (protected)/
│   │       └── dashboard/
│   │           └── page.tsx          # 受保护页面（验证路由守卫）
│   ├── lib/
│   │   ├── api-client.ts             # API 客户端（fetch 封装 + JWT 拦截）
│   │   ├── ws-client.ts              # WebSocket 客户端（重连 + 心跳）
│   │   ├── auth-store.ts             # Zustand 认证状态
│   │   └── utils.ts                  # cn() 等工具函数
│   ├── components/
│   │   ├── providers.tsx             # 全局 Provider 组合
│   │   └── ui/                       # shadcn/ui 组件
│   │       ├── button.tsx
│   │       ├── input.tsx
│   │       └── card.tsx
│   ├── middleware.ts                 # 路由守卫
│   └── types/
│       └── api.ts                    # API 类型定义
└── tests/
    ├── api-client.test.ts            # API 客户端测试
    ├── auth-store.test.ts            # 认证状态测试
    └── ws-client.test.ts             # WebSocket 客户端测试
```

---

## 任务列表

### 任务 1：Next.js 项目初始化与基础配置

**文件：**
- 创建：`web/package.json`
- 创建：`web/tsconfig.json`
- 创建：`web/next.config.js`
- 创建：`web/.env.local`
- 创建：`web/.gitignore`
- 创建：`web/src/app/globals.css`
- 创建：`web/src/app/layout.tsx`
- 创建：`web/src/app/page.tsx`

- [ ] **步骤 1：创建 Next.js 项目**

在项目根目录 `c:\trae_projects\tongyongjiaoyi` 下创建 `web/` 目录，初始化 Next.js 14 项目：

```bash
cd c:\trae_projects\tongyongjiaoyi
npx create-next-app@14 web --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --no-git
```

若交互式提示，选择：TypeScript=Yes、ESLint=Yes、Tailwind=Yes、src/=Yes、App Router=Yes、import alias=`@/*`。

- [ ] **步骤 2：安装核心依赖**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npm install zustand @tanstack/react-query react-hook-form zod @hookform/resolvers
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **步骤 3：配置环境变量**

创建 `web/.env.local`：

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000/api/v1/ws/events
```

- [ ] **步骤 4：验证项目可启动**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npm run dev
```

预期：在 http://localhost:3000 看到 Next.js 默认页面。用 Ctrl+C 停止。

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 初始化 Next.js 14 项目与基础依赖"
```

---

### 任务 2：API 类型定义

**文件：**
- 创建：`web/src/types/api.ts`

- [ ] **步骤 1：编写 API 类型定义**

创建 `web/src/types/api.ts`：

```typescript
/** 统一响应信封（成功）。 */
export interface Envelope<T> {
  code: number;
  data: T | null;
  message: string;
}

/** 统一错误信封。 */
export interface ErrorEnvelope {
  code: number;
  message: string;
  details: unknown | null;
}

/** Token 响应。 */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** 用户信息。 */
export interface UserInfo {
  user_id: string;
  name: string;
  roles: string[];
  active_role: string | null;
}

/** 登录请求。 */
export interface LoginRequest {
  credential_type: string;
  token: string;
}

/** 刷新令牌请求。 */
export interface RefreshRequest {
  refresh_token: string;
}

/** WebSocket 推送消息。 */
export interface WSMessage {
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}
```

- [ ] **步骤 2：验证类型可导入**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx tsc --noEmit src/types/api.ts
```

预期：无错误。

- [ ] **步骤 3：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/types/api.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): API 类型定义"
```

---

### 任务 3：认证状态管理（Zustand Store）

**文件：**
- 创建：`web/src/lib/auth-store.ts`
- 创建：`web/tests/auth-store.test.ts`
- 创建：`web/vitest.config.ts`

- [ ] **步骤 1：编写 vitest 配置**

创建 `web/vitest.config.ts`：

```typescript
import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
```

- [ ] **步骤 2：编写失败的测试**

创建 `web/tests/auth-store.test.ts`：

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useAuthStore } from "@/lib/auth-store";

describe("auth-store", () => {
  beforeEach(() => {
    useAuthStore.getState().logout();
    localStorage.clear();
  });

  it("initial state has no tokens and no user", () => {
    const state = useAuthStore.getState();
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });

  it("setTokens stores access and refresh tokens", () => {
    useAuthStore.getState().setTokens("access_123", "refresh_456");
    const state = useAuthStore.getState();
    expect(state.accessToken).toBe("access_123");
    expect(state.refreshToken).toBe("refresh_456");
    expect(state.isAuthenticated).toBe(true);
  });

  it("setUser stores user info", () => {
    const user = { user_id: "u1", name: "Test", roles: ["demander"], active_role: "demander" };
    useAuthStore.getState().setUser(user);
    expect(useAuthStore.getState().user).toEqual(user);
  });

  it("logout clears all state", () => {
    useAuthStore.getState().setTokens("access", "refresh");
    useAuthStore.getState().setUser({ user_id: "u1", name: "T", roles: [], active_role: null });
    useAuthStore.getState().logout();
    const state = useAuthStore.getState();
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });

  it("persist tokens to localStorage", () => {
    useAuthStore.getState().setTokens("access_persist", "refresh_persist");
    // Zustand persist 中间件会异步写入，手动触发
    const stored = localStorage.getItem("auth-storage");
    expect(stored).toBeTruthy();
    const parsed = JSON.parse(stored!);
    expect(parsed.state.accessToken).toBe("access_persist");
  });
});
```

- [ ] **步骤 3：运行测试验证失败**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx vitest run tests/auth-store.test.ts
```

预期：FAIL，`Cannot find module '@/lib/auth-store'`

- [ ] **步骤 4：实现 auth-store**

创建 `web/src/lib/auth-store.ts`：

```typescript
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserInfo } from "@/types/api";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserInfo | null;
  isAuthenticated: boolean;
  setTokens: (accessToken: string, refreshToken: string) => void;
  setUser: (user: UserInfo) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      setTokens: (accessToken, refreshToken) =>
        set({ accessToken, refreshToken, isAuthenticated: true }),
      setUser: (user) => set({ user }),
      logout: () =>
        set({
          accessToken: null,
          refreshToken: null,
          user: null,
          isAuthenticated: false,
        }),
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
```

- [ ] **步骤 5：运行测试验证通过**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx vitest run tests/auth-store.test.ts
```

预期：PASS（5 个用例）

- [ ] **步骤 6：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/lib/auth-store.ts web/tests/auth-store.test.ts web/vitest.config.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 认证状态管理 Zustand store + persist"
```

---

### 任务 4：API 客户端（fetch 封装 + JWT 拦截 + 自动刷新）

**文件：**
- 创建：`web/src/lib/api-client.ts`
- 创建：`web/tests/api-client.test.ts`

- [ ] **步骤 1：编写失败的测试**

创建 `web/tests/api-client.test.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";

// Mock fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// Mock window.location
const mockLocation = { href: "" };
vi.stubGlobal("location", mockLocation);

describe("api-client", () => {
  beforeEach(() => {
    useAuthStore.getState().logout();
    mockFetch.mockReset();
  });

  it("GET request returns data on success", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 0, data: { user_id: "u1" }, message: "ok" }),
    });
    const result = await apiClient.get("/auth/me");
    expect(result).toEqual({ user_id: "u1" });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/auth/me"),
      expect.objectContaining({ method: "GET" })
    );
  });

  it("POST request sends JSON body", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 0, data: null, message: "ok" }),
    });
    await apiClient.post("/auth/logout", null);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      })
    );
  });

  it("attaches Authorization header when authenticated", async () => {
    useAuthStore.getState().setTokens("my_access_token", "my_refresh_token");
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 0, data: null, message: "ok" }),
    });
    await apiClient.get("/auth/me");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer my_access_token",
        }),
      })
    );
  });

  it("throws ApiError on non-zero code", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 1001, message: "无效凭据", details: null }),
    });
    await expect(apiClient.get("/auth/me")).rejects.toThrow("无效凭据");
  });

  it("auto-refreshes on 1002 expired token", async () => {
    useAuthStore.getState().setTokens("expired_access", "valid_refresh");
    // 第一次请求返回 1002（过期）
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 1002, message: "token 已过期", details: null }),
    });
    // 刷新请求返回新 token
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        code: 0,
        data: {
          access_token: "new_access",
          refresh_token: "new_refresh",
          token_type: "Bearer",
          expires_in: 3600,
        },
        message: "ok",
      }),
    });
    // 重试请求返回成功
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 0, data: { user_id: "u1" }, message: "ok" }),
    });
    const result = await apiClient.get("/auth/me");
    expect(result).toEqual({ user_id: "u1" });
    expect(useAuthStore.getState().accessToken).toBe("new_access");
  });

  it("redirects to login when refresh fails", async () => {
    useAuthStore.getState().setTokens("expired_access", "invalid_refresh");
    // 第一次请求返回 1002
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 1002, message: "token 已过期", details: null }),
    });
    // 刷新请求失败
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 1001, message: "无效凭据", details: null }),
    });
    await expect(apiClient.get("/auth/me")).rejects.toThrow();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });
});
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx vitest run tests/api-client.test.ts
```

预期：FAIL，`Cannot find module '@/lib/api-client'`

- [ ] **步骤 3：实现 API 客户端**

创建 `web/src/lib/api-client.ts`：

```typescript
import { useAuthStore } from "@/lib/auth-store";
import type { Envelope, ErrorEnvelope } from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    public code: number,
    message: string,
    public details?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let isRefreshing = false;
let refreshPromise: Promise<void> | null = null;

async function refreshTokens(): Promise<void> {
  const { refreshToken, logout } = useAuthStore.getState();
  if (!refreshToken) {
    logout();
    throw new ApiError(1001, "无 refresh token");
  }
  const resp = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const envelope: Envelope<{ access_token: string; refresh_token: string }> = await resp.json();
  if (envelope.code !== 0 || !envelope.data) {
    useAuthStore.getState().logout();
    throw new ApiError(envelope.code, envelope.message);
  }
  useAuthStore.getState().setTokens(envelope.data.access_token, envelope.data.access_token);
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const { accessToken } = useAuthStore.getState();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  const resp = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  const envelope: Envelope<T> | ErrorEnvelope = await resp.json();

  // 检查是否 token 过期（code=1002）
  if ("code" in envelope && envelope.code === 1002) {
    if (!isRefreshing) {
      isRefreshing = true;
      refreshPromise = refreshTokens().finally(() => {
        isRefreshing = false;
        refreshPromise = null;
      });
    }
    await refreshPromise;
    // 重试原请求
    return request<T>(path, options);
  }

  // 非 0 code 视为错误
  if (envelope.code !== 0) {
    const err = envelope as ErrorEnvelope;
    throw new ApiError(err.code, err.message, err.details);
  }

  return (envelope as Envelope<T>).data as T;
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body !== null ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "PUT",
      body: body !== null ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
```

- [ ] **步骤 4：运行测试验证通过**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx vitest run tests/api-client.test.ts
```

预期：PASS（6 个用例）

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/lib/api-client.ts web/tests/api-client.test.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): API 客户端（fetch 封装 + JWT 拦截 + 自动刷新）"
```

---

### 任务 5：WebSocket 客户端（重连 + 心跳 + 消息分发）

**文件：**
- 创建：`web/src/lib/ws-client.ts`
- 创建：`web/tests/ws-client.test.ts`

- [ ] **步骤 1：编写失败的测试**

创建 `web/tests/ws-client.test.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WSClient } from "@/lib/ws-client";

// Mock WebSocket
class MockWebSocket {
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
```

- [ ] **步骤 2：运行测试验证失败**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx vitest run tests/ws-client.test.ts
```

预期：FAIL，`Cannot find module '@/lib/ws-client'`

- [ ] **步骤 3：实现 WebSocket 客户端**

创建 `web/src/lib/ws-client.ts`：

```typescript
import type { WSMessage } from "@/types/api";

type MessageHandler = (data: Record<string, unknown>) => void;

interface WSClientOptions {
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
```

- [ ] **步骤 4：运行测试验证通过**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx vitest run tests/ws-client.test.ts
```

预期：PASS（5 个用例）

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/lib/ws-client.ts web/tests/ws-client.test.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): WebSocket 客户端（重连+心跳+消息分发）"
```

---

### 任务 6：shadcn/ui 基础组件

**文件：**
- 创建：`web/src/lib/utils.ts`
- 创建：`web/src/components/ui/button.tsx`
- 创建：`web/src/components/ui/input.tsx`
- 创建：`web/src/components/ui/card.tsx`

- [ ] **步骤 1：安装 shadcn/ui 依赖**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx shadcn-ui@latest init -d
```

若交互提示，选择：style=default、base color=neutral、CSS variables=yes。

- [ ] **步骤 2：添加基础组件**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx shadcn-ui@latest add button input card -y
```

- [ ] **步骤 3：验证组件可导入**

创建 `web/src/lib/utils.ts`（若 shadcn 未自动创建）：

```typescript
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

若 shadcn 已创建则跳过。

验证：
```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx tsc --noEmit
```

预期：无错误。

- [ ] **步骤 4：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/components/ web/src/lib/utils.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): shadcn/ui 基础组件（button/input/card）"
```

---

### 任务 7：全局 Provider 与根布局

**文件：**
- 创建：`web/src/components/providers.tsx`
- 修改：`web/src/app/layout.tsx`

- [ ] **步骤 1：编写 Providers 组件**

创建 `web/src/components/providers.tsx`：

```tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
```

- [ ] **步骤 2：更新根布局**

修改 `web/src/app/layout.tsx`：

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "陪驾平台",
  description: "陪驾 Web 应用 MVP",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className={inter.className}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

- [ ] **步骤 3：验证项目可构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npm run build
```

预期：构建成功。

- [ ] **步骤 4：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/components/providers.tsx web/src/app/layout.tsx
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 全局 Provider 与根布局"
```

---

### 任务 8：登录页面

**文件：**
- 创建：`web/src/app/(auth)/login/page.tsx`

- [ ] **步骤 1：实现登录页面**

创建 `web/src/app/(auth)/login/page.tsx`：

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TokenResponse, UserInfo, LoginRequest } from "@/types/api";

export default function LoginPage() {
  const router = useRouter();
  const { setTokens, setUser } = useAuthStore();
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phone) {
      setError("请输入手机号");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // 1. 登录获取 token
      const tokenResp = await apiClient.post<TokenResponse>("/auth/login", {
        credential_type: "phone",
        token: phone,
      } as LoginRequest);
      setTokens(tokenResp.access_token, tokenResp.refresh_token);

      // 2. 获取用户信息
      const userInfo = await apiClient.get<UserInfo>("/auth/me");
      setUser(userInfo);

      // 3. 跳转到受保护页面
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-center text-2xl">陪驾平台登录</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">手机号</label>
              <Input
                type="tel"
                placeholder="请输入手机号"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                disabled={loading}
              />
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "登录中..." : "登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **步骤 2：验证页面可构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npm run build
```

预期：构建成功。

- [ ] **步骤 3：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/app/
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 登录页面（手机号登录）"
```

---

### 任务 9：受保护页面与首页重定向

**文件：**
- 创建：`web/src/app/(protected)/dashboard/page.tsx`
- 修改：`web/src/app/page.tsx`

- [ ] **步骤 1：实现 Dashboard 页面**

创建 `web/src/app/(protected)/dashboard/page.tsx`：

```tsx
"use client";

import { useAuthStore } from "@/lib/auth-store";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import { useRouter } from "next/navigation";

export default function DashboardPage() {
  const router = useRouter();
  const { user, logout } = useAuthStore();

  const handleLogout = async () => {
    try {
      await apiClient.post("/auth/logout", null);
    } catch {
      // 忽略登出 API 错误
    }
    logout();
    router.push("/login");
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50">
      <div className="w-full max-w-md space-y-6 text-center">
        <h1 className="text-3xl font-bold">欢迎，{user?.name || "用户"}</h1>
        <p className="text-gray-600">用户 ID: {user?.user_id}</p>
        <p className="text-gray-600">角色: {user?.roles?.join(", ") || "无"}</p>
        <Button onClick={handleLogout} variant="outline">
          退出登录
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **步骤 2：实现首页重定向**

修改 `web/src/app/page.tsx`：

```tsx
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/dashboard");
}
```

- [ ] **步骤 3：验证构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npm run build
```

预期：构建成功。

- [ ] **步骤 4：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/app/
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 受保护 Dashboard 页面与首页重定向"
```

---

### 任务 10：路由守卫 middleware

**文件：**
- 创建：`web/src/middleware.ts`

- [ ] **步骤 1：实现路由守卫**

创建 `web/src/middleware.ts`：

```typescript
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 从 cookie 读取 auth-storage（Zustand persist 默认存 localStorage，
  // 但 middleware 运行在 Edge Runtime 无法访问 localStorage，
  // 所以通过 cookie 传递认证状态——需在 auth-store 中同步写入 cookie）
  // 这里简化为检查 cookie 中的 access_token
  const authToken = request.cookies.get("auth-token")?.value;

  // 公开路径（无需登录）
  const publicPaths = ["/login", "/register", "/forgot-password"];
  const isPublicPath = publicPaths.some((p) => pathname.startsWith(p));

  // 未登录访问受保护路径 → 跳登录
  if (!authToken && !isPublicPath) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // 已登录访问登录页 → 跳 Dashboard
  if (authToken && isPublicPath) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **步骤 2：在 auth-store 中同步 cookie**

修改 `web/src/lib/auth-store.ts`，在 `setTokens` 和 `logout` 时同步写入/清除 cookie（供 middleware 读取）：

在 store 定义后追加 cookie 同步逻辑。修改 `setTokens`：

```typescript
      setTokens: (accessToken, refreshToken) => {
        set({ accessToken, refreshToken, isAuthenticated: true });
        // 同步 cookie 供 middleware 读取
        document.cookie = `auth-token=${accessToken}; path=/; max-age=3600; samesite=lax`;
      },
```

修改 `logout`：

```typescript
      logout: () => {
        set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false });
        document.cookie = "auth-token=; path=/; max-age=0";
      },
```

- [ ] **步骤 3：验证构建**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npm run build
```

预期：构建成功。

- [ ] **步骤 4：运行全部测试**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npx vitest run
```

预期：所有测试通过。

- [ ] **步骤 5：Commit**

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/src/middleware.ts web/src/lib/auth-store.ts
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "feat(web): 路由守卫 middleware + cookie 同步"
```

---

### 任务 11：端到端验证

**文件：**
- 无新建文件

- [ ] **步骤 1：启动后端**

```bash
cd c:\trae_projects\tongyongjiaoyi\umcp-core
$env:PYTHONPATH="src"; python -m umcp_core.transport
```

预期：FastAPI 启动在 http://localhost:8000

- [ ] **步骤 2：启动前端**

```bash
cd c:\trae_projects\tongyongjiaoyi\web
npm run dev
```

预期：Next.js 启动在 http://localhost:3000

- [ ] **步骤 3：手动验证登录流程**

1. 打开 http://localhost:3000 → 应重定向到 /login
2. 输入手机号（如 13800138000），点击登录
3. 登录成功后应跳转到 /dashboard
4. Dashboard 显示用户信息（user_id / name / roles）
5. 点击"退出登录" → 应跳转回 /login
6. 直接访问 http://localhost:3000/dashboard（未登录）→ 应重定向到 /login

- [ ] **步骤 4：Commit（若有修复）**

若验证过程中发现问题并修复：

```bash
cd c:\trae_projects\tongyongjiaoyi
git add web/
git -c user.name="UMCP Dev" -c user.email="dev@umcp.local" commit -m "fix(web): 端到端验证修复"
```

若无问题则跳过此步骤。

---

## 自检

### 1. 规格覆盖度

对照设计规格第八章"前端架构"：
- 技术栈（Next.js 14 / shadcn/ui / Zustand / React Query）：✅ 任务1-7
- 鉴权与路由守卫：✅ 任务10
- API 客户端（fetch + JWT 拦截 + 统一信封解析 + 401 自动刷新）：✅ 任务4
- WebSocket 客户端（指数退避重连 + 心跳保活 + 消息分发）：✅ 任务5
- 登录页面：✅ 任务8

未覆盖（留待后续阶段）：
- 注册页面（后端当前 PhoneAuthProvider 自动注册，无需独立注册页）
- 角色校验（middleware 仅检查登录态，角色校验留待学员端/教练端阶段）
- React Query 服务端状态管理封装（Provider 已就绪，具体查询留待业务页面）

### 2. 占位符扫描

无占位符。所有代码步骤包含完整代码。

### 3. 类型一致性

- `TokenResponse`：任务2 定义，任务4 和任务8 使用 — 一致
- `UserInfo`：任务2 定义，任务3 和任务8 使用 — 一致
- `LoginRequest`：任务2 定义，任务8 使用 — 一致
- `WSMessage`：任务2 定义，任务5 使用 — 一致
- `apiClient.get/post`：任务4 定义，任务8 和任务9 使用 — 一致
- `useAuthStore.setTokens/setUser/logout`：任务3 定义，任务4/8/9/10 使用 — 一致
- `WSClient.on/off/disconnect`：任务5 定义 — 一致
