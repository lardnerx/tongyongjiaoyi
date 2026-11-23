"use client";

import { useParams, useRouter } from "next/navigation";
import { useOrder } from "@/hooks/use-orders";
import { Button } from "@/components/ui/button";
import {
  estimateAmount,
  formatCarType,
  unitPriceOf,
} from "@/types/escort";

/** 时长展示：X 小时 Y 分钟。 */
function formatDuration(hours: number): string {
  const totalMinutes = Math.max(0, Math.round(hours * 60));
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m} 分钟`;
  return `${h} 小时${m > 0 ? ` ${m} 分钟` : ""}`;
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN");
}

/** 结算页：结束订单后展示服务时长与应付金额。 */
export default function CoachSettlementPage() {
  const params = useParams();
  const router = useRouter();
  const taskId = params.id as string;
  const { data: order, isLoading } = useOrder(taskId);

  if (isLoading) return <div className="p-4">加载中...</div>;
  if (!order) return <div className="p-4">订单不存在</div>;

  const startMs = order.check_in_at ? Date.parse(order.check_in_at) : null;
  const endMs = order.check_out_at ? Date.parse(order.check_out_at) : null;
  const actualHours =
    startMs !== null && endMs !== null && !Number.isNaN(startMs) && !Number.isNaN(endMs)
      ? Math.max(0, (endMs - startMs) / 3600000)
      : null;
  const unitPrice = unitPriceOf(order.car_type);
  const amount = estimateAmount(order.car_type, order.duration_hours);

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">结算单</h1>
          <Button variant="ghost" onClick={() => router.push("/escort/coach/orders")}>
            返回订单
          </Button>
        </div>

        {/* 金额卡片 */}
        <div className="rounded-xl bg-gray-900 p-8 text-center text-white">
          <p className="text-sm text-gray-400">本单金额</p>
          <p className="mt-2 text-4xl font-bold">
            {amount === null ? "—" : `¥${amount.toFixed(2)}`}
          </p>
          <p className="mt-3 text-xs text-gray-400">
            {unitPrice > 0
              ? `¥${unitPrice}/小时 × ${order.duration_hours} 小时`
              : "该车型暂无单价"}
          </p>
        </div>

        {/* 结算明细 */}
        <div className="space-y-2 rounded-lg border bg-white p-4">
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">订单编号</span>
            <span className="font-mono">{order.task_id.slice(0, 8)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">车型</span>
            <span>{formatCarType(order.car_type)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">开始时间</span>
            <span>{formatTime(order.check_in_at)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">结束时间</span>
            <span>{formatTime(order.check_out_at)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">实际服务时长</span>
            <span>{actualHours === null ? "—" : formatDuration(actualHours)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">计费时长</span>
            <span>{order.duration_hours} 小时</span>
          </div>
          <div className="flex justify-between border-t pt-2 text-sm font-medium">
            <span>应付金额</span>
            <span>{amount === null ? "—" : `¥${amount.toFixed(2)}`}</span>
          </div>
        </div>

        <p className="text-xs text-gray-400">
          实际金额以平台结算为准；如服务时长与预定时长差异较大，请联系平台客服处理。
        </p>

        <div className="flex gap-2">
          <Button
            variant="outline"
            className="flex-1"
            onClick={() => router.push(`/escort/coach/orders/${taskId}`)}
          >
            订单详情
          </Button>
          <Button
            className="flex-1"
            onClick={() => router.push("/escort/coach/orders")}
          >
            我的订单
          </Button>
        </div>
      </div>
    </div>
  );
}
