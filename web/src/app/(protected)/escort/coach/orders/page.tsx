"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { Button } from "@/components/ui/button";
import type { OrderInfo } from "@/types/escort";
import { formatCarType } from "@/types/escort";

export default function CoachOrdersPage() {
  const router = useRouter();

  // 教练订单列表（通过查询所有订单，前端筛选 assigned_resource_id 匹配）
  // MVP 阶段简化：查询所有订单，实际应后端提供 coach_id 筛选
  const { data: allOrders, isLoading } = useQuery({
    queryKey: ["coach-orders"],
    queryFn: () => apiClient.get<OrderInfo[]>("/escort/orders?demander_id=_coach_view"),
    staleTime: 30_000,
  });

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">我的订单</h1>
          <Button variant="ghost" onClick={() => router.push("/escort/coach")}>返回大厅</Button>
        </div>

        {isLoading && <p className="text-gray-500">加载中...</p>}

        {(!allOrders || allOrders.length === 0) && (
          <p className="text-gray-500 text-center py-8">暂无订单</p>
        )}

        <div className="space-y-3">
          {allOrders?.filter((o) => o.assigned_resource_id).map((order) => (
            <div
              key={order.task_id}
              className="bg-white rounded-lg border p-4 cursor-pointer hover:shadow-md transition"
              onClick={() => router.push(`/escort/coach/orders/${order.task_id}`)}
            >
              <div className="flex justify-between items-start mb-2">
                <span className="text-sm text-gray-500">{order.task_id.slice(0, 8)}</span>
                <OrderStatusBadge status={order.status} />
              </div>
              <p className="text-sm">{formatCarType(order.car_type)} · {order.duration_hours}小时</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
