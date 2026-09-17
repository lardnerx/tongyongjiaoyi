"use client";

interface ProcessingProps {
  message?: string;
}

interface SuccessProps {
  amount: number;
  countdown: number;
}

interface FailedProps {
  error: string;
  onRetry: () => void;
}

function Spinner() {
  return (
    <svg className="animate-spin h-10 w-10 text-blue-500" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M12 2a10 10 0 019.95 9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function PaymentProcessing({ message = "支付处理中，请稍候..." }: ProcessingProps) {
  return (
    <div className="rounded-lg border bg-white p-8 flex flex-col items-center gap-4">
      <Spinner />
      <p className="text-gray-700 font-medium">{message}</p>
      <p className="text-sm text-gray-400">请不要关闭页面</p>
    </div>
  );
}

export function PaymentSuccess({ amount, countdown }: SuccessProps) {
  return (
    <div className="rounded-lg border bg-white p-8 flex flex-col items-center gap-4">
      <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center">
        <svg className="w-8 h-8 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </div>
      <div className="text-center">
        <p className="text-lg font-bold text-gray-900">支付成功</p>
        <p className="text-2xl font-bold text-red-500 mt-1">¥{amount.toFixed(2)}</p>
      </div>
      <p className="text-sm text-gray-400">{countdown} 秒后自动返回订单详情</p>
    </div>
  );
}

interface TimeoutProps {
  onBack: () => void;
}

export function PaymentTimeout({ onBack }: TimeoutProps) {
  return (
    <div className="rounded-lg border bg-white p-8 flex flex-col items-center gap-4">
      <div className="w-16 h-16 rounded-full bg-orange-100 flex items-center justify-center">
        <svg className="w-8 h-8 text-orange-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 6v6l4 4" />
        </svg>
      </div>
      <div className="text-center">
        <p className="text-lg font-bold text-gray-900">支付超时</p>
        <p className="text-sm text-orange-500 mt-1">支付已超时，订单已自动取消</p>
      </div>
      <button
        type="button"
        onClick={onBack}
        className="w-full max-w-xs rounded-lg bg-blue-500 py-2.5 text-sm font-medium text-white hover:bg-blue-600 transition-colors"
      >
        返回订单详情
      </button>
    </div>
  );
}

export function PaymentFailed({ error, onRetry }: FailedProps) {
  return (
    <div className="rounded-lg border bg-white p-8 flex flex-col items-center gap-4">
      <div className="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center">
        <svg className="w-8 h-8 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </div>
      <div className="text-center">
        <p className="text-lg font-bold text-gray-900">支付失败</p>
        <p className="text-sm text-red-500 mt-1">{error}</p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="w-full max-w-xs rounded-lg bg-blue-500 py-2.5 text-sm font-medium text-white hover:bg-blue-600 transition-colors"
      >
        重新支付
      </button>
    </div>
  );
}