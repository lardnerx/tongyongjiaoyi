"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AmapPicker } from "@/components/amap-picker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/lib/auth-store";
import { useCreateScheduledOrder, useSelectCoach } from "@/hooks/use-scheduled";
import type { ScheduledOrderResponse, SelectCoachResponse } from "@/types/escort";

export default function BookScheduledPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const createOrder = useCreateScheduledOrder();
  const selectCoach = useSelectCoach();

  const [location, setLocation] = useState<{ lat: number; lng: number; address: string } | null>(null);
  const [carType, setCarType] = useState("manual");
  const [duration, setDuration] = useState(2);
  const [scheduledAt, setScheduledAt] = useState("");
  const [coachLevelPref, setCoachLevelPref] = useState("ANY");
  const [scheduledResp, setScheduledResp] = useState<ScheduledOrderResponse | null>(null);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!location || !scheduledAt) {
      setError("请选择上车地点和预约时间");
      return;
    }
    setError("");
    createOrder.mutate(
      {
        demander_id: user?.user_id || "",
        origin_lat: location.lat,
        origin_lng: location.lng,
        car_type: carType,
        duration_hours: duration,
        scheduled_at: scheduledAt,
        coach_level_pref: coachLevelPref,
      },
      {
        onSuccess: (data) => setScheduledResp(data),
        onError: (e: any) => setError(e.message || "下单失败"),
      }
    );
  };

  const handleSelectCoach = async (resourceId: string) => {
    if (!scheduledResp) return;
    selectCoach.mutate(
      { taskId: scheduledResp.task_id, resourceId },
      {
        onSuccess: (data: SelectCoachResponse) => {
          router.push(`/escort/student/orders/${data.task_id}`);
        },
        onError: (e: any) => setError(e.message || "选教练失败"),
      }
    );
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <h1 className="text-2xl font-bold">预约叫车</h1>

        {!scheduledResp && (
          <>
            <div className="space-y-2">
              <label className="text-sm font-medium">选择上车地点</label>
              <AmapPicker onChange={setLocation} />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">预约时间</label>
              <Input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">车型</label>
              <select
                className="w-full rounded-md border border-gray-300 p-2"
                value={carType}
                onChange={(e) => setCarType(e.target.value)}
              >
                <option value="manual">手动挡</option>
                <option value="auto">自动挡</option>
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">教练等级偏好</label>
              <select
                className="w-full rounded-md border border-gray-300 p-2"
                value={coachLevelPref}
                onChange={(e) => setCoachLevelPref(e.target.value)}
              >
                <option value="ANY">不限</option>
                <option value="A">A级</option>
                <option value="B">B级</option>
                <option value="C">C级</option>
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">服务时长（小时）</label>
              <Input
                type="number"
                min={1}
                max={8}
                value={duration}
                onChange={(e) => setDuration(parseInt(e.target.value) || 1)}
              />
            </div>

            {error && <p className="text-sm text-red-500">{error}</p>}

            <Button
              className="w-full"
              onClick={handleSubmit}
              disabled={createOrder.isPending}
            >
              {createOrder.isPending ? "提交中..." : "查找教练"}
            </Button>

            <Button variant="ghost" className="w-full" onClick={() => router.push("/dashboard")}>
              返回
            </Button>
          </>
        )}

        {scheduledResp && (
          <div className="space-y-4">
            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-medium mb-3">推荐教练（Top3）</h2>
              <p className="text-sm text-gray-500 mb-3">
                请选择一位教练，支付定金后等待教练确认。
              </p>
              <div className="space-y-2">
                {scheduledResp.candidates.map((coachId) => (
                  <div
                    key={coachId}
                    className="flex items-center justify-between border rounded-md p-3"
                  >
                    <span className="text-sm">{coachId}</span>
                    <Button
                      size="sm"
                      onClick={() => handleSelectCoach(coachId)}
                      disabled={selectCoach.isPending}
                    >
                      {selectCoach.isPending ? "选择中..." : "选择"}
                    </Button>
                  </div>
                ))}
                {scheduledResp.candidates.length === 0 && (
                  <p className="text-sm text-gray-500">暂无匹配教练</p>
                )}
              </div>
            </div>
            <Button variant="ghost" className="w-full" onClick={() => router.push("/dashboard")}>
              返回
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
