"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useReviews, useInvalidateOrder } from "@/hooks/use-orders";
import { useDeal, useConfirmDeal, useRejectDeal } from "@/hooks/use-scheduled";
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
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);

  const dealId = order?.deal_id ?? undefined;
  const { data: deal } = useDeal(dealId);
  const confirmDeal = useConfirmDeal();
  const rejectDeal = useRejectDeal();

  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());
  useWsEvent("deal.confirmed", () => invalidate());
  useWsEvent("deal.rejected", () => invalidate());
  useWsEvent("payment.paid", () => invalidate());

  const hasReviewed = reviews?.some((r) => r.reviewer_id === user?.user_id);
  const isScheduled = order?.order_type === "SCHEDULED";

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

  const handleConfirm = async () => {
    if (!dealId || !user?.user_id) return;
    setActionLoading(true);
    try {
      await confirmDeal.mutateAsync({ dealId, coachId: user.user_id });
      invalidate();
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!dealId || !user?.user_id) return;
    setActionLoading(true);
    try {
      await rejectDeal.mutateAsync({
        dealId,
        coachId: user.user_id,
        reason: rejectReason,
      });
      invalidate();
    } finally {
      setActionLoading(false);
      setShowReject(false);
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
            <span className="text-gray-500">类型</span>
            <span>{isScheduled ? "预约单" : "实时单"}</span>
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
          {isScheduled && order.scheduled_at && (
            <div className="flex justify-between">
              <span className="text-gray-500">预约时间</span>
              <span>{new Date(order.scheduled_at).toLocaleString("zh-CN")}</span>
            </div>
          )}
          {deal && (
            <div className="flex justify-between">
              <span className="text-gray-500">交易状态</span>
              <span className="text-sm">{deal.status}</span>
            </div>
          )}
        </div>

        {/* 预约单：待确认（deal pending + 已支付） */}
        {isScheduled && deal?.status === "pending" && (
          <div className="space-y-3">
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-yellow-800 text-sm">学员已支付定金，请确认是否接单。</p>
            </div>
            {!showReject ? (
              <div className="flex gap-2">
                <Button
                  className="flex-1"
                  onClick={handleConfirm}
                  disabled={actionLoading}
                >
                  {actionLoading ? "确认中..." : "确认接单"}
                </Button>
                <Button
                  variant="destructive"
                  className="flex-1"
                  onClick={() => setShowReject(true)}
                  disabled={actionLoading}
                >
                  拒绝
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                <textarea
                  className="w-full rounded-md border border-gray-300 p-2 text-sm"
                  placeholder="拒绝原因..."
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  rows={2}
                />
                <div className="flex gap-2">
                  <Button
                    variant="destructive"
                    className="flex-1"
                    onClick={handleReject}
                    disabled={actionLoading}
                  >
                    {actionLoading ? "提交中..." : "确认拒绝"}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setShowReject(false)}
                    disabled={actionLoading}
                  >
                    取消
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 签到按钮（实时单 assigned 或 预约单 deal active + task assigned） */}
        {order.status === "assigned" && (!isScheduled || deal?.status === "active") && (
          <Button className="w-full" onClick={handleCheckIn} disabled={actionLoading}>
            {actionLoading ? "签到中..." : "签到"}
          </Button>
        )}
        {order.status === "in_progress" && (
          <Button className="w-full" onClick={handleCheckOut} disabled={actionLoading}>
            {actionLoading ? "签退中..." : "签退"}
          </Button>
        )}

        {/* 已取消状态 */}
        {order.status === "cancelled" && (
          <div className="bg-gray-100 border border-gray-300 rounded-lg p-4 text-center">
            <p className="text-gray-700">订单已取消</p>
          </div>
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
