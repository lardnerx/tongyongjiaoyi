/** 订单状态（后端 TaskStatus 小写字符串）。 */
export type OrderStatus =
  | "draft"
  | "published"
  | "matching"
  | "assigned"
  | "in_progress"
  | "completed"
  | "cancelled";

/** 订单信息。 */
export interface OrderInfo {
  task_id: string;
  order_type: string;
  status: OrderStatus;
  demander_id: string;
  car_type: string;
  duration_hours: number;
  assigned_resource_id: string | null;
  title: string | null;
}

/** 评价信息。 */
export interface ReviewInfo {
  review_id: string;
  task_id: string;
  reviewer_id: string;
  reviewer_role: "STUDENT" | "COACH";
  evaluatee_id: string;
  ratings: Record<string, number>;
  comment: string;
  created_at: string;
}

/** WS 推送消息。 */
export interface WSMessage {
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}
