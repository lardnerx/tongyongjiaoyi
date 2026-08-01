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

  it("setTokens writes auth-token cookie for middleware", () => {
    useAuthStore.getState().setTokens("access_cookie_test", "refresh");
    // jsdom 支持 document.cookie
    expect(document.cookie).toContain("auth-token=access_cookie_test");
  });

  it("logout clears auth-token cookie", () => {
    useAuthStore.getState().setTokens("access_to_clear", "refresh");
    expect(document.cookie).toContain("auth-token=access_to_clear");
    useAuthStore.getState().logout();
    // 清除后 cookie 中不再包含有效 token（max-age=0 已使其失效）
    expect(document.cookie).not.toContain("auth-token=access_to_clear");
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
