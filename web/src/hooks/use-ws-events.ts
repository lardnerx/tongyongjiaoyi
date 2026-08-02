"use client";

import { useEffect } from "react";
import { wsClient } from "@/lib/ws-client";

/**
 * 订阅 WS 事件，组件卸载时自动清理。
 * @param eventType 事件类型（如 "task.published"、"task.claimed"）
 * @param handler 数据处理函数（接收 data 字段）
 */
export function useWsEvent(
  eventType: string,
  handler: (data: Record<string, unknown>) => void
) {
  useEffect(() => {
    wsClient.on(eventType, handler);
    return () => {
      wsClient.off(eventType, handler);
    };
  }, [eventType, handler]);
}
