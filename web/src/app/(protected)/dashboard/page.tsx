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

  const canBeCoach = user?.roles?.includes("supplier");

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-md space-y-6 text-center">
        <h1 className="text-3xl font-bold">欢迎，{user?.name || "用户"}</h1>
        <p className="text-gray-600">用户 ID: {user?.user_id}</p>
        <p className="text-gray-600">当前角色: {activeRole || "未设置"}</p>

        {/* 角色切换 */}
        <div className="flex gap-2 justify-center">
          <Button
            variant={activeRole === "demander" ? "default" : "outline"}
            onClick={() => handleSwitchRole("demander")}
            disabled={switching}
          >
            学员
          </Button>
          {canBeCoach && (
            <Button
              variant={activeRole === "supplier" ? "default" : "outline"}
              onClick={() => handleSwitchRole("supplier")}
              disabled={switching}
            >
              教练
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
        </div>

        <Button onClick={handleLogout} variant="ghost">
          退出登录
        </Button>
      </div>
    </div>
  );
}
