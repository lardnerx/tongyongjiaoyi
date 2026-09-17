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

  it("auto-refreshes on 1001 invalid credential", async () => {
    useAuthStore.getState().setTokens("invalid_access", "valid_refresh");
    // 第一次请求返回 1001（签名无效，如服务器重启）
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 1001, message: "无效凭据", details: null }),
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

  it("concurrent 1002 requests share single refresh", async () => {
    useAuthStore.getState().setTokens("expired_access", "valid_refresh");
    // 三个并发请求各自第一次返回 1002
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 1002, message: "token 已过期", details: null }),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 1002, message: "token 已过期", details: null }),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 1002, message: "token 已过期", details: null }),
    });
    // 一次刷新成功
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        code: 0,
        data: { access_token: "new_access", refresh_token: "new_refresh", token_type: "Bearer", expires_in: 3600 },
        message: "ok",
      }),
    });
    // 三个重试各自返回成功
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 0, data: { n: 1 }, message: "ok" }),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 0, data: { n: 2 }, message: "ok" }),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ code: 0, data: { n: 3 }, message: "ok" }),
    });

    const results = await Promise.all([
      apiClient.get("/test/1"),
      apiClient.get("/test/2"),
      apiClient.get("/test/3"),
    ]);

    // 验证 /auth/refresh 只被调用一次（核心防并发断言）
    const refreshCalls = mockFetch.mock.calls.filter(
      (c) => String(c[0]).includes("/auth/refresh")
    );
    expect(refreshCalls.length).toBe(1);
    // 验证三个请求都拿到结果
    expect(results.length).toBe(3);
  });
});
