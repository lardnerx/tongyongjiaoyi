"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { useOrder } from "@/hooks/use-orders";
import { useDeal, useCreatePayment, usePayment } from "@/hooks/use-scheduled";
import { usePaymentPoll } from "@/hooks/use-payment-poll";
import { apiClient } from "@/lib/api-client";
import { PaymentOrderSummary } from "./payment-order-summary";
import { PaymentMethodSelector, type PaymentMethod } from "./payment-method-selector";
import { MockQrDisplay } from "./mock-qr-display";
import { PaymentProcessing, PaymentSuccess, PaymentFailed, PaymentTimeout } from "./payment-status-card";

/** 支付超时时间（秒）。生产环境建议 900（15 分钟），测试时可缩短。 */
const PAYMENT_TIMEOUT_SECONDS = 900;

type PageState =
  | { type: "LOADING" }
  | { type: "READY"; paymentMethod: PaymentMethod; remainingSeconds: number }
  | { type: "PROCESSING" }
  | { type: "QR_SCANNING"; paymentMethod: PaymentMethod; dealId: string }  // 微信支付：等待扫码
  | { type: "SUCCESS"; countdown: number }
  | { type: "FAILED"; error: string }
  | { type: "TIMEOUT" };

interface Props {
  taskId: string;
}

