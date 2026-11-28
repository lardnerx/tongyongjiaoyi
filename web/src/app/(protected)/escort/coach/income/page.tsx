"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { Button } from "@/components/ui/button";
import type { OrderInfo } from "@/types/escort";
import { formatCarType } from "@/types/escort";

/** 时间字符串格式化（空值返回「—」）。 */
function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN");
}

/** 收入清单：客户已确认支付的订单明细与合计。 */
export default function CoachIncomePage() {
  const router = useRouter();
  const { user } = useAuthStore();

  const { data: orders, isLoading } = useQuery({
    queryKey: ["coach-orders", user?.user_id],
    queryFn: () =>
      apiClient.get<OrderInfo[]>(`/escort/orders?coach_id=${user?.user_id}`),
    enabled: !!user?.user_id,
    staleTime: 0,
  });

  // 已支付订单按下单时间倒序，最新收入在前
  const settledOrders = (orders ?? [])
    .filter((order) => !!order.customer_confirmed_at)
    .sort((a, b) =>
      (b.customer_confirmed_at || "").localeCompare(a.customer_confirmed_at || "")
    );
  const total = settledOrders.reduce(
    (sum, order) => sum + (order.settled_amount ?? 0),
    0
  );

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">收入清单</h1>
          <Button variant="ghost" onClick={() => router.push("/profile")}>
            返回
          </Button>
        </div>

        {/* 收入合计 */}
        <div className="rounded-xl bg-gray-900 p-6 text-center text-white">
          <p className="text-sm text-gray-400">累计收入</p>
          <p className="mt-2 text-4xl font-bold">¥{total.toFixed(2)}</p>
          <p className="mt-2 text-xs text-gray-400">
            已结算 {settledOrders.length} 单
          </p>
        </div>

        {isLoading && <p className="text-gray-500">加载中...</p>}

        {!isLoading && settledOrders.length === 0 && (
          <p className="text-gray-500 text-center py-8">暂无收入记录</p>
        )}

        <div className="space-y-3">
          {settledOrders.map((order) => (
            <div
              key={order.task_id}
              className="bg-white rounded-lg border p-4 cursor-pointer hover:shadow-md transition space-y-2"
              onClick={() =>
                router.push(`/escort/coach/orders/${order.task_id}`)
              }
            >
              <div className="flex justify-between items-start">
                <span className="text-sm text-gray-500">
                  {order.task_id.slice(0, 8)}
                </span>
                <span className="font-medium text-green-600">
                  +¥{(order.settled_amount ?? 0).toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">车型 / 时长</span>
                <span>
                  {formatCarType(order.car_type)} · {order.duration_hours}小时
                </span>
              </div>
              <div className="flex justify-between gap-4 text-sm">
                <span className="shrink-0 text-gray-500">上车地点</span>
                <span className="break-all text-right">
                  {order.origin_address || "未记录"}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">支付时间</span>
                <span>{formatTime(order.customer_confirmed_at)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
