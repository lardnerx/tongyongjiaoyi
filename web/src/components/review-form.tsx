"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";

interface ReviewFormProps {
  taskId: string;
  reviewerId: string;
  reviewerRole: "STUDENT" | "COACH";
  onSubmitted: () => void;
}

const STUDENT_DIMENSIONS = [
  { key: "teaching_score", label: "教学能力" },
  { key: "patience_score", label: "耐心程度" },
  { key: "safety_score", label: "安全记录" },
];

const COACH_DIMENSIONS = [
  { key: "punctuality_score", label: "守时程度" },
  { key: "cooperation_score", label: "配合度" },
  { key: "payment_score", label: "付款及时性" },
];

export function ReviewForm({ taskId, reviewerId, reviewerRole, onSubmitted }: ReviewFormProps) {
  const dimensions = reviewerRole === "STUDENT" ? STUDENT_DIMENSIONS : COACH_DIMENSIONS;
  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await apiClient.post(`/escort/orders/${taskId}/reviews`, {
        reviewer_id: reviewerId,
        reviewer_role: reviewerRole,
        ratings: scores,
        comment,
      });
      onSubmitted();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="font-medium">评价</h3>
      {dimensions.map((dim) => (
        <div key={dim.key} className="flex items-center gap-2">
          <span className="text-sm w-24">{dim.label}</span>
          <div className="flex gap-1">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                type="button"
                className={`text-xl ${scores[dim.key] >= star ? "text-yellow-400" : "text-gray-300"}`}
                onClick={() => setScores({ ...scores, [dim.key]: star })}
              >
                ★
              </button>
            ))}
          </div>
        </div>
      ))}
      <textarea
        className="w-full rounded-md border border-gray-300 p-2 text-sm"
        placeholder="写点什么..."
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={3}
      />
      <Button onClick={handleSubmit} disabled={submitting || Object.keys(scores).length < 3}>
        {submitting ? "提交中..." : "提交评价"}
      </Button>
    </div>
  );
}
