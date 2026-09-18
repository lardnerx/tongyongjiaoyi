import { useAuthStore } from "@/lib/auth-store";
import type { Envelope, ErrorEnvelope } from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

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
  // 注意：第二个参数必须是 refresh_token（令牌轮换后旧 refresh 失效，使用新返回的 refresh_token）
  useAuthStore.getState().setTokens(envelope.data.access_token, envelope.data.refresh_token);
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  retried: boolean = false
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

  // 检查是否 token 过期（code=1002）或签名无效（code=1001，如服务器重启后密钥变更）
  // 两者都尝试用 refresh_token 自动恢复，避免用户手动重新登录
  if ("code" in envelope && (envelope.code === 1002 || envelope.code === 1001)) {
    if (retried) {
      throw new ApiError(envelope.code, "刷新后令牌仍被拒绝");
    }
    if (!isRefreshing) {
      isRefreshing = true;
      refreshPromise = refreshTokens().finally(() => {
        isRefreshing = false;
        refreshPromise = null;
      });
    }
    await refreshPromise;
    // 重试原请求，标记已重试
    return request<T>(path, options, true);
  }

  // 非 0 code 视为错误
  if (envelope.code !== 0) {
    const err = envelope as ErrorEnvelope;
    throw new ApiError(err.code, err.message, err.details);
  }

  return (envelope as Envelope<T>).data as T;
}

/** 文件上传（multipart/form-data），不走 JSON 序列化。 */
async function uploadFile<T>(
  path: string,
  formData: FormData,
  onProgress?: (pct: number) => void,
): Promise<T> {
  const { accessToken } = useAuthStore.getState();
  const headers: Record<string, string> = {};
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }
  // 不设置 Content-Type，让浏览器自动设置 multipart boundary

  const resp = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });

  const envelope: Envelope<T> | ErrorEnvelope = await resp.json();
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
  upload: <T>(path: string, formData: FormData) => uploadFile<T>(path, formData),
};
