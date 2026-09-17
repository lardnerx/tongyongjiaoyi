"use client";

export type PaymentMethod = "alipay" | "wechat";

interface Props {
  value: PaymentMethod;
  onChange: (method: PaymentMethod) => void;
}

const methods: { key: PaymentMethod; label: string; icon: string }[] = [
  { key: "alipay", label: "支付宝", icon: "💳" },
  { key: "wechat", label: "微信支付", icon: "💚" },
];

export function PaymentMethodSelector({ value, onChange }: Props) {
  return (
    <div className="rounded-lg border bg-white p-4 space-y-3">
      <h3 className="font-medium text-sm text-gray-500">支付方式</h3>
      <div className="grid grid-cols-2 gap-3">
        {methods.map((m) => {
          const active = value === m.key;
          return (
            <button
              key={m.key}
              type="button"
              onClick={() => onChange(m.key)}
              className={`
                flex items-center justify-center gap-2 rounded-lg border-2 p-3 text-sm
                transition-all duration-150
                ${active
                  ? m.key === "alipay"
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : "border-green-500 bg-green-50 text-green-700"
                  : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
                }
              `}
            >
              <span className="text-lg">{m.icon}</span>
              <span className="font-medium">{m.label}</span>
              {active && (
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                  <path d="M20 6L9 17l-5-5" />
                </svg>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}