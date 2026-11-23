"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import { useWsEvent } from "@/hooks/use-ws-events";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";
import { MapView } from "@/components/map-view";
import { Button } from "@/components/ui/button";
import type { OrderInfo } from "@/types/escort";
import { formatCarType, formatEstimate } from "@/types/escort";

interface OrderWithLocation extends OrderInfo {
  origin_lat?: number;
  origin_lng?: number;
}

/** 两点间球面距离（公里）。 */
function distanceKm(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number }
): number {
  const R = 6371;
  const toRad = (v: number) => (v * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export default function CoachHallPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const [pendingOrders, setPendingOrders] = useState<OrderWithLocation[]>([]);
  const [claiming, setClaiming] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [mapMode, setMapMode] = useState(false);
  const [driverPos, setDriverPos] = useState<{ lat: number; lng: number } | null>(null);
  const { claimedOrderIds } = useOrderRealtimeStore();

  // 教练上线
  useEffect(() => {
    if (!user?.user_id) return;
    // 使用浏览器定位
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const lat = pos.coords.latitude;
          const lng = pos.coords.longitude;
          setDriverPos({ lat, lng });
          apiClient
            .post(`/escort/coaches/${user.user_id}/online`, { lat, lng })
            .catch(() => {});
        },
        () => {
          // 定位失败，使用默认坐标
          setDriverPos({ lat: 39.9, lng: 116.4 });
          apiClient
            .post(`/escort/coaches/${user.user_id}/online`, { lat: 39.9, lng: 116.4 })
            .catch(() => {});
        }
      );
    } else {
      setDriverPos({ lat: 39.9, lng: 116.4 });
      apiClient
        .post(`/escort/coaches/${user.user_id}/online`, { lat: 39.9, lng: 116.4 })
        .catch(() => {});
    }
    return () => {
      apiClient.post(`/escort/coaches/${user.user_id}/offline`, null).catch(() => {});
    };
  }, [user?.user_id]);

  // 进入大厅时主动拉取待抢订单并定期刷新：WS 推送是实时通道，
  // 司机下单时不在线或刷新页面后会错过推送，需要靠拉取补齐。
  useEffect(() => {
    let cancelled = false;
    const loadAvailable = async () => {
      try {
        const list = await apiClient.get<OrderWithLocation[]>("/escort/orders/available");
        if (cancelled || !Array.isArray(list)) return;
        setPendingOrders((prev) => {
          const merged = new Map(prev.map((o) => [o.task_id, o]));
          for (const order of list) {
            if (!merged.has(order.task_id)) merged.set(order.task_id, order);
          }
          return Array.from(merged.values());
        });
      } catch {
        // 拉取失败时依赖 WS 推送
      }
    };
    loadAvailable();
    const timer = setInterval(loadAvailable, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  // WS 收到新订单
  const handleNewOrder = useCallback((data: Record<string, unknown>) => {
    const newOrder: OrderWithLocation = {
      task_id: data.task_id as string,
      order_type: "REALTIME",
      status: "published",
      demander_id: data.demander_id as string,
      car_type: data.car_type as string,
      origin_address: (data.origin_address as string) ?? null,
      duration_hours: data.duration_hours as number,
      assigned_resource_id: null,
      title: null,
      created_at: data.created_at as string | undefined,
      origin_lat: data.origin_lat as number | undefined,
      origin_lng: data.origin_lng as number | undefined,
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

  // 地图标记点
  const mapPoints = visibleOrders
    .filter((o) => o.origin_lat != null && o.origin_lng != null)
    .map((o) => ({
      id: o.task_id,
      lat: o.origin_lat!,
      lng: o.origin_lng!,
      label: `${formatCarType(o.car_type)} · ${o.duration_hours}h`,
    }));

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">接单大厅</h1>
          <div className="flex gap-2">
            <Button
              variant={mapMode ? "default" : "ghost"}
              size="sm"
              onClick={() => setMapMode(!mapMode)}
            >
              {mapMode ? "列表" : "地图"}
            </Button>
            <Button variant="ghost" onClick={() => router.push("/dashboard")}>
              返回
            </Button>
          </div>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        {/* 地图模式 */}
        {mapMode && (
          <div className="space-y-2">
            <MapView
              points={mapPoints}
              className="w-full h-96 rounded-lg"
              onPointClick={(taskId) => handleClaim(taskId)}
            />
            <p className="text-xs text-gray-400 text-center">
              点击地图上的标记可快速抢单
            </p>
          </div>
        )}

        {/* 列表模式 */}
        {!mapMode && visibleOrders.length === 0 && (
          <p className="text-gray-500 text-center py-8">暂无待接订单，等待推送...</p>
        )}

        {!mapMode && (
          <div className="space-y-3">
            {visibleOrders.map((order) => (
              <div key={order.task_id} className="bg-white rounded-lg border p-4 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">订单 {order.task_id.slice(0, 8)}</span>
                  <span className="font-medium">{formatCarType(order.car_type)}</span>
                </div>
                <p className="text-sm text-gray-700">
                  起点：
                  {order.origin_address ||
                    (order.origin_lat != null && order.origin_lng != null
                      ? `${order.origin_lat.toFixed(4)}, ${order.origin_lng.toFixed(4)}`
                      : "未提供")}
                </p>
                <div className="flex justify-between text-sm">
                  <span>时长：{order.duration_hours} 小时</span>
                  <span>预估：{formatEstimate(order.car_type, order.duration_hours)}</span>
                </div>
                <div className="flex justify-between text-xs text-gray-400">
                  <span>
                    {order.created_at
                      ? `下单时间：${new Date(order.created_at).toLocaleTimeString("zh-CN", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}`
                      : `客户：${order.demander_id.slice(0, 8)}`}
                  </span>
                  {driverPos && order.origin_lat != null && order.origin_lng != null && (
                    <span>
                      距离约{" "}
                      {distanceKm(driverPos, {
                        lat: order.origin_lat,
                        lng: order.origin_lng,
                      }).toFixed(1)}{" "}
                      km
                    </span>
                  )}
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
        )}
      </div>
    </div>
  );
}