import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import {
  useFriendRequests,
  useFriends,
  useSendFriendRequest,
  useAcceptFriendRequest,
  useRejectFriendRequest,
  useRemoveFriend,
} from "@/hooks/use-friends";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

describe("use-friends hooks", () => {
  beforeEach(() => {
    (apiClient.get as any).mockReset();
    (apiClient.post as any).mockReset();
    (apiClient.delete as any).mockReset();
  });

  it("useFriendRequests 获取好友请求列表", async () => {
    (apiClient.get as any).mockResolvedValue([
      { request_id: "freq_1", from_user_id: "u1", to_user_id: "me", status: "pending" },
    ]);
    const { result } = renderHook(() => useFriendRequests(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(1);
  });

  it("useFriends 获取好友列表", async () => {
    (apiClient.get as any).mockResolvedValue([
      { friendship_id: "f1", friend_user_id: "u1", created_at: "2026-01-01" },
    ]);
    const { result } = renderHook(() => useFriends(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toHaveLength(1);
  });

  it("useSendFriendRequest 调用 POST", async () => {
    (apiClient.post as any).mockResolvedValue({ request_id: "freq_1" });
    const { result } = renderHook(() => useSendFriendRequest(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ toUserId: "u1", message: "加个好友" });
    expect(apiClient.post).toHaveBeenCalledWith("/friends/requests", {
      to_user_id: "u1",
      message: "加个好友",
    });
  });

  it("useAcceptFriendRequest 调用 POST accept", async () => {
    (apiClient.post as any).mockResolvedValue({ status: "accepted" });
    const { result } = renderHook(() => useAcceptFriendRequest(), { wrapper: createWrapper() });
    await result.current.mutateAsync("freq_1");
    expect(apiClient.post).toHaveBeenCalledWith("/friends/requests/freq_1/accept", null);
  });

  it("useRejectFriendRequest 调用 POST reject", async () => {
    (apiClient.post as any).mockResolvedValue({ status: "rejected" });
    const { result } = renderHook(() => useRejectFriendRequest(), { wrapper: createWrapper() });
    await result.current.mutateAsync("freq_1");
    expect(apiClient.post).toHaveBeenCalledWith("/friends/requests/freq_1/reject", null);
  });

  it("useRemoveFriend 调用 DELETE", async () => {
    (apiClient.delete as any).mockResolvedValue(undefined);
    const { result } = renderHook(() => useRemoveFriend(), { wrapper: createWrapper() });
    await result.current.mutateAsync("u1");
    expect(apiClient.delete).toHaveBeenCalledWith("/friends/u1");
  });
});
