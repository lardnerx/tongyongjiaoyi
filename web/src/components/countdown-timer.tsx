"use client";

import { useEffect, useState } from "react";

interface CountdownTimerProps {
  /** 下单时间（ISO 字符串或 Date）。 */
  createdAt: string | Date;
  /** 超时秒数。 */
  timeoutSeconds: number;
  /** 超时回调（可选）。 */
  onTimeout?: () => void;
}

export function CountdownTimer({ createdAt, timeoutSeconds, onTimeout }: CountdownTimerProps) {
  const created = typeof createdAt === "string" ? new Date(createdAt) : createdAt;
  const [remaining, setRemaining] = useState<number>(
    Math.max(0, timeoutSeconds - (Date.now() - created.getTime()) / 1000),
  );

  useEffect(() => {
    const timer = setInterval(() => {
      const r = timeoutSeconds - (Date.now() - created.getTime()) / 1000;
      setRemaining(Math.max(0, r));
      if (r <= 0 && onTimeout) onTimeout();
    }, 1000);
    return () => clearInterval(timer);
  }, [created, timeoutSeconds, onTimeout]);

  if (remaining <= 0) {
    return <span className="text-red-500 text-sm">已超时</span>;
  }
  return (
    <span className="text-orange-500 text-sm">
      剩余 {Math.ceil(remaining)} 秒
    </span>
  );
}
