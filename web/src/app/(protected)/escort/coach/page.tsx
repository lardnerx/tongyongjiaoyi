"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { apiClient } from "@/lib/api-client";
import { useWsEvent } from "@/hooks/use-ws-events";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";
import {
  isSoundEnabled,
  notifyNewOrder,
  playAlertTone,
  playSuccessTone,
  setSoundEnabled,
  speak,
} from "@/lib/notification-sound";
import { MapView, loadAmapSDK, reverseGeocodeAddress } from "@/components/map-view";
import { Button } from "@/components/ui/button";
import type { OrderInfo } from "@/types/escort";
import { formatCarType, formatEstimate, formatOrderNo } from "@/types/escort";

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
  const [driverAddress, setDriverAddress] = useState("");
  const { claimedOrderIds } = useOrderRealtimeStore();
  // 新单弹窗与提示音开关
  const [soundOn, setSoundOn] = useState(true);
  const [orderToast, setOrderToast] = useState<{
    order: OrderWithLocation;
    count: number;
  } | null>(null);
  const knownIdsRef = useRef<Set<string>>(new Set());
  const initialLoadedRef = useRef(false);

  useEffect(() => {
    setSoundOn(isSoundEnabled());
  }, []);

  // 弹窗 8 秒后自动关闭
  useEffect(() => {
    if (!orderToast) return;
    const timer = setTimeout(() => setOrderToast(null), 8000);
    return () => clearTimeout(timer);
  }, [orderToast]);

  /** 新订单提示：弹窗 + 提示音 + 语音播报（首次加载不提示）。 */
  const announceNewOrders = useCallback((fresh: OrderWithLocation[]) => {
    if (fresh.length === 0) return;
    setOrderToast({ order: fresh[0], count: fresh.length });
    notifyNewOrder();
  }, []);

  // 教练上线（同时把当前位置解析成具体地址，供大厅展示）
  useEffect(() => {
    if (!user?.user_id) return;
    const goOnline = (lat: number, lng: number) => {
      setDriverPos({ lat, lng });
      apiClient
        .post(`/escort/coaches/${user.user_id}/online`, { lat, lng })
        .catch(() => {});
      loadAmapSDK()
        .then(() => reverseGeocodeAddress(lat, lng))
        .then((address) => {
          if (address) setDriverAddress(address);
        })
        .catch(() => {});
    };
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => goOnline(pos.coords.latitude, pos.coords.longitude),
        () => goOnline(39.9, 116.4)
      );
    } else {
      goOnline(39.9, 116.4);
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
        // 找出本次拉取中新增的订单，用于弹窗与语音提示
        const fresh = list.filter((o) => !knownIdsRef.current.has(o.task_id));
        list.forEach((o) => knownIdsRef.current.add(o.task_id));
        if (initialLoadedRef.current && fresh.length > 0) {
          announceNewOrders(fresh as OrderWithLocation[]);
        }
        initialLoadedRef.current = true;
        setPendingOrders((prev) => {
          const merged = new Map(prev.map((o) => [o.task_id, o]));
          for (const order of list) {
            const existing = merged.get(order.task_id);
            // 以接口数据为准（补齐订单号/客户姓名/坐标），但绝不丢失已有坐标
            merged.set(
              order.task_id,
              existing
                ? {
                    ...existing,
                    ...order,
                    origin_lat: order.origin_lat ?? existing.origin_lat,
                    origin_lng: order.origin_lng ?? existing.origin_lng,
                    order_no: order.order_no ?? existing.order_no,
                    demander_name: order.demander_name ?? existing.demander_name,
                  }
                : order
            );
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
  }, [announceNewOrders]);

  // WS 收到新订单
  const handleNewOrder = useCallback((data: Record<string, unknown>) => {
    const newOrder: OrderWithLocation = {
      task_id: data.task_id as string,
      order_type: "REALTIME",
      status: "published",
      demander_id: data.demander_id as string,
      demander_name: (data.demander_name as string) ?? null,
      order_no: (data.order_no as string) ?? null,
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
    // 已通过轮询见过该单时不再重复提示
    if (!knownIdsRef.current.has(newOrder.task_id)) {
      knownIdsRef.current.add(newOrder.task_id);
      announceNewOrders([newOrder]);
    }
  }, [announceNewOrders]);

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
      playSuccessTone();
      speak("抢单成功");
      router.push(`/escort/coach/orders/${taskId}`);
    } catch (e: any) {
      setError(e.message || "抢单失败");
      useOrderRealtimeStore.getState().markClaimed(taskId);
    } finally {
      setClaiming(null);
    }
  };

  const visibleOrders = pendingOrders.filter((o) => !claimedOrderIds.has(o.task_id));

  /** 订单上车点距司机的直线距离（公里）；未定位或订单无坐标时返回 null。 */
  const distanceTo = (order: OrderWithLocation): number | null => {
    if (!driverPos || order.origin_lat == null || order.origin_lng == null) {
      return null;
    }
    return distanceKm(driverPos, {
      lat: order.origin_lat,
      lng: order.origin_lng,
    });
  };

  // 地图标记点：待抢订单（标注距离）+ 司机当前位置（绿色标记）
  const mapPoints = visibleOrders
    .filter((o) => o.origin_lat != null && o.origin_lng != null)
    .map((o) => {
      const distance = distanceTo(o);
      return {
        id: o.task_id,
        lat: o.origin_lat!,
        lng: o.origin_lng!,
        label: `${formatCarType(o.car_type)} · ${o.duration_hours}h${
          distance != null ? ` · ${distance.toFixed(1)}km` : ""
        }`,
      };
    });

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">接单大厅</h1>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                const next = !soundOn;
                setSoundOn(next);
                setSoundEnabled(next);
                if (next) playAlertTone();
              }}
            >
              {soundOn ? "提示音开" : "提示音关"}
            </Button>
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

        {/* 司机当前位置 */}
        <p className="text-xs text-gray-500">
          我的位置：
          {driverAddress
            ? driverAddress
            : driverPos
              ? `已定位（${driverPos.lat.toFixed(4)}, ${driverPos.lng.toFixed(4)}）`
              : "定位中..."}
        </p>

        {/* 新订单弹窗提示 */}
        {orderToast && (
          <div className="fixed left-1/2 top-4 z-50 w-[92%] max-w-sm -translate-x-1/2 rounded-xl border border-amber-300 bg-white p-4 shadow-lg">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-amber-600">
                  {orderToast.count > 1
                    ? `有 ${orderToast.count} 个新订单`
                    : "新订单"}
                </p>
                <p className="mt-1 truncate text-sm text-gray-700">
                  起点：{orderToast.order.origin_address || "未提供"}
                </p>
                <p className="mt-0.5 text-sm text-gray-500">
                  {formatCarType(orderToast.order.car_type)} ·{" "}
                  {orderToast.order.duration_hours} 小时 ·{" "}
                  {formatEstimate(
                    orderToast.order.car_type,
                    orderToast.order.duration_hours
                  )}
                </p>
              </div>
              <button
                type="button"
                aria-label="关闭提示"
                className="text-lg leading-none text-gray-400"
                onClick={() => setOrderToast(null)}
              >
                ×
              </button>
            </div>
          </div>
        )}

        {/* 地图模式 */}
        {mapMode && (
          <div className="space-y-2">
            <MapView
              points={mapPoints}
              center={driverPos ?? undefined}
              self={driverPos ?? undefined}
              className="w-full h-96 rounded-lg"
              onPointClick={(taskId) => handleClaim(taskId)}
            />
            <p className="text-xs text-gray-400 text-center">
              蓝色为待抢订单，绿色为我的位置；点击订单标记可快速抢单
            </p>
          </div>
        )}

        {/* 列表模式 */}
        {!mapMode && visibleOrders.length === 0 && (
          <p className="text-gray-500 text-center py-8">暂无待接订单，等待推送...</p>
        )}

        {!mapMode && (
          <div className="space-y-3">
            {visibleOrders.map((order) => {
              const distance = distanceTo(order);
              return (
              <div key={order.task_id} className="bg-white rounded-lg border p-4 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">
                    订单 {formatOrderNo(order.order_no, order.task_id)}
                  </span>
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
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-500">距我</span>
                  <span className="font-medium text-blue-600">
                    {distance != null
                      ? `${distance.toFixed(1)} km`
                      : driverPos
                        ? "距离未知"
                        : "定位中..."}
                  </span>
                </div>
                <div className="flex justify-between gap-3 text-xs text-gray-500">
                  <span>
                    {order.created_at
                      ? `下单时间：${new Date(order.created_at).toLocaleTimeString("zh-CN", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}`
                      : "下单时间：—"}
                  </span>
                  <span className="truncate">
                    客户：{order.demander_name || "未命名客户"}
                  </span>
                </div>
                <Button
                  className="w-full"
                  onClick={() => handleClaim(order.task_id)}
                  disabled={claiming === order.task_id}
                >
                  {claiming === order.task_id ? "抢单中..." : "立即抢单"}
                </Button>
              </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}