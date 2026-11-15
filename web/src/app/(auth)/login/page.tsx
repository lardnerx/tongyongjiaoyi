"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TokenResponse, UserInfo, LoginRequest } from "@/types/api";

export default function LoginPage() {
  const router = useRouter();
  const { setTokens, setUser } = useAuthStore();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
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
        password: password || undefined,
      } as LoginRequest & { password?: string });
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
    <div className="relative flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(0,0,0,0.05),transparent_55%)]" />
      <Card className="relative w-full max-w-md border-gray-200/80 shadow-sm">
        <CardHeader className="space-y-0 pb-6 pt-8">
          <div className="flex flex-col items-center gap-4">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gray-900 text-white shadow-sm">
              <span className="text-xs font-semibold tracking-tight">100%</span>
            </div>
            <div className="flex flex-col items-center gap-2">
              <CardTitle className="text-center text-2xl font-semibold tracking-tight">
                即时百分百
              </CardTitle>
              <div className="flex items-center gap-2">
                <span className="h-px w-6 bg-gray-200" />
                <span className="mr-[-0.25em] text-[11px] font-medium tracking-[0.25em] text-gray-400">
                  在线服务
                </span>
                <span className="h-px w-6 bg-gray-200" />
              </div>
            </div>
          </div>
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
            <div className="space-y-2">
              <label className="text-sm font-medium">密码（可选）</label>
              <Input
                type="password"
                placeholder="已设置密码的用户请输入"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
              />
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "登录中..." : "登录"}
            </Button>
            <div className="text-center">
              <Link href="/reset-password" className="text-sm text-blue-500 hover:underline">
                忘记密码？
              </Link>
            </div>
          </form>
          <div className="mt-4 text-center text-sm text-gray-500">
            还没有账号？{" "}
            <Link href="/register" className="text-blue-500 hover:underline">
              立即注册
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
