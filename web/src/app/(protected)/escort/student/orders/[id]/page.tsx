"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useReviews, useInvalidateOrder } from "@/hooks/use-orders";
import { useDeal, usePayment } from "@/hooks/use-scheduled";
import { useSendFriendRequest } from "@/hooks/use-friends";
import { useWsEvent } from "@/hooks/use-ws-events";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";
import { apiClient } from "@/lib/api-client";
import { speak } from "@/lib/notification-sound";
import { useCancelRules } from "@/hooks/use-cancel-rules";
import { CountdownTimer } from "@/components/countdown-timer";
import { CancelDialog } from "@/components/cancel-dialog";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { ReviewForm } from "@/components/review-form";
import { Button } from "@/components/ui/button";
import type { OrderStatus } from "@/types/escort";
import { formatCarType, formatEstimate, unitPriceOf } from "@/types/escort";

/** 秒数转 HH:MM:SS。 */
function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return [h, m, sec].map((v) => String(v).padStart(2, "0")).join(":");
}

export default function StudentOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuthStore();
  const taskId = params.id as string;
  // 轮询兜底：WS 断线时也能在 10 秒内同步司机开始/结束服务
  const { data: order, isLoading } = useOrder(taskId, 10_000);
  const { data: reviews } = useReviews(taskId);
  const invalidate = useInvalidateOrder(taskId);
  const { orderStatusUpdates } = useOrderRealtimeStore();

  // 司机开始服务时弹窗提示；计时与司机端同步（都基于 check_in_at）
  const [showStarted, setShowStarted] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const prevStatusRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const status = order?.status;
    if (status) {
      if (prevStatusRef.current && prevStatusRef.current !== "in_progress" && status === "in_progress") {
        setShowStarted(true);
        speak("司机已开始服务");
      }
      if (prevStatusRef.current && prevStatusRef.current !== "completed" && status === "completed") {
        speak("服务已完成，请确认支付");
      }
      prevStatusRef.current = status;
    }
  }, [order?.status]);

  // 预约单：查询 deal 和 payment
  const dealId = order?.deal_id ?? undefined;
  const { data: deal } = useDeal(dealId);
  const { data: payment } = usePayment(dealId);

  // WS 事件 → 刷新
  useWsEvent("task.assigned", () => invalidate());
  useWsEvent("task.in_service", () => {
    invalidate();
    setShowStarted(true);
  });
  useWsEvent("task.completed", () => invalidate());
  useWsEvent("task.cancelled", () => invalidate());
  useWsEvent("deal.confirmed", () => invalidate());
  useWsEvent("deal.rejected", () => invalidate());
  useWsEvent("deal.cancelled", () => invalidate());
  useWsEvent("payment.paid", () => invalidate());

  const currentStatus = orderStatusUpdates[taskId] || order?.status;
  const hasReviewed = reviews?.some((r) => r.reviewer_id === user?.user_id);
  const isScheduled = order?.order_type === "SCHEDULED";

  const sendFriendRequest = useSendFriendRequest();

  const cancelRules = useCancelRules();
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const scheduledPenalty = cancelRules.calculatePenalty(order?.scheduled_at ?? null);

  if (isLoading) return <div className="p-4">加载中...</div>;
  if (!order) return <div className="p-4">订单不存在</div>;

  const checkInMs = order.check_in_at ? Date.parse(order.check_in_at) : null;
  const elapsedSeconds =
    checkInMs !== null && !Number.isNaN(checkInMs)
      ? Math.max(0, (now - checkInMs) / 1000)
      : 0;

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
            <span className="text-gray-500">类型</span>
            <span>{isScheduled ? "预约单" : "实时单"}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="shrink-0 text-gray-500">上车地点</span>
            <span className="break-all text-right">{order.origin_address || "未记录"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">车型</span>
            <span>{formatCarType(order.car_type)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">时长</span>
            <span>{order.duration_hours}小时</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">单价</span>
            <span>
              {unitPriceOf(order.car_type) > 0
                ? `¥${unitPriceOf(order.car_type)}/小时`
                : "—"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">预估价格</span>
            <span className="font-medium">
              {formatEstimate(order.car_type, order.duration_hours)}
            </span>
          </div>
          {isScheduled && order.scheduled_at && (
            <div className="flex justify-between">
              <span className="text-gray-500">预约时间</span>
              <span>{new Date(order.scheduled_at).toLocaleString("zh-CN")}</span>
            </div>
          )}
          {order.created_at && (
            <div className="flex justify-between">
              <span className="text-gray-500">下单时间</span>
              <span>{new Date(order.created_at).toLocaleString("zh-CN")}</span>
            </div>
          )}
          {order.assigned_resource_id && (
            <div className="flex justify-between">
              <span className="text-gray-500">司机</span>
              <span>{order.assigned_resource_id}</span>
            </div>
          )}
          {deal && (
            <div className="flex justify-between">
              <span className="text-gray-500">交易状态</span>
              <span className="text-sm">{deal.status}</span>
            </div>
          )}
        </div>

        {unitPriceOf(order.car_type) > 0 && (
          <p className="text-xs text-gray-400">
            预估价格按 {unitPriceOf(order.car_type)} 元/小时 × {order.duration_hours} 小时估算，实际以订单结算为准。
          </p>
        )}

        {/* 司机已开始服务：与司机端同步计时 */}
        {currentStatus === "in_progress" && (
          <div className="rounded-lg bg-gray-900 p-5 text-center text-white">
            <p className="text-xs text-gray-400">司机已开始服务</p>
            <p className="mt-1 font-mono text-3xl font-bold tracking-wider">
              {formatClock(elapsedSeconds)}
            </p>
            {order.check_in_at && (
              <p className="mt-2 text-xs text-gray-400">
                开始时间：{new Date(order.check_in_at).toLocaleString("zh-CN")}
              </p>
            )}
          </div>
        )}

        {/* 实时单：等待接单 */}
        {!isScheduled && currentStatus === "published" && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 space-y-2">
            <p className="text-sm font-medium text-yellow-800">
              订单已发布，正在通知附近司机
            </p>
            <p className="text-xs text-yellow-600">
              司机接单后会立即通知您；若长时间无人接单，可取消订单后重新叫车。
            </p>
            <div className="flex items-center justify-between pt-1">
              <span className="text-xs text-yellow-700">剩余等待时间</span>
              <CountdownTimer
                createdAt={order.created_at ?? new Date().toISOString()}
                timeoutSeconds={cancelRules.data?.timeout_seconds ?? 300}
              />
            </div>
          </div>
        )}

        {/* 预约单：已选教练，待支付定金 */}
        {isScheduled && dealId && deal?.status === "pending" && payment?.status !== "paid" && (
          <Button
            className="w-full"
            onClick={() => router.push(`/escort/student/orders/${taskId}/pay`)}
          >
            去支付 ¥{deal?.final_amount ? (deal.final_amount * 0.3).toFixed(2) : "0.00"}
          </Button>
        )}

        {/* 预约单：已支付，等待教练确认 */}
        {isScheduled && payment?.status === "paid" && deal?.status === "pending" && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center space-y-1">
            <p className="text-yellow-800">定金已支付，等待司机确认...</p>
            <p className="text-sm text-yellow-600">
              已付定金：¥{payment?.amount ? payment.amount.toFixed(2) : (deal?.final_amount ? (deal.final_amount * 0.3).toFixed(2) : "0.00")}
            </p>
          </div>
        )}

        {/* 预约单：教练已确认，等待签到 */}
        {isScheduled && deal?.status === "active" && currentStatus === "assigned" && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-center">
            <p className="text-blue-800">司机已确认，等待服务开始...</p>
          </div>
        )}

        {/* 预约单：教练拒绝 */}
        {isScheduled && deal?.status === "cancelled" && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-center">
            <p className="text-red-800">司机已拒绝，订单已取消</p>
          </div>
        )}

        {/* 评价 */}
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

        {/* 加好友按钮（订单完成后向教练发送好友请求） */}
        {currentStatus === "completed" && order.assigned_resource_id && (
          <Button
            variant="outline"
            className="w-full"
            onClick={() =>
              sendFriendRequest.mutate({
                toUserId: order.assigned_resource_id as string,
                message: "服务很好，加个好友",
              })
            }
            disabled={sendFriendRequest.isPending}
          >
            {sendFriendRequest.isPending ? "发送中..." : "加好友"}
          </Button>
        )}

        {/* 取消按钮（服务开始前可取消） */}
        {currentStatus !== "in_progress" &&
          currentStatus !== "completed" &&
          currentStatus !== "cancelled" && (
          <Button
            variant="outline"
            className="w-full text-red-600 border-red-300"
            onClick={() => setShowCancelDialog(true)}
          >
            取消订单
          </Button>
        )}

        <CancelDialog
          open={showCancelDialog}
          orderType={order.order_type as "REALTIME" | "SCHEDULED"}
          penalty={isScheduled ? scheduledPenalty : 0}
          onConfirm={async () => {
            await apiClient.post(`/escort/orders/${taskId}/cancel`, {});
            setShowCancelDialog(false);
            invalidate();
          }}
          onClose={() => setShowCancelDialog(false)}
        />

        {/* 司机开始服务弹窗 */}
        {showStarted && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
            role="dialog"
            aria-modal="true"
          >
            <div className="w-full max-w-sm rounded-xl bg-white p-6 text-center shadow-xl">
              <p className="text-lg font-bold">司机已开始服务</p>
              <p className="mt-1 text-sm text-gray-500">
                计时已开始，与司机端同步
              </p>
              <p className="mt-4 font-mono text-4xl font-bold tracking-wider">
                {formatClock(elapsedSeconds)}
              </p>
              {order.check_in_at && (
                <p className="mt-2 text-xs text-gray-400">
                  开始时间：{new Date(order.check_in_at).toLocaleString("zh-CN")}
                </p>
              )}
              <Button className="mt-5 w-full" onClick={() => setShowStarted(false)}>
                知道了
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
