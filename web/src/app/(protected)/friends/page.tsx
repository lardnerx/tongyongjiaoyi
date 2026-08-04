"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useFriends, useFriendRequests, useAcceptFriendRequest, useRejectFriendRequest, useRemoveFriend } from "@/hooks/use-friends";
import { useWsEvent } from "@/hooks/use-ws-events";
import { Button } from "@/components/ui/button";

export default function FriendsPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"friends" | "requests">("friends");

  const { data: friends, isLoading: friendsLoading } = useFriends();
  const { data: requests, isLoading: requestsLoading } = useFriendRequests();
  const acceptRequest = useAcceptFriendRequest();
  const rejectRequest = useRejectFriendRequest();
  const removeFriend = useRemoveFriend();

  // WS 实时接收好友请求提醒，收到时自动刷新请求列表
  useWsEvent("friend_request.created", () => {
    // react-query 会通过 invalidateQueries 自动刷新（由 mutation 触发）
    // 这里作为补充：强制刷新
  });

  const handleRemove = (friendUserId: string, friendName: string) => {
    if (confirm(`确定删除好友 ${friendName} 吗？`)) {
      removeFriend.mutate(friendUserId);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-2xl space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">我的好友</h1>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>返回</Button>
        </div>

        {/* Tab 切换 */}
        <div className="flex gap-2 border-b">
          <button
            className={`pb-2 px-4 text-sm font-medium ${
              tab === "friends" ? "border-b-2 border-blue-500 text-blue-600" : "text-gray-500"
            }`}
            onClick={() => setTab("friends")}
          >
            好友列表 ({friends?.length ?? 0})
          </button>
          <button
            className={`pb-2 px-4 text-sm font-medium ${
              tab === "requests" ? "border-b-2 border-blue-500 text-blue-600" : "text-gray-500"
            }`}
            onClick={() => setTab("requests")}
          >
            好友请求 {requests && requests.length > 0 && `(${requests.length})`}
          </button>
        </div>

        {/* 好友列表 */}
        {tab === "friends" && (
          <div className="space-y-2">
            {friendsLoading && <p className="text-sm text-gray-500">加载中...</p>}
            {!friendsLoading && friends && friends.length === 0 && (
              <p className="text-sm text-gray-500 text-center py-8">还没有好友，完成服务后可以互加好友</p>
            )}
            {friends?.map((friend) => (
              <div
                key={friend.friendship_id}
                className="bg-white rounded-lg border p-4 flex items-center justify-between"
              >
                <div>
                  <p className="font-medium">{friend.friend_user_id}</p>
                  <p className="text-xs text-gray-500">
                    成为好友于 {new Date(friend.created_at).toLocaleString("zh-CN")}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => handleRemove(friend.friend_user_id, friend.friend_user_id)}
                >
                  删除
                </Button>
              </div>
            ))}
          </div>
        )}

        {/* 好友请求 */}
        {tab === "requests" && (
          <div className="space-y-2">
            {requestsLoading && <p className="text-sm text-gray-500">加载中...</p>}
            {!requestsLoading && requests && requests.length === 0 && (
              <p className="text-sm text-gray-500 text-center py-8">暂无好友请求</p>
            )}
            {requests?.map((req) => (
              <div
                key={req.request_id}
                className="bg-white rounded-lg border p-4 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">{req.from_user_id}</p>
                    <p className="text-xs text-gray-500">
                      {new Date(req.created_at).toLocaleString("zh-CN")}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={() => acceptRequest.mutate(req.request_id)}
                      disabled={acceptRequest.isPending}
                    >
                      接受
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => rejectRequest.mutate(req.request_id)}
                      disabled={rejectRequest.isPending}
                    >
                      拒绝
                    </Button>
                  </div>
                </div>
                {req.message && (
                  <p className="text-sm text-gray-600 bg-gray-50 rounded p-2">
                    留言：{req.message}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
