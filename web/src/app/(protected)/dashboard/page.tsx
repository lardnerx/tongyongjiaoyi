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
