"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api-client";
import type { PaymentInfo } from "@/types/escort";

export type PaymentPollResult =
  | { status: "pending" }
  | { status: "paid" }
  | { status: "failed"; error: string }
  | { status: "timeout" };

/**
 * 支付状态轮询 hook。
 *
 * @param dealId 交易 ID
 * @param enabled 是否启用轮询
 * @param interval 轮询间隔（ms），默认 2000
 * @param timeout 超时时间（ms），默认 30000
 */
export function usePaymentPoll(
  dealId: string | undefined,
  enabled: boolean,
  interval = 2000,
  timeout = 30000,
) {
  const [result, setResult] = useState<PaymentPollResult>({ status: "pending" });
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const elapsedRef = useRef(0);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!enabled || !dealId) {
      setResult({ status: "pending" });
      return;
    }

    elapsedRef.current = 0;

    const poll = async () => {
      try {
        const payment = await apiClient.get<PaymentInfo>(`/escort/payments/${dealId}`);
        if (payment.status === "paid") {
          setResult({ status: "paid" });
          stop();
        } else if (payment.status === "failed") {
          setResult({ status: "failed", error: "支付失败" });
          stop();
        }
        // pending 状态继续轮询
      } catch {
        // 网络错误继续轮询
      }
    };

    // 立即执行一次
    poll();

    timerRef.current = setInterval(poll, interval);
    timeoutRef.current = setTimeout(() => {
      setResult({ status: "timeout" });
      stop();
    }, timeout);

    return stop;
  }, [dealId, enabled, interval, timeout, stop]);

  return result;
}