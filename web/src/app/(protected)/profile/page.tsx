"use client";

import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import AvatarUpload from "@/components/avatar-upload";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const ROLE_LABELS: Record<string, string> = {
  demander: "学员",
  supplier: "教练",
  admin: "管理员",
};

export default function ProfilePage() {
  const router = useRouter();
  const { user, logout, setUser } = useAuthStore();

  const handleLogout = async () => {
    try {
      await apiClient.post("/auth/logout", null);
    } catch {
      // ignore
    }
    logout();
    router.push("/login");
  };

  const handleAvatarSuccess = async () => {
    // 重新获取用户信息以更新头像 URL
    try {
      type T = import("@/types/api").UserInfo;
      const userInfo = await apiClient.get<T>("/auth/me");
      if (userInfo) {
        setUser(userInfo);
      }
    } catch {
      // ignore
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-lg space-y-6">
        {/* 页面标题 */}
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => router.push("/dashboard")}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M19 12H5" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </Button>
          <h1 className="text-2xl font-bold">个人中心</h1>
        </div>

        {/* 头像卡片 */}
        <Card>
          <CardContent className="flex flex-col items-center py-6">
            <AvatarUpload
              currentAvatarUrl={user?.avatar_url || null}
              onSuccess={handleAvatarSuccess}
            />
            <h2 className="mt-3 text-xl font-semibold">{user?.name || "用户"}</h2>
            <p className="text-sm text-gray-500">
              {user?.active_role
                ? ROLE_LABELS[user.active_role] || user.active_role
                : "未设置角色"}
            </p>
          </CardContent>
        </Card>

        {/* 个人信息卡片 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">个人信息</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between border-b pb-2">
              <span className="text-gray-500">用户 ID</span>
              <span className="font-mono text-sm">{user?.user_id}</span>
            </div>
            <div className="flex justify-between border-b pb-2">
              <span className="text-gray-500">昵称</span>
              <span>{user?.name}</span>
            </div>
            <div className="flex justify-between border-b pb-2">
              <span className="text-gray-500">角色</span>
              <div className="flex gap-1">
                {user?.roles?.map((role) => (
                  <span
                    key={role}
                    className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-600"
                  >
                    {ROLE_LABELS[role] || role}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">当前角色</span>
              <span>{user?.active_role ? ROLE_LABELS[user.active_role] || user.active_role : "未设置"}</span>
            </div>
          </CardContent>
        </Card>

        {/* 快捷操作卡片 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">快捷操作</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button
              variant="outline"
              className="w-full justify-start"
              onClick={() => router.push("/settings/password")}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="mr-2"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              修改密码
            </Button>
            <Button
              variant="outline"
              className="w-full justify-start"
              onClick={() => router.push("/dashboard")}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="mr-2"
              >
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
              </svg>
              返回首页
            </Button>
            <Button
              variant="ghost"
              className="w-full justify-start text-red-500 hover:bg-red-50 hover:text-red-600"
              onClick={handleLogout}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="mr-2"
              >
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
              退出登录
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}