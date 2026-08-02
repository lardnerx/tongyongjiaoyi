"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { CancelRules } from "@/types/escort";

/** 获取取消规则（实时单超时、预约单罚分梯度）。 */
export function useCancelRules() {
  const query = useQuery({
    queryKey: ["cancel-rules"],
    queryFn: () => apiClient.get<CancelRules>("/escort/cancel-rules"),
    staleTime: 5 * 60 * 1000, // 5 分钟缓存
  });

  const calculatePenalty = (
    scheduledAt: Date | string | null,
    now: Date = new Date(),
  ): number => {
    if (!scheduledAt || !query.data) return 0;
    const scheduled = typeof scheduledAt === "string" ? new Date(scheduledAt) : scheduledAt;
    const hoursBefore = (scheduled.getTime() - now.getTime()) / 3600000;
    const tiers = query.data.penalty_tiers ?? [];
    for (const tier of tiers) {
      if (hoursBefore >= tier.hours_before) {
        return tier.penalty;
      }
    }
    return 0;
  };

  return {
    ...query,
    calculatePenalty,
  };
}
