"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { FriendRequest, Friendship } from "@/types/friend";

export function useFriendRequests() {
  return useQuery({
    queryKey: ["friend-requests"],
    queryFn: () => apiClient.get<FriendRequest[]>("/friends/requests"),
  });
}

export function useFriends() {
  return useQuery({
    queryKey: ["friends"],
    queryFn: () => apiClient.get<Friendship[]>("/friends"),
  });
}

export function useSendFriendRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { toUserId: string; message?: string }) =>
      apiClient.post<FriendRequest>("/friends/requests", {
        to_user_id: params.toUserId,
        message: params.message ?? "",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["friend-requests"] });
    },
  });
}

export function useAcceptFriendRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) =>
      apiClient.post<FriendRequest>(`/friends/requests/${requestId}/accept`, null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["friend-requests"] });
      qc.invalidateQueries({ queryKey: ["friends"] });
    },
  });
}

export function useRejectFriendRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) =>
      apiClient.post<FriendRequest>(`/friends/requests/${requestId}/reject`, null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["friend-requests"] });
    },
  });
}

export function useRemoveFriend() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (friendUserId: string) =>
      apiClient.delete(`/friends/${friendUserId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["friends"] });
    },
  });
}
