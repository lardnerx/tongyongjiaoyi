"use client";

import { useParams, useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useReviews, useInvalidateOrder } from "@/hooks/use-orders";
import { useWsEvent } from "@/hooks/use-ws-events";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { ReviewForm } from "@/components/review-form";
import { Button } from "@/components/ui/button";
import type { OrderStatus } from "@/types/escort";

export default function StudentOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuthStore();
  const taskId = params.id as string;
  const { data: order, isLoading } = useOrder(taskId);
  const { data: reviews } = useReviews(taskId);
  const invalidate = useInvalidateOrder(taskId);
  const { orderStatusUpdates } = useOrderRealtimeStore();

  // WS 事件 → 刷新订单
  useWsEvent("task.assigned", () => invalidate());
  useWsEvent("task.in_service", () => invalidate());
  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());

  const currentStatus = orderStatusUpdates[taskId] || order?.status;
  const hasReviewed = reviews?.some((r) => r.reviewer_id === user?.user_id);

  if (isLoading) return <div className="p-4">加载中...</div>;
  if (!order) return <div className="p-4">订单不存在</div>;

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">订单详情</h1>
          <Button variant="ghost" onClick={() => router.push("/escort/student/orders")}>返回</Button>
        </div>

        <div className="bg-white rounded-lg border p-4 space-y-2">
          <div className="flex justify-between">
            <span className="text-gray-500">状态</span>
            <OrderStatusBadge status={currentStatus as OrderStatus} />
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">车型</span>
            <span>{order.car_type === "manual" ? "手动挡" : "自动挡"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">时长</span>
            <span>{order.duration_hours}小时</span>
          </div>
          {order.assigned_resource_id && (
            <div className="flex justify-between">
              <span className="text-gray-500">教练</span>
              <span>{order.assigned_resource_id}</span>
            </div>
          )}
        </div>

        {currentStatus === "published" && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center">
            <p className="text-yellow-800">等待教练接单...</p>
          </div>
        )}

        {currentStatus === "completed" && !hasReviewed && user && (
          <div className="bg-white rounded-lg border p-4">
            <ReviewForm
              taskId={taskId}
              reviewerId={user.user_id}
              reviewerRole="STUDENT"
              onSubmitted={invalidate}
            />
          </div>
        )}

        {currentStatus === "completed" && hasReviewed && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
            <p className="text-green-800">已评价</p>
          </div>
        )}
      </div>
    </div>
  );
}
