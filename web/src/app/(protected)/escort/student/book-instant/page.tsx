"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AmapPicker } from "@/components/amap-picker";
import { EscortOrderFields } from "@/components/escort-order-fields";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import type { OrderInfo } from "@/types/escort";

export default function BookInstantPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const [location, setLocation] = useState<{ lat: number; lng: number; address: string } | null>(null);
  const [carType, setCarType] = useState("economy");
  const [duration, setDuration] = useState(2);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!location) {
      setError("请在地图上选择上车地点");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const order = await apiClient.post<OrderInfo>("/escort/orders", {
        demander_id: user?.user_id,
        domain_tag: "escort",
        origin_lat: location.lat,
        origin_lng: location.lng,
        origin_address: location.address,
        car_type: carType,
        required_skills: ["coach_license"],
        duration_hours: duration,
        order_type: "REALTIME",
      });
      router.push(`/escort/student/orders/${order.task_id}`);
    } catch (e: any) {
      setError(e.message || "下单失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <h1 className="text-2xl font-bold">实时叫车</h1>

        <div className="space-y-2">
          <label className="text-sm font-medium">选择上车地点</label>
          <AmapPicker onChange={setLocation} />
        </div>

        <EscortOrderFields
          carType={carType}
          onCarTypeChange={setCarType}
          duration={duration}
          onDurationChange={setDuration}
        />

        {error && <p className="text-sm text-red-500">{error}</p>}

        <Button className="w-full" onClick={handleSubmit} disabled={submitting}>
          {submitting ? "下单中..." : "立即叫车"}
        </Button>

        <Button variant="ghost" className="w-full" onClick={() => router.push("/escort/student")}>
          返回
        </Button>
      </div>
    </div>
  );
}
