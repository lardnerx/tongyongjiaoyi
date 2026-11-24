"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder, useInvalidateOrder } from "@/hooks/use-orders";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import { playSuccessTone, speak } from "@/lib/notification-sound";
import { formatCarType } from "@/types/escort";

/** 秒数转 HH:MM:SS。 */
function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return [h, m, sec].map((v) => String(v).padStart(2, "0")).join(":");
}

/** 服务计时页：开始订单后展示实时计时，结束订单后进入结算页。 */
export default function CoachServicePage() {
  const params = useParams();
  const router = useRouter();
  const taskId = params.id as string;
  const { user } = useAuthStore();
  const { data: order, isLoading } = useOrder(taskId);
  const invalidate = useInvalidateOrder(taskId);
  const [now, setNow] = useState(() => Date.now());
  const [checkingOut, setCheckingOut] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // 已完成订单直接进入结算页
  useEffect(() => {
    if (order?.status === "completed") {
      router.replace(`/escort/coach/orders/${taskId}/settlement`);
    }
  }, [order?.status, router, taskId]);

  const startMs = order?.check_in_at ? Date.parse(order.check_in_at) : null;
  const elapsed =
    startMs !== null && !Number.isNaN(startMs) ? (now - startMs) / 1000 : 0;

  const handleCheckOut = async () => {
    setCheckingOut(true);
    setError("");
    try {
      await apiClient.post(`/escort/orders/${taskId}/check-out`, {
        coach_id: user?.user_id,
        lat: 39.9,
        lng: 116.4,
      });
      invalidate();
      playSuccessTone();
      speak("订单已结束");
      router.replace(`/escort/coach/orders/${taskId}/settlement`);
    } catch {
      setError("结束订单失败，请重试");
    } finally {
      setCheckingOut(false);
    }
  };

  if (isLoading) return <div className="p-4">加载中...</div>;
  if (!order) return <div className="p-4">订单不存在</div>;

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">服务计时</h1>
          <Button
            variant="ghost"
            onClick={() => router.push(`/escort/coach/orders/${taskId}`)}
          >
            返回
          </Button>
        </div>

        {/* 计时卡片 */}
        <div className="rounded-xl bg-gray-900 p-8 text-center text-white">
          <p className="text-sm text-gray-400">已服务时长</p>
          <p className="mt-2 font-mono text-5xl font-bold tracking-wider">
            {formatClock(elapsed)}
          </p>
          {order.check_in_at && (
            <p className="mt-3 text-xs text-gray-400">
              开始时间：{new Date(order.check_in_at).toLocaleString("zh-CN")}
            </p>
          )}
        </div>

        {/* 订单信息 */}
        <div className="space-y-2 rounded-lg border bg-white p-4">
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">车型</span>
            <span>{formatCarType(order.car_type)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">预定时长</span>
            <span>{order.duration_hours} 小时</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">客户</span>
            <span>{order.demander_id}</span>
          </div>
          <div className="flex justify-between gap-4 text-sm">
            <span className="shrink-0 text-gray-500">上车地点</span>
            <span className="break-all text-right">
              {order.origin_address || "未记录"}
            </span>
          </div>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        <Button
          className="w-full"
          onClick={handleCheckOut}
          disabled={checkingOut}
        >
          {checkingOut ? "结束订单中..." : "结束订单"}
        </Button>
        <p className="text-center text-xs text-gray-400">
          服务结束后请点击结束订单，系统将生成本单结算单
        </p>
      </div>
    </div>
  );
}
