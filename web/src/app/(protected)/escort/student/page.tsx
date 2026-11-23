"use client";

import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { Button } from "@/components/ui/button";

interface EntryItem {
  key: string;
  label: string;
  description: string;
  href: string;
}

/** 陪驾个人主页：从服务列表进入后的功能入口。 */
export default function EscortStudentHomePage() {
  const router = useRouter();
  const { user } = useAuthStore();

  const entries: EntryItem[] = [
    {
      key: "instant",
      label: "实时叫车",
      description: "立即呼叫附近司机",
      href: "/escort/student/book-instant",
    },
    {
      key: "scheduled",
      label: "预约叫车",
      description: "选择时间与司机",
      href: "/escort/student/book-scheduled",
    },
    {
      key: "orders",
      label: "我的订单",
      description: "查看订单明细与进度",
      href: "/escort/student/orders",
    },
    {
      key: "friends",
      label: "我的好友",
      description: "查看司机好友",
      href: "/friends",
    },
    {
      key: "profile",
      label: "我的",
      description: "个人信息、头像与账号设置",
      href: "/profile",
    },
  ];

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="mx-auto w-full max-w-md space-y-6">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold">陪驾 · 个人主页</h1>
            <p className="text-sm text-gray-500">
              {user?.name ? `${user.name}，您好` : "您好"}
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => router.push("/services")}>
            回到服务列表
          </Button>
        </div>

        <div className="space-y-3">
          {entries.map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => router.push(entry.href)}
              className="flex w-full items-center justify-between rounded-xl border border-gray-200 bg-white p-5 text-left transition hover:border-gray-300 hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/20"
            >
              <span className="space-y-1">
                <span className="block text-base font-medium text-gray-900">
                  {entry.label}
                </span>
                <span className="block text-sm text-gray-500">{entry.description}</span>
              </span>
              <svg
                className="h-5 w-5 shrink-0 text-gray-400"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M9 6l6 6-6 6" />
              </svg>
            </button>
          ))}
        </div>

        <Button variant="ghost" className="w-full" onClick={() => router.push("/services")}>
          回到服务列表
        </Button>
      </div>
    </div>
  );
}
