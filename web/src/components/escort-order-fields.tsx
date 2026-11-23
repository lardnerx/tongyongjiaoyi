"use client";

import { cn } from "@/lib/utils";
import {
  CAR_TYPE_OPTIONS,
  estimateAmount,
  unitPriceOf,
} from "@/types/escort";

/** 服务时长可选的上下限（小时）。 */
export const MIN_DURATION_HOURS = 1;
export const MAX_DURATION_HOURS = 8;

interface EscortOrderFieldsProps {
  carType: string;
  onCarTypeChange: (value: string) => void;
  duration: number;
  onDurationChange: (value: number) => void;
}

/**
 * 陪驾下单的共性字段：车型（含单价）、服务时长（可增减）、预估价格。
 * 实时叫车与预约叫车共用，保证两页除预约时间外保持一致。
 */
export function EscortOrderFields({
  carType,
  onCarTypeChange,
  duration,
  onDurationChange,
}: EscortOrderFieldsProps) {
  const clamp = (value: number) =>
    Math.min(MAX_DURATION_HOURS, Math.max(MIN_DURATION_HOURS, value));

  const stepClass =
    "flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-gray-300 bg-white text-lg text-gray-700 disabled:cursor-not-allowed disabled:opacity-40";

  const amount = estimateAmount(carType, duration);
  const unitPrice = unitPriceOf(carType);

  return (
    <>
      <div className="space-y-2">
        <label className="text-sm font-medium">车型</label>
        <select
          aria-label="车型"
          className="w-full rounded-md border border-gray-300 bg-white p-2"
          value={carType}
          onChange={(e) => onCarTypeChange(e.target.value)}
        >
          {CAR_TYPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label} · ¥{option.price}/小时
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">服务时长（小时）</label>
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="减少服务时长"
            className={stepClass}
            onClick={() => onDurationChange(clamp(duration - 1))}
            disabled={duration <= MIN_DURATION_HOURS}
          >
            −
          </button>
          <input
            aria-label="服务时长"
            type="number"
            min={MIN_DURATION_HOURS}
            max={MAX_DURATION_HOURS}
            value={duration}
            onChange={(e) => onDurationChange(clamp(parseInt(e.target.value, 10) || MIN_DURATION_HOURS))}
            className="h-10 min-w-0 flex-1 rounded-md border border-gray-300 bg-white text-center text-sm"
          />
          <button
            type="button"
            aria-label="增加服务时长"
            className={stepClass}
            onClick={() => onDurationChange(clamp(duration + 1))}
            disabled={duration >= MAX_DURATION_HOURS}
          >
            +
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between rounded-md bg-gray-100 px-3 py-2">
        <span className="text-sm text-gray-500">预估价格</span>
        <span aria-label="预估价格" className={cn("text-lg font-semibold text-gray-900")}>
          {amount === null ? "—" : `¥${amount.toFixed(2)}`}
        </span>
      </div>
      {unitPrice > 0 && (
        <p className="text-xs text-gray-400">
          {unitPrice} 元/小时 × {duration} 小时，实际以订单结算为准
        </p>
      )}
    </>
  );
}
