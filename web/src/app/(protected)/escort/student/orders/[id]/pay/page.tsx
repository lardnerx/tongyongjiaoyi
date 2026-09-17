"use client";

import { useParams } from "next/navigation";
import { PaymentPage } from "@/components/payment-page";

export default function PayPage() {
  const params = useParams();
  const taskId = params.id as string;

  return <PaymentPage taskId={taskId} />;
}