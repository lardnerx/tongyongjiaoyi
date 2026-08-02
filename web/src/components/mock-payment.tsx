"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useMockPay, usePayment } from "@/hooks/use-scheduled";

interface MockPaymentProps {
  dealId: string;
  onPaid: () => void;
}

export function MockPayment({ dealId, onPaid }: MockPaymentProps) {
  const mockPay = useMockPay();
  const { data: payment, isLoading } = usePayment(dealId);
  const [error, setError] = useState("");

  // 已支付
  if (payment?.status === "paid") {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
        <p className="text-green-800">定金已支付</p>
        <p className="text-sm text-gray-500 mt-1">等待教练确认...</p>
      </div>
    );
  }

  const handlePay = async () => {
    setError("");
    mockPay.mutate(
      { dealId },
      {
        onSuccess: () => onPaid(),
        onError: (e: any) => setError(e.message || "支付失败"),
      }
    );
  };

  return (
    <div className="bg-white rounded-lg border p-4 space-y-3">
      <h3 className="font-medium">支付定金</h3>
      <p className="text-sm text-gray-500">
        Mock 支付（开发环境模拟，点击即支付成功）
      </p>
      {error && <p className="text-sm text-red-500">{error}</p>}
      <Button className="w-full" onClick={handlePay} disabled={mockPay.isPending || isLoading}>
        {mockPay.isPending ? "支付中..." : "Mock 支付定金"}
      </Button>
    </div>
  );
}
