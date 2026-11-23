"use client";

import type { OrderInfo, DealInfo } from "@/types/escort";

interface Props {
  order: OrderInfo;
  deal: DealInfo | undefined;
  depositAmount: number;
}

export function PaymentOrderSummary({ order, deal, depositAmount }: Props) {
  return (
    <div className="rounded-lg border bg-white p-4 space-y-3">
      <h3 className="font-medium text-sm text-gray-500">订单信息</h3>
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-500">类型</span>
          <span>{order.order_type === "SCHEDULED" ? "预约单" : "实时单"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">车型</span>
          <span>{order.car_type === "manual" ? "手动挡" : "自动挡"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">时长</span>
          <span>{order.duration_hours} 小时</span>
        </div>
        {order.assigned_resource_id && (
          <div className="flex justify-between">
            <span className="text-gray-500">司机</span>
            <span className="text-blue-600">{order.assigned_resource_id}</span>
          </div>
        )}
        {order.scheduled_at && (
          <div className="flex justify-between">
            <span className="text-gray-500">预约时间</span>
            <span>{new Date(order.scheduled_at).toLocaleString("zh-CN")}</span>
          </div>
        )}
        {deal?.final_amount && (
          <div className="flex justify-between">
            <span className="text-gray-500">总价</span>
            <span>¥{deal.final_amount.toFixed(2)}</span>
          </div>
        )}
      </div>

      <hr className="border-gray-100" />

      <div className="flex justify-between items-center">
        <span className="text-sm text-gray-500">应付定金</span>
        <span className="text-xl font-bold text-red-500">¥{depositAmount.toFixed(2)}</span>
      </div>
    </div>
  );
}