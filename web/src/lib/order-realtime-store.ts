import { create } from "zustand";
import type { OrderStatus } from "@/types/escort";

interface OrderRealtimeState {
  /** 被抢的订单 ID 集合（教练端用于从大厅移除） */
  claimedOrderIds: Set<string>;
  /** 订单状态实时更新（task_id → status） */
  orderStatusUpdates: Record<string, OrderStatus>;
  /** 标记订单被抢 */
  markClaimed: (taskId: string) => void;
  /** 更新订单状态 */
  updateOrderStatus: (taskId: string, status: OrderStatus) => void;
  /** 重置（切换页面时调用） */
  reset: () => void;
}

export const useOrderRealtimeStore = create<OrderRealtimeState>((set) => ({
  claimedOrderIds: new Set<string>(),
  orderStatusUpdates: {},
  markClaimed: (taskId) =>
    set((state) => {
      const claimed = new Set(state.claimedOrderIds);
      claimed.add(taskId);
      return { claimedOrderIds: claimed };
    }),
  updateOrderStatus: (taskId, status) =>
    set((state) => ({
      orderStatusUpdates: { ...state.orderStatusUpdates, [taskId]: status },
    })),
  reset: () => set({ claimedOrderIds: new Set(), orderStatusUpdates: {} }),
}));
