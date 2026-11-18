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
    activeRole === "supplier" ? "/escort/coach" : "/escort/student/book-instant";

  const services: ServiceItem[] = [
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
          <Button variant="link" className="text-sm" onClick={() => router.push("/dashboard")}>
            我的账户
          </Button>
          <Button variant="link" className="text-sm" onClick={handleLogout}>
            退出登录
          </Button>
        </div>
      </div>
    </div>
  );
}
