"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import { useWsEvent } from "@/hooks/use-ws-events";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";
import { Button } from "@/components/ui/button";
import type { OrderInfo } from "@/types/escort";

export default function CoachHallPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const [pendingOrders, setPendingOrders] = useState<OrderInfo[]>([]);
  const [claiming, setClaiming] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { claimedOrderIds } = useOrderRealtimeStore();

  // 教练上线
  useEffect(() => {
    if (!user?.user_id) return;
    apiClient
      .post(`/escort/coaches/${user.user_id}/online`, { lat: 39.9, lng: 116.4 })
      .catch(() => {});
    return () => {
      apiClient.post(`/escort/coaches/${user.user_id}/offline`, null).catch(() => {});
    };
  }, [user?.user_id]);

  // WS 收到新订单
  const handleNewOrder = useCallback((data: Record<string, unknown>) => {
    const newOrder: OrderInfo = {
      task_id: data.task_id as string,
      order_type: "REALTIME",
      status: "published",
      demander_id: data.demander_id as string,
      car_type: data.car_type as string,
      duration_hours: data.duration_hours as number,
      assigned_resource_id: null,
      title: null,
    };
    setPendingOrders((prev) => [newOrder, ...prev]);
  }, []);

  useWsEvent("task.published", handleNewOrder);

  // WS 收到被抢通知
  useWsEvent("task.claimed", (data) => {
    const taskId = data.task_id as string;
    useOrderRealtimeStore.getState().markClaimed(taskId);
  });

  const handleClaim = async (taskId: string) => {
    setClaiming(taskId);
    setError("");
    try {
      await apiClient.post(`/escort/orders/${taskId}/claim`, {
        coach_id: user?.user_id,
      });
      router.push(`/escort/coach/orders/${taskId}`);
    } catch (e: any) {
      setError(e.message || "抢单失败");
      useOrderRealtimeStore.getState().markClaimed(taskId);
    } finally {
      setClaiming(null);
    }
  };

  const visibleOrders = pendingOrders.filter((o) => !claimedOrderIds.has(o.task_id));

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">接单大厅</h1>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>返回</Button>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        {visibleOrders.length === 0 && (
          <p className="text-gray-500 text-center py-8">暂无待接订单，等待推送...</p>
        )}

        <div className="space-y-3">
          {visibleOrders.map((order) => (
            <div key={order.task_id} className="bg-white rounded-lg border p-4 space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">{order.task_id.slice(0, 8)}</span>
                <span>{order.car_type === "manual" ? "手动挡" : "自动挡"}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span>时长：{order.duration_hours}小时</span>
                <span>学员：{order.demander_id.slice(0, 8)}</span>
              </div>
              <Button
                className="w-full"
                onClick={() => handleClaim(order.task_id)}
                disabled={claiming === order.task_id}
              >
                {claiming === order.task_id ? "抢单中..." : "立即抢单"}
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
