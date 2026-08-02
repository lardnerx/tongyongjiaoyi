import type { OrderStatus } from "@/types/escort";

const STATUS_LABELS: Record<OrderStatus, string> = {
  draft: "草稿",
  published: "等待接单",
  matching: "匹配中",
  assigned: "已接单",
  in_progress: "服务中",
  completed: "已完成",
  cancelled: "已取消",
};

const STATUS_COLORS: Record<OrderStatus, string> = {
  draft: "bg-gray-100 text-gray-800",
  published: "bg-yellow-100 text-yellow-800",
  matching: "bg-yellow-100 text-yellow-800",
  assigned: "bg-blue-100 text-blue-800",
  in_progress: "bg-green-100 text-green-800",
  completed: "bg-gray-100 text-gray-800",
  cancelled: "bg-red-100 text-red-800",
};

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  return (
    <span className={`px-2 py-1 rounded text-xs font-medium ${STATUS_COLORS[status]}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}
