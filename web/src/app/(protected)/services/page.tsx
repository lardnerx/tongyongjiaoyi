"use client";

import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ServiceItem {
  key: string;
  name: string;
  description: string;
  href: string | null;
  icon: React.ReactNode;
}

const iconClass = "h-7 w-7";

export default function ServicesPage() {
  const router = useRouter();
  const { user, activeRole, logout } = useAuthStore();

  const escortHref =
    activeRole === "supplier" ? "/escort/coach" : "/escort/student";
  // 个人主页：学员进入陪驾个人主页，教练仍回控制台
  const homeHref = activeRole === "supplier" ? "/dashboard" : "/escort/student";

  const services: ServiceItem[] = [
    {
      key: "ride",
      name: "网约车",
      description: "实时叫车，就近派单",
      href: null,
      icon: (
        <svg
          className={iconClass}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 16h18" />
          <path d="M5 16V9.5L7.2 6h9.6L19 9.5V16" />
          <path d="M7 6h10" />
          <circle cx="7.5" cy="16" r="1.8" />
          <circle cx="16.5" cy="16" r="1.8" />
          <path d="M9 19.5l-1 1.5M15 19.5l1 1.5" />
        </svg>
      ),
    },
    {
      key: "escort",
      name: "陪驾",
      description: "实时或预约陪驾，专业教练上门",
      href: escortHref,
      icon: (
        <svg
          className={iconClass}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M19 17h2l.4-2.6a2 2 0 0 0-1.4-2.3l-1.6-.5-2.1-3.1a2 2 0 0 0-1.7-.9H8.4a2 2 0 0 0-1.7.9L4.6 11.6l-1.6.5a2 2 0 0 0-1.4 2.3L2 17h2" />
          <circle cx="7" cy="17" r="2" />
          <circle cx="17" cy="17" r="2" />
          <path d="M9 17h6" />
        </svg>
      ),
    },
    {
      key: "tire",
      name: "应急补胎",
      description: "道路现场补胎、换胎",
      href: null,
      icon: (
        <svg
          className={iconClass}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="9" />
          <circle cx="12" cy="12" r="3.5" />
          <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
        </svg>
      ),
    },
    {
      key: "jump-start",
      name: "应急搭电",
      description: "电瓶亏电快速搭电",
      href: null,
      icon: (
        <svg
          className={iconClass}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="2" y="8" width="16" height="10" rx="2" />
          <path d="M18 11h3v4h-3" />
          <path d="M6 8V6h3v2M11 8V6h3v2" />
          <path d="M8 13h4" />
        </svg>
      ),
    },
    {
      key: "charging",
      name: "应急充电",
      description: "新能源车移动应急充电",
      href: null,
      icon: (
        <svg
          className={iconClass}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M13 2 4.5 13.5H11l-1 8.5L19.5 10H13l0-8Z" />
        </svg>
      ),
    },
    {
      key: "plumbing",
      name: "即时水电维修",
      description: "水管、电路、门锁等家庭急修",
      href: null,
      icon: (
        <svg
          className={iconClass}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M14.7 6.3a4 4 0 0 0 5 5L21 21l-2-.5-9.5-9.5a4 4 0 0 1-5-5L6 4l1.5 1.5" />
          <path d="M4 4l3 3" />
        </svg>
      ),
    },
    {
      key: "pet",
      name: "即时宠物服务",
      description: "上门喂养、遛狗、宠物洗护",
      href: null,
      icon: (
        <svg
          className={iconClass}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <ellipse cx="6" cy="10" rx="2" ry="2.5" />
          <ellipse cx="18" cy="10" rx="2" ry="2.5" />
          <ellipse cx="9.5" cy="5.5" rx="1.8" ry="2.2" />
          <ellipse cx="14.5" cy="5.5" rx="1.8" ry="2.2" />
          <path d="M12 12c-2.5 0-4.5 2-4.5 4a3 3 0 0 0 4.5 2.6A3 3 0 0 0 16.5 16c0-2-2-4-4.5-4Z" />
        </svg>
      ),
    },
    {
      key: "housekeeping",
      name: "即时家政服务",
      description: "日常保洁、深度清洁、家电清洗",
      href: null,
      icon: (
        <svg
          className={iconClass}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M15 3l6 6" />
          <path d="M13 5l6 6-1.8 1.8a2 2 0 0 1-2.8 0l-3.2-3.2a2 2 0 0 1 0-2.8L13 5Z" />
          <path d="M12 14l-8 7 1-4 7-8" />
          <path d="M4 21h6" />
        </svg>
      ),
    },
  ];

  const handleLogout = async () => {
    logout();
    router.push("/login");
  };

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="mx-auto w-full max-w-3xl space-y-8">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            {user?.name ? `${user.name}，您好` : "您好"}
          </h1>
          <p className="text-sm text-gray-500">请选择需要的服务</p>
        </header>

        <div className="grid gap-4 sm:grid-cols-2">
          {services.map((service) => {
            const available = service.href !== null;
            const content = (
              <div className="flex items-start gap-4">
                <div
                  className={cn(
                    "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl",
                    available ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-400"
                  )}
                >
                  {service.icon}
                </div>
                <div className="min-w-0 flex-1 text-left">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "text-base font-medium",
                        available ? "text-gray-900" : "text-gray-400"
                      )}
                    >
                      {service.name}
                    </span>
                    {!available && (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-400">
                        即将上线
                      </span>
                    )}
                  </div>
                  <p
                    className={cn(
                      "mt-1 text-sm",
                      available ? "text-gray-500" : "text-gray-400"
                    )}
                  >
                    {service.description}
                  </p>
                </div>
              </div>
            );

            if (!available) {
              return (
                <div
                  key={service.key}
                  aria-disabled="true"
                  className="cursor-not-allowed rounded-xl border border-gray-200 bg-white p-5 opacity-70"
                >
                  {content}
                </div>
              );
            }

            return (
              <button
                key={service.key}
                type="button"
                onClick={() => router.push(service.href as string)}
                className="rounded-xl border border-gray-200 bg-white p-5 text-left transition hover:border-gray-300 hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/20"
              >
                {content}
              </button>
            );
          })}
        </div>

        <div className="flex items-center justify-center gap-4">
          <Button variant="link" className="text-sm" onClick={() => router.push(homeHref)}>
            个人主页
          </Button>
          <Button variant="link" className="text-sm" onClick={handleLogout}>
            退出登录
          </Button>
        </div>
      </div>
    </div>
  );
}
