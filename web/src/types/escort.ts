/** 车型标签。兼容历史值（manual/auto）与新增档位。 */
export const CAR_TYPE_LABELS: Record<string, string> = {
  economy: "经济型",
  professional: "专业型",
  luxury: "豪华型",
  business: "商务型",
  manual: "手动挡",
  auto: "自动挡",
  automatic: "自动挡",
};

/** 将后端车型值转为中文展示。 */
export function formatCarType(carType: string | null | undefined): string {
  if (!carType) return "未填写";
  return CAR_TYPE_LABELS[carType] ?? carType;
}

/** 各车型暂定单价（元/小时），仅用于前端预估价格展示。 */
export const CAR_TYPE_UNIT_PRICES: Record<string, number> = {
  economy: 100,
  professional: 200,
  luxury: 500,
  business: 400,
};

/** 下单可选车型（含单价）。 */
export const CAR_TYPE_OPTIONS = [
  { value: "economy", label: "经济型", price: 100 },
  { value: "professional", label: "专业型", price: 200 },
  { value: "luxury", label: "豪华型", price: 500 },
  { value: "business", label: "商务型", price: 400 },
];

/** 取车型单价；历史车型（manual/auto）无单价返回 0。 */
export function unitPriceOf(carType: string | null | undefined): number {
  if (!carType) return 0;
  return CAR_TYPE_UNIT_PRICES[carType] ?? 0;
}

/** 预估价格 = 车型单价 × 时长；无单价的车型返回 null。 */
export function estimateAmount(
  carType: string | null | undefined,
  durationHours: number
): number | null {
  const unitPrice = unitPriceOf(carType);
  if (!unitPrice || !durationHours) return null;
  return unitPrice * durationHours;
}

/** 预估价格展示文案；无单价时返回「—」。 */
export function formatEstimate(
  carType: string | null | undefined,
  durationHours: number
): string {
  const amount = estimateAmount(carType, durationHours);
  return amount === null ? "—" : `¥${amount.toFixed(2)}`;
}

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
  origin_address?: string | null;
  duration_hours: number;
  assigned_resource_id: string | null;
  title: string | null;
  scheduled_at?: string | null;
  coach_level_pref?: string | null;
  deal_id?: string | null;
  cancel_penalty?: number;
  created_at?: string;
  check_in_at?: string | null;
  check_out_at?: string | null;
  customer_confirmed_at?: string | null;
  settled_amount?: number | null;
  /** 订单号：年月日时分 + 5 位序号。 */
  order_no?: string | null;
  /** 下单客户姓名（后端解析，缺失时回退展示 demander_id）。 */
  demander_name?: string | null;
}

/** 订单号展示：优先使用后端 order_no，历史订单回退 task_id 前 8 位。 */
export function formatOrderNo(
  orderNo: string | null | undefined,
  taskId?: string | null
): string {
  if (orderNo) return orderNo;
  return taskId ? taskId.slice(0, 8) : "—";
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
  code_url: string | null;  // 微信支付 Native 二维码 URL
}

/** 教练确认/拒绝响应。 */
export interface DealStatusInfo {
  deal_id: string;
  status: string;
  task_id: string;
}

/** 取消规则配置。 */
export interface CancelRules {
  timeout_seconds: number;
  expand_after_seconds: number;
  penalty_tiers: PenaltyTier[];
}

/** 罚分梯度档位。 */
export interface PenaltyTier {
  hours_before: number;
  penalty: number;
}
