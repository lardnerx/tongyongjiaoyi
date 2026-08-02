import { describe, it, expect, beforeEach } from "vitest";
import { useOrderRealtimeStore } from "@/lib/order-realtime-store";

describe("order-realtime-store", () => {
  beforeEach(() => {
    useOrderRealtimeStore.getState().reset();
  });

  it("markClaimed adds to claimed set", () => {
    useOrderRealtimeStore.getState().markClaimed("task_1");
    expect(useOrderRealtimeStore.getState().claimedOrderIds.has("task_1")).toBe(true);
  });

  it("updateOrderStatus sets status", () => {
    useOrderRealtimeStore.getState().updateOrderStatus("task_1", "assigned");
    expect(useOrderRealtimeStore.getState().orderStatusUpdates["task_1"]).toBe("assigned");
  });

  it("reset clears all", () => {
    useOrderRealtimeStore.getState().markClaimed("task_1");
    useOrderRealtimeStore.getState().updateOrderStatus("task_1", "completed");
    useOrderRealtimeStore.getState().reset();
    expect(useOrderRealtimeStore.getState().claimedOrderIds.size).toBe(0);
    expect(Object.keys(useOrderRealtimeStore.getState().orderStatusUpdates)).toHaveLength(0);
  });
});
