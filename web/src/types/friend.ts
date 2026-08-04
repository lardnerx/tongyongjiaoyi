/** 好友请求。 */
export interface FriendRequest {
  request_id: string;
  from_user_id: string;
  to_user_id: string;
  status: "pending" | "accepted" | "rejected";
  message: string;
  created_at: string;
  responded_at: string | null;
}

/** 好友关系。 */
export interface Friendship {
  friendship_id: string;
  friend_user_id: string;
  created_at: string;
}
