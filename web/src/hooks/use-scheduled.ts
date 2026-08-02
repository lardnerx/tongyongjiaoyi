"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type {
  ScheduledOrderResponse,
  SelectCoachResponse,
  DealInfo,
  PaymentInfo,
  DealStatusInfo,
} from "@/types/escort";

/** 创建预约单。 */
export function useCreateScheduledOrder() {
  return useMutation({
    mutationFn: (params: {
      demander_id: string;
      origin_lat: number;
      origin_lng: number;
      car_type: string;
      duration_hours: number;
      scheduled_at: string;
      coach_level_pref: string;
    }) =>
      apiClient.post<ScheduledOrderResponse>("/escort/orders", {
        demander_id: params.demander_id,
        domain_tag: "escort",
        origin_lat: params.origin_lat,
        origin_lng: params.origin_lng,
        car_type: params.car_type,
        required_skills: ["coach_license"],
        duration_hours: params.duration_hours,
        order_type: "SCHEDULED",
        scheduled_at: params.scheduled_at,
        coach_level_pref: params.coach_level_pref,
      }),
  });
}

/** 学员选教练。 */
export function useSelectCoach() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { taskId: string; resourceId: string }) =>
      apiClient.post<SelectCoachResponse>(
        `/escort/orders/${params.taskId}/select-coach`,
        { resource_id: params.resourceId }
      ),
    onSuccess: (_, variables) => {
      qc.invalidateQueries({ queryKey: ["order", variables.taskId] });
    },
  });
}

/** Mock 支付定金。 */
export function useMockPay() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { dealId: string; paymentType?: string }) =>
      apiClient.post<PaymentInfo>("/escort/payments/mock-pay", {
        deal_id: params.dealId,
        payment_type: params.paymentType || "deposit",
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["payment", data.deal_id] });
      qc.invalidateQueries({ queryKey: ["deal", data.deal_id] });
    },
  });
}

/** 教练确认预约单。 */
export function useConfirmDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { dealId: string; coachId: string }) =>
      apiClient.post<DealStatusInfo>(
        `/escort/deals/${params.dealId}/confirm`,
        { coach_id: params.coachId }
      ),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["deal", data.deal_id] });
      qc.invalidateQueries({ queryKey: ["order", data.task_id] });
    },
  });
}

/** 教练拒绝预约单。 */
export function useRejectDeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { dealId: string; coachId: string; reason?: string }) =>
      apiClient.post<DealStatusInfo>(
        `/escort/deals/${params.dealId}/reject`,
        { coach_id: params.coachId, reason: params.reason || "" }
      ),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["deal", data.deal_id] });
      qc.invalidateQueries({ queryKey: ["order", data.task_id] });
    },
  });
}

/** 查询 deal 信息。 */
export function useDeal(dealId: string | undefined) {
  return useQuery({
    queryKey: ["deal", dealId],
    queryFn: () => apiClient.get<DealInfo>(`/deals/${dealId}`),
    enabled: !!dealId,
  });
}

/** 查询支付状态。 */
export function usePayment(dealId: string | undefined) {
  return useQuery({
    queryKey: ["payment", dealId],
    queryFn: () => apiClient.get<PaymentInfo>(`/escort/payments/${dealId}`),
    enabled: !!dealId,
    retry: false,
  });
}
