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
  scheduled_at?: string | null;
  coach_level_pref?: string | null;
  deal_id?: string | null;
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

/** 预约单下单响应（含 Top3 候选教练）。 */
export interface ScheduledOrderResponse {
  task_id: string;
  order_type: string;
  candidates: string[];
}

/** 选教练响应。 */
export interface SelectCoachResponse {
  deal_id: string;
  task_id: string;
  resource_id: string;
  status: string;
  deposit_amount: number;
}

/** 交易信息。 */
export interface DealInfo {
  deal_id: string;
  task_id: string;
  resource_id: string;
  demander_id: string;
  supplier_id: string;
  status: string;
  final_amount: number | null;
}

/** 支付信息。 */
export interface PaymentInfo {
  payment_id: string;
  deal_id: string;
  user_id: string;
  amount: number;
  payment_type: string;
  status: string;
  trade_no: string | null;
}

/** 教练确认/拒绝响应。 */
export interface DealStatusInfo {
  deal_id: string;
  status: string;
  task_id: string;
}
