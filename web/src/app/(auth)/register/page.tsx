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

/** 注册身份选项：客户（会员）发出订单，司机负责接单。 */
const ROLE_OPTIONS = [
  {
    value: "demander",
    title: "客户（会员）",
    description: "发布订单，呼叫服务",
  },
  {
    value: "supplier",
    title: "司机",
    description: "在线接单，提供服务",
  },
] as const;

export default function RegisterPage() {
  const router = useRouter();
  const { setTokens, setUser } = useAuthStore();
  const [role, setRole] = useState<"" | "demander" | "supplier">("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedPhone = phone.trim();
    if (!trimmedPhone) {
      setError("请输入手机号");
      return;
    }
    // 中国大陆手机号：1 开头、第二位 3-9、共 11 位
    if (!/^1[3-9]\d{9}$/.test(trimmedPhone)) {
      setError("请输入正确的 11 位大陆手机号");
      return;
    }
    if (!role) {
      setError("请选择注册身份（客户或司机）");
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
        phone: trimmedPhone,
        name,
        password,
        role,
      } as RegisterRequest & { password?: string });
      setTokens(tokenResp.access_token, tokenResp.refresh_token);

      // 2. 获取用户信息
      const userInfo = await apiClient.get<UserInfo>("/auth/me");
      setUser(userInfo);

      // 3. 客户进入服务列表，司机直接进入接单大厅
      router.push(role === "supplier" ? "/escort/coach" : "/services");
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
            选择身份后创建账号，客户叫单、司机接单
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleRegister} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">注册身份</label>
              <div className="grid grid-cols-2 gap-3">
                {ROLE_OPTIONS.map((option) => {
                  const selected = role === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => {
                        setRole(option.value);
                        setError(null);
                      }}
                      disabled={loading}
                      className={`rounded-lg border p-3 text-left transition-colors ${
                        selected
                          ? "border-gray-900 bg-gray-900 text-white"
                          : "border-gray-200 bg-white text-gray-700 hover:border-gray-400"
                      }`}
                    >
                      <div className="text-sm font-medium">{option.title}</div>
                      <div
                        className={`mt-1 text-xs ${
                          selected ? "text-gray-300" : "text-gray-500"
                        }`}
                      >
                        {option.description}
                      </div>
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-gray-400">
                注册后身份不可更改，客户负责发出订单，司机负责接单
              </p>
            </div>
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
                inputMode="numeric"
                maxLength={11}
                placeholder="请输入 11 位大陆手机号"
                value={phone}
                onChange={(e) => setPhone(e.target.value.replace(/\D/g, ""))}
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