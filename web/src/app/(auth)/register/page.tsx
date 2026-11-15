"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { SiteFooter } from "@/components/site-footer";
import type { TokenResponse, UserInfo, RegisterRequest } from "@/types/api";

export default function RegisterPage() {
  const router = useRouter();
  const { setTokens, setUser } = useAuthStore();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phone) {
      setError("请输入手机号");
      return;
    }
    if (!name) {
      setError("请输入昵称");
      return;
    }
    if (!password) {
      setError("请设置登录密码");
      return;
    }
    if (password.length < 6) {
      setError("密码长度不能少于6位");
      return;
    }
    if (!agreed) {
      setError("请先阅读并同意《用户协议》和《隐私政策》");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // 1. 注册获取 token
      const tokenResp = await apiClient.post<TokenResponse>("/auth/register", {
        phone,
        name,
        password,
      } as RegisterRequest & { password?: string });
      setTokens(tokenResp.access_token, tokenResp.refresh_token);

      // 2. 获取用户信息
      const userInfo = await apiClient.get<UserInfo>("/auth/me");
      setUser(userInfo);

      // 3. 跳转到受保护页面
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4 py-10">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(0,0,0,0.05),transparent_55%)]" />
      <Card className="relative w-full max-w-md border-gray-200/80 shadow-sm">
        <CardHeader>
          <CardTitle className="text-center text-2xl">注册即时百分百</CardTitle>
          <CardDescription className="text-center">
            创建账号，开始预约陪驾服务
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleRegister} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">昵称</label>
              <Input
                type="text"
                placeholder="请输入您的昵称"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={loading}
              />
            </div>
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
              <label className="text-sm font-medium">密码</label>
              <Input
                type="password"
                placeholder="至少6位字符"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
              />
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
            <label className="flex cursor-pointer items-start gap-2 text-xs leading-relaxed text-gray-500">
              <input
                type="checkbox"
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
                disabled={loading}
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 accent-gray-900"
              />
              <span>
                我已阅读并同意
                <Link href="/terms" className="text-gray-700 hover:underline">
                  《用户协议》
                </Link>
                和
                <Link href="/privacy" className="text-gray-700 hover:underline">
                  《隐私政策》
                </Link>
              </span>
            </label>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "注册中..." : "注册"}
            </Button>
          </form>
          <div className="mt-4 text-center text-sm text-gray-500">
            已有账号？{" "}
            <Link href="/login" className="text-blue-500 hover:underline">
              立即登录
            </Link>
          </div>
        </CardContent>
      </Card>
      <div className="relative w-full max-w-md">
        <SiteFooter />
      </div>
    </div>
  );
}