"use client";

import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { TokenResponse } from "@/types/api";

export default function DashboardPage() {
  const router = useRouter();
  const { user, activeRole, setActiveRole, setTokens, logout } = useAuthStore();
  const [switching, setSwitching] = useState(false);

  const handleSwitchRole = async (role: string) => {
    if (role === activeRole) return;
    setSwitching(true);
    try {
      const tokens = await apiClient.post<TokenResponse>("/auth/switch-role", { role });
      setTokens(tokens.access_token, tokens.refresh_token);
      setActiveRole(role);
      router.refresh();
    } catch {
      // 切换失败，保持原角色
    } finally {
      setSwitching(false);
    }
  };

  const handleLogout = async () => {
    try {
      await apiClient.post("/auth/logout", null);
    } catch {
      // 忽略
    }
    logout();
    router.push("/login");
  };

  const canBeDemander = user?.roles?.includes("demander");
  const canBeCoach = user?.roles?.includes("supplier");

  const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";
  const avatarFullUrl = user?.avatar_url
    ? `${API_BASE_URL.replace("/api/v1", "")}${user.avatar_url}`
    : null;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-md space-y-6 text-center">
        {/* 头像显示 */}
        <div className="mx-auto h-20 w-20 overflow-hidden rounded-full border-2 border-gray-200 bg-gray-100">
          {avatarFullUrl ? (
            <img
              src={avatarFullUrl}
              alt="用户头像"
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-2xl text-gray-400">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="40"
                height="40"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            </div>
          )}
        </div>
        <h1 className="text-3xl font-bold">欢迎，{user?.name || "用户"}</h1>
        <p className="text-gray-600">用户 ID: {user?.user_id}</p>
        <p className="text-gray-600">
          当前角色: {activeRole === "supplier" ? "司机" : activeRole === "demander" ? "客户（会员）" : "未设置"}
        </p>

        {/* 角色切换 */}
        <div className="flex gap-2 justify-center">
          {canBeDemander && (
            <Button
              variant={activeRole === "demander" ? "default" : "outline"}
              onClick={() => handleSwitchRole("demander")}
              disabled={switching}
            >
              客户（会员）
            </Button>
          )}
          {canBeCoach && (
            <Button
              variant={activeRole === "supplier" ? "default" : "outline"}
              onClick={() => handleSwitchRole("supplier")}
              disabled={switching}
            >
              司机
            </Button>
          )}
        </div>

        {/* 入口卡片 */}
        <div className="grid gap-3">
          {activeRole === "demander" && (
            <>
              <Button onClick={() => router.push("/escort/student/book-instant")}>
                实时叫车
              </Button>
              <Button variant="outline" onClick={() => router.push("/escort/student/book-scheduled")}>
                预约叫车
              </Button>
              <Button variant="outline" onClick={() => router.push("/escort/student/orders")}>
                我的订单
              </Button>
            </>
          )}
          {activeRole === "supplier" && (
            <>
              <Button onClick={() => router.push("/escort/coach")}>
                接单大厅
              </Button>
              <Button variant="outline" onClick={() => router.push("/escort/coach/orders")}>
                我的订单
              </Button>
            </>
          )}
          {user?.roles?.includes("admin") && (
            <Button variant="outline" onClick={() => router.push("/admin/rules")}>
              管理后台 · 规则配置
            </Button>
          )}
          <Button variant="outline" onClick={() => router.push("/friends")}>
            我的好友
          </Button>
        </div>

        <Button onClick={handleLogout} variant="ghost">
          退出登录
        </Button>
        <div className="mt-2 flex justify-center gap-4">
          <Button variant="link" onClick={() => router.push("/profile")} className="text-sm">
            个人中心
          </Button>
          <Button variant="link" onClick={() => router.push("/settings/password")} className="text-sm">
            修改密码
          </Button>
        </div>
      </div>
    </div>
  );
}
