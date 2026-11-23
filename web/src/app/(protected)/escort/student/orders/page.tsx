"use client";

import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrders } from "@/hooks/use-orders";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { Button } from "@/components/ui/button";
import { formatCarType } from "@/types/escort";

export default function StudentOrdersPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: orders, isLoading } = useOrders(user?.user_id);

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">我的订单</h1>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>返回</Button>
        </div>

        {isLoading && <p className="text-gray-500">加载中...</p>}

        {orders && orders.length === 0 && (
          <p className="text-gray-500 text-center py-8">暂无订单</p>
        )}

        <div className="space-y-3">
          {orders?.map((order) => (
            <div
              key={order.task_id}
              className="bg-white rounded-lg border p-4 cursor-pointer hover:shadow-md transition"
              onClick={() => router.push(`/escort/student/orders/${order.task_id}`)}
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
