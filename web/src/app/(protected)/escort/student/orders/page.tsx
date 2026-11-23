"use client";

import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrders } from "@/hooks/use-orders";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { Button } from "@/components/ui/button";
import { formatCarType, formatEstimate } from "@/types/escort";

/** 时间字符串格式化（空值返回「—」）。 */
function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN");
}

export default function StudentOrdersPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: orders, isLoading } = useOrders(user?.user_id);
  // 按下单时间倒序展示，新单在前
  const sortedOrders = orders
    ? [...orders].sort((a, b) =>
        (b.created_at || "").localeCompare(a.created_at || "")
      )
    : undefined;

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">我的订单</h1>
          <Button variant="ghost" onClick={() => router.push("/escort/student")}>返回</Button>
        </div>

        {isLoading && <p className="text-gray-500">加载中...</p>}

        {sortedOrders && sortedOrders.length === 0 && (
          <p className="text-gray-500 text-center py-8">暂无订单</p>
        )}

        <div className="space-y-3">
          {sortedOrders?.map((order) => {
            const isScheduled = order.order_type === "SCHEDULED";
            return (
              <div
                key={order.task_id}
                className="bg-white rounded-lg border p-4 cursor-pointer hover:shadow-md transition space-y-2"
                onClick={() => router.push(`/escort/student/orders/${order.task_id}`)}
              >
                <div className="flex justify-between items-start">
                  <span className="text-sm text-gray-500">{order.task_id.slice(0, 8)}</span>
                  <OrderStatusBadge status={order.status} />
                </div>

                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">订单类型</span>
                  <span>{isScheduled ? "预约单" : "实时单"}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">车型 / 时长</span>
                  <span>
                    {formatCarType(order.car_type)} · {order.duration_hours}小时
                  </span>
                </div>
                <div className="flex justify-between gap-4 text-sm">
                  <span className="shrink-0 text-gray-500">上车地点</span>
                  <span className="break-all text-right">{order.origin_address || "未记录"}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">预估价格</span>
                  <span className="font-medium">
                    {formatEstimate(order.car_type, order.duration_hours)}
                  </span>
                </div>
                {isScheduled && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">预约时间</span>
                    <span>{formatTime(order.scheduled_at)}</span>
                  </div>
                )}
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">下单时间</span>
                  <span>{formatTime(order.created_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
