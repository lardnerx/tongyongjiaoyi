"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { OrderInfo, ReviewInfo } from "@/types/escort";

export function useOrders(demanderId: string | undefined) {
  return useQuery({
    queryKey: ["orders", demanderId],
    queryFn: () =>
      apiClient.get<OrderInfo[]>(`/escort/orders?demander_id=${demanderId}`),
    enabled: !!demanderId,
    staleTime: 30_000,
  });
}

export function useOrder(taskId: string | undefined) {
  return useQuery({
    queryKey: ["order", taskId],
    queryFn: () => apiClient.get<OrderInfo>(`/escort/orders/${taskId}`),
    enabled: !!taskId,
  });
}

export function useReviews(taskId: string | undefined) {
  return useQuery({
    queryKey: ["reviews", taskId],
    queryFn: () => apiClient.get<ReviewInfo[]>(`/escort/orders/${taskId}/reviews`),
    enabled: !!taskId,
  });
}

export function useInvalidateOrder(taskId: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["order", taskId] });
    qc.invalidateQueries({ queryKey: ["reviews", taskId] });
  };
}
