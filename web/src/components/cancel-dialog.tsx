"use client";

import { Button } from "@/components/ui/button";

interface CancelDialogProps {
  open: boolean;
  orderType: "REALTIME" | "SCHEDULED";
  penalty: number;
  onConfirm: () => void;
  onClose: () => void;
}

export function CancelDialog({
  open,
  orderType,
  penalty,
  onConfirm,
  onClose,
}: CancelDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-sm w-full mx-4 space-y-4">
        <h3 className="text-lg font-medium">取消订单</h3>
        <p className="text-sm text-gray-600">
          {orderType === "REALTIME"
            ? "取消后将通知在线司机。"
            : `取消将扣除信用分 ${penalty} 分，已支付定金将原路退回。`}
        </p>
        {orderType === "SCHEDULED" && penalty > 0 && (
          <p className="text-xs text-orange-600">
            提示：越临近预约时间取消，扣分越多。
          </p>
        )}
        <div className="flex gap-2 justify-end">
          <Button variant="ghost" onClick={onClose}>
            再想想
          </Button>
          <Button variant="destructive" onClick={onConfirm}>
            确认取消
          </Button>
        </div>
      </div>
    </div>
  );
}
