"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/lib/auth-store";
import { useOrders } from "@/hooks/use-orders";
import { apiClient } from "@/lib/api-client";
import { playSuccessTone, speak } from "@/lib/notification-sound";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { Button } from "@/components/ui/button";
import { formatCarType, formatEstimate, formatOrderNo } from "@/types/escort";

/** 时间字符串格式化（空值返回「—」）。 */
function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN");
}

export default function StudentOrdersPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const { data: orders, isLoading } = useOrders(user?.user_id);
  const [payingId, setPayingId] = useState<string | null>(null);
  const [payError, setPayError] = useState("");

  // 确认完成订单并支付
  const handleConfirmPay = async (taskId: string) => {
    if (!window.confirm("确认服务已完成？确认后将支付本单费用。")) return;
    setPayingId(taskId);
    setPayError("");
    try {
      await apiClient.post(`/escort/orders/${taskId}/confirm`, {});
      await queryClient.invalidateQueries({ queryKey: ["orders", user?.user_id] });
      playSuccessTone();
      speak("支付成功");
    } catch {
      setPayError("确认支付失败，请重试");
    } finally {
      setPayingId(null);
    }
  };

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

        {payError && <p className="text-sm text-red-500">{payError}</p>}

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
                  <span className="text-sm text-gray-500">
                    {formatOrderNo(order.order_no, order.task_id)}
                  </span>
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

                {/* 已完成订单：确认完成并支付 */}
                {order.status === "completed" &&
                  (order.customer_confirmed_at ? (
                    <p className="text-right text-sm text-green-600">
                      已确认并支付
                      {order.settled_amount != null
                        ? ` ¥${order.settled_amount.toFixed(2)}`
                        : ""}
                    </p>
                  ) : (
                    <Button
                      className="w-full"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleConfirmPay(order.task_id);
                      }}
                      disabled={payingId === order.task_id}
                    >
                      {payingId === order.task_id
                        ? "支付中..."
                        : `确认完成并支付 ${formatEstimate(order.car_type, order.duration_hours)}`}
                    </Button>
                  ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
