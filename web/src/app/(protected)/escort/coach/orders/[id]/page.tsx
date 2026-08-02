"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useReviews, useInvalidateOrder } from "@/hooks/use-orders";
import { useWsEvent } from "@/hooks/use-ws-events";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { ReviewForm } from "@/components/review-form";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import type { OrderStatus } from "@/types/escort";

export default function CoachOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuthStore();
  const taskId = params.id as string;
  const { data: order, isLoading } = useOrder(taskId);
  const { data: reviews } = useReviews(taskId);
  const invalidate = useInvalidateOrder(taskId);
  const [actionLoading, setActionLoading] = useState(false);

  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());

  const hasReviewed = reviews?.some((r) => r.reviewer_id === user?.user_id);

  const handleCheckIn = async () => {
    setActionLoading(true);
    try {
      await apiClient.post(`/escort/orders/${taskId}/check-in`, {
        coach_id: user?.user_id,
        lat: 39.9,
        lng: 116.4,
      });
      invalidate();
    } finally {
      setActionLoading(false);
    }
  };

  const handleCheckOut = async () => {
    setActionLoading(true);
    try {
      await apiClient.post(`/escort/orders/${taskId}/check-out`, {
        coach_id: user?.user_id,
        lat: 39.9,
        lng: 116.4,
      });
      invalidate();
    } finally {
      setActionLoading(false);
    }
  };

  if (isLoading) return <div className="p-4">加载中...</div>;
  if (!order) return <div className="p-4">订单不存在</div>;

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">订单详情</h1>
          <Button variant="ghost" onClick={() => router.push("/escort/coach/orders")}>返回</Button>
        </div>

        <div className="bg-white rounded-lg border p-4 space-y-2">
          <div className="flex justify-between">
            <span className="text-gray-500">状态</span>
            <OrderStatusBadge status={order.status as OrderStatus} />
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">学员</span>
            <span>{order.demander_id}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">车型</span>
            <span>{order.car_type === "manual" ? "手动挡" : "自动挡"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">时长</span>
            <span>{order.duration_hours}小时</span>
          </div>
        </div>

        {/* 操作按钮 */}
        {order.status === "assigned" && (
          <Button className="w-full" onClick={handleCheckIn} disabled={actionLoading}>
            {actionLoading ? "签到中..." : "签到"}
          </Button>
        )}
        {order.status === "in_progress" && (
          <Button className="w-full" onClick={handleCheckOut} disabled={actionLoading}>
            {actionLoading ? "签退中..." : "签退"}
          </Button>
        )}

        {/* 评价 */}
        {order.status === "completed" && !hasReviewed && user && (
          <div className="bg-white rounded-lg border p-4">
            <ReviewForm
              taskId={taskId}
              reviewerId={user.user_id}
              reviewerRole="COACH"
              onSubmitted={invalidate}
            />
          </div>
        )}
        {order.status === "completed" && hasReviewed && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
            <p className="text-green-800">已评价</p>
          </div>
        )}
      </div>
    </div>
  );
}