export function formatRemaining(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export function PaymentPage({ taskId }: Props) {
  const router = useRouter();
  const { user } = useAuthStore();
  const { data: order, isLoading: orderLoading } = useOrder(taskId);
  const dealId = order?.deal_id ?? undefined;
  const { data: deal } = useDeal(dealId);
  const { data: payment } = usePayment(dealId);
  const createPayment = useCreatePayment();

  const [state, setState] = useState<PageState>({ type: "LOADING" });
  const [countdown, setCountdown] = useState(3);
  const timeoutTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 微信支付轮询：在 QR_SCANNING 状态下轮询支付状态
  const isScanning = state.type === "QR_SCANNING";
  const pollResult = usePaymentPoll(
    isScanning ? state.dealId : undefined,
    isScanning,
    2000,  // 2 秒轮询一次
    900000, // 15 分钟超时
  );

  // 轮询结果处理
  useEffect(() => {
    if (pollResult.status === "paid") {
      setState({ type: "SUCCESS", countdown: 3 });
    } else if (pollResult.status === "failed") {
      setState({ type: "FAILED", error: pollResult.error });
    } else if (pollResult.status === "timeout") {
      setState({ type: "TIMEOUT" });
    }
  }, [pollResult.status]);

  // 定金 = 总价的 30%
  const depositAmount = deal?.final_amount ? Math.round(deal.final_amount * 0.3 * 100) / 100 : 0;

  // --- 清理超时定时器 ---
  const clearTimeoutTimer = useCallback(() => {
    if (timeoutTimerRef.current !== null) {
      clearInterval(timeoutTimerRef.current);
      timeoutTimerRef.current = null;
    }
  }, []);

  // --- 状态机 ---

  // LOADING → READY / REDIRECT
  useEffect(() => {
    if (orderLoading) return;
    if (!order) {
      router.back();
      return;
    }
    if (payment?.status === "paid") {
      router.push(`/escort/student/orders/${taskId}`);
      return;
    }
    setState({ type: "READY", paymentMethod: "wechat", remainingSeconds: PAYMENT_TIMEOUT_SECONDS });
  }, [orderLoading, order, payment, router, taskId]);

  // READY → 超时倒计时
  useEffect(() => {
    if (state.type !== "READY") {
      clearTimeoutTimer();
      return;
    }
    // 每秒递减剩余时间
    timeoutTimerRef.current = setInterval(() => {
      setState((prev) => {
        if (prev.type !== "READY") return prev;
        const next = prev.remainingSeconds - 1;
        if (next <= 0) {
          return { type: "TIMEOUT" };
        }
        return { ...prev, remainingSeconds: next };
      });
    }, 1000);
    return clearTimeoutTimer;
  }, [state.type === "READY"]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- 事件处理 ---

  const handleTimeout = useCallback(async () => {
    if (!dealId) return;
    clearTimeoutTimer();
    try {
      await apiClient.post(`/escort/payments/${dealId}/timeout`, {});
    } catch {
      // 超时取消即使 API 失败，前端也展示超时状态
    }
  }, [dealId, clearTimeoutTimer]);

  const handlePay = useCallback(async () => {
    if (!dealId) return;
    clearTimeoutTimer();
    setState({ type: "PROCESSING" });

    try {
      const result = await createPayment.mutateAsync({ dealId });
      if (result.code_url) {
        // 微信支付模式：进入扫码等待状态
        setState({ type: "QR_SCANNING", paymentMethod: state.type === "READY" ? state.paymentMethod : "wechat", dealId });
      } else {
        // Mock 模式：立即成功
        setState({ type: "SUCCESS", countdown: 3 });
      }
    } catch (err: any) {
      setState({ type: "FAILED", error: err?.message || "支付失败，请重试" });
    }
  }, [dealId, createPayment, state.type === "READY" ? (state as any).paymentMethod : "wechat"]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRetry = useCallback(() => {
    setState({ type: "READY", paymentMethod: "wechat", remainingSeconds: PAYMENT_TIMEOUT_SECONDS });
  }, []);

  const handleTimeoutBack = useCallback(() => {
    router.push(`/escort/student/orders/${taskId}`);
  }, [router, taskId]);

  // 当状态变为 TIMEOUT 时调用取消 API（与 setState 分离，避免副作用在 updater 中）
  useEffect(() => {
    if (state.type === "TIMEOUT") {
      handleTimeout();
    }
  }, [state.type, handleTimeout]);

  // SUCCESS → 倒计时 → 跳转
  useEffect(() => {
    if (state.type !== "SUCCESS") return;
    if (countdown <= 0) {
      router.push(`/escort/student/orders/${taskId}`);
      return;
    }
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [state.type, countdown, router, taskId]);

  // --- 组件卸载时清理定时器 ---
  useEffect(() => {
    return clearTimeoutTimer;
  }, [clearTimeoutTimer]);

  // --- 渲染 ---

  // LOADING
  if (state.type === "LOADING") {
    return (
      <div className="min-h-screen bg-gray-50 p-4 flex items-center justify-center">
        <div className="text-gray-500">加载中...</div>
      </div>
    );
  }

  // TIMEOUT
  if (state.type === "TIMEOUT") {
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="mx-auto max-w-md pt-16">
          <PaymentTimeout onBack={handleTimeoutBack} />
        </div>
      </div>
    );
  }

  // QR_SCANNING — 微信支付扫码等待
  if (state.type === "QR_SCANNING") {
    const paymentData = createPayment.data;
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="mx-auto max-w-md space-y-4 pt-8">
          <h1 className="text-lg font-bold text-center">微信扫码支付</h1>
          <div className="rounded-lg border bg-white p-4 space-y-3">
            <h3 className="font-medium text-sm text-gray-500">扫码支付</h3>
            <div className="flex flex-col items-center gap-3">
              {paymentData?.code_url ? (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(paymentData.code_url)}`}
                    alt="微信支付二维码"
                    className="w-48 h-48"
                  />
                  <p className="text-sm text-gray-500">请使用微信扫码支付</p>
                  <p className="text-xs text-gray-400">
                    支付金额: ¥{depositAmount.toFixed(2)}
                  </p>
                  <div className="flex items-center gap-2 text-sm text-orange-500">
                    <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <path d="M12 6v6l4 4" />
                    </svg>
                    <span>等待支付中...</span>
                  </div>
                </>
              ) : (
                <div className="text-gray-500">生成二维码中...</div>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setState({ type: "READY", paymentMethod: "wechat", remainingSeconds: PAYMENT_TIMEOUT_SECONDS })}
            className="w-full rounded-lg border border-gray-300 py-3 text-base font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            取消支付
          </button>
        </div>
      </div>
    );
  }

  // READY
  if (state.type === "READY") {
    if (!order) return null;
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="mx-auto max-w-md space-y-4">
          {/* 顶部导航 */}
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => router.back()} className="text-gray-500 hover:text-gray-700">
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
            </button>
            <h1 className="text-lg font-bold">支付定金</h1>
            {/* 超时倒计时 */}
            <div className="ml-auto flex items-center gap-1 text-sm text-orange-500">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 6v6l4 4" />
              </svg>
              <span>{formatRemaining(state.remainingSeconds)}</span>
            </div>
          </div>

          {/* 订单信息 */}
          <PaymentOrderSummary order={order} deal={deal} depositAmount={depositAmount} />

          {/* 支付方式选择 */}
          <PaymentMethodSelector
            value={state.paymentMethod}
            onChange={(m) => setState({ type: "READY", paymentMethod: m, remainingSeconds: state.remainingSeconds })}
          />

          {/* Mock 二维码（开发模式） */}
          <MockQrDisplay method={state.paymentMethod} amount={depositAmount} />

          {/* 确认支付按钮 */}
          <button
            type="button"
            onClick={handlePay}
            disabled={createPayment.isPending}
            className="w-full rounded-lg bg-blue-500 py-3 text-base font-medium text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {createPayment.isPending ? "支付中..." : `确认支付  ¥${depositAmount.toFixed(2)}`}
          </button>
        </div>
      </div>
    );
  }

  // PROCESSING
  if (state.type === "PROCESSING") {
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="mx-auto max-w-md pt-16">
          <PaymentProcessing />
        </div>
      </div>
    );
  }

  // SUCCESS
  if (state.type === "SUCCESS") {
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="mx-auto max-w-md pt-16">
          <PaymentSuccess amount={depositAmount} countdown={countdown} />
        </div>
      </div>
    );
  }

  // FAILED
  if (state.type === "FAILED") {
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="mx-auto max-w-md pt-16">
          <PaymentFailed error={state.error} onRetry={handleRetry} />
        </div>
      </div>
    );
  }

  return null;
}