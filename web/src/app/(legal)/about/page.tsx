import Link from "next/link";

export const metadata = {
  title: "关于我们",
};

const COMPANY_NAME =
  process.env.NEXT_PUBLIC_COMPANY_NAME ?? "深圳市华创科信息技术有限公司";
const CREDIT_CODE =
  process.env.NEXT_PUBLIC_CREDIT_CODE ?? "91440300797966290H";
const ICP_NUMBER = process.env.NEXT_PUBLIC_ICP_NUMBER ?? "粤ICP备2026155792号";
const CONTACT_EMAIL =
  process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? "service@jishi100.online";

export default function AboutPage() {
  return (
    <div className="space-y-6 text-sm leading-7 text-gray-600">
      <header className="flex items-center gap-3 border-b border-gray-100 pb-5">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gray-900 text-white shadow-sm">
          <span className="text-xs font-semibold tracking-tight">100%</span>
        </div>
        <div className="space-y-0.5">
          <h1 className="text-xl font-semibold text-gray-900">关于我们</h1>
          <p className="text-xs text-gray-400">即时百分百 · 在线服务</p>
        </div>
      </header>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">平台简介</h2>
        <p>
          即时百分百是由{COMPANY_NAME}运营的在线服务平台。平台以“即时响应、透明交易、双向信任”为目标，为服务需求方与服务提供方提供在线下单、智能匹配、履约确认、在线支付、双向评价与信用记录等全流程服务。
        </p>
        <p>
          目前平台已上线陪驾服务场景：学员可实时呼叫或预约教练，教练可在线接单，双方通过平台完成订单履约、计时计费、在线支付与互评，全流程留痕，保障交易透明可追溯。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">我们提供的服务</h2>
        <p>· 需求发布与订单管理：实时单、预约单两种模式，支持取消规则与信用约束。</p>
        <p>· 智能匹配与承接：系统推荐与教练抢单结合，提升响应效率。</p>
        <p>· 在线支付与对账：支持微信支付，订单款项可查询、可追溯。</p>
        <p>· 履约与安全：签到签退、服务时长记录、异常订单监控。</p>
        <p>· 评价与信用：服务完成后双向互评，形成可积累的信用档案。</p>
      </section>

      <section className="space-y-3">
        <h2 className="text-base font-semibold text-gray-900">主体信息</h2>
        <dl className="divide-y divide-gray-100 rounded-lg border border-gray-100 bg-gray-50/60 text-xs">
          <div className="flex gap-3 px-4 py-3">
            <dt className="w-28 shrink-0 text-gray-400">运营主体</dt>
            <dd className="text-gray-700">{COMPANY_NAME}</dd>
          </div>
          <div className="flex gap-3 px-4 py-3">
            <dt className="w-28 shrink-0 text-gray-400">统一社会信用代码</dt>
            <dd className="font-mono tracking-wide text-gray-700">{CREDIT_CODE}</dd>
          </div>
          <div className="flex gap-3 px-4 py-3">
            <dt className="w-28 shrink-0 text-gray-400">ICP 备案号</dt>
            <dd className="text-gray-700">
              <a
                href="https://beian.miit.gov.cn"
                target="_blank"
                rel="noreferrer"
                className="hover:text-gray-900 hover:underline"
              >
                {ICP_NUMBER}
              </a>
            </dd>
          </div>
          <div className="flex gap-3 px-4 py-3">
            <dt className="w-28 shrink-0 text-gray-400">客服邮箱</dt>
            <dd className="text-gray-700">
              <a
                href={`mailto:${CONTACT_EMAIL}`}
                className="hover:text-gray-900 hover:underline"
              >
                {CONTACT_EMAIL}
              </a>
            </dd>
          </div>
        </dl>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">联系我们</h2>
        <p>
          如您在使用过程中遇到订单、支付、账号或隐私相关问题，欢迎通过客服邮箱
          <a
            href={`mailto:${CONTACT_EMAIL}`}
            className="mx-1 text-blue-500 hover:underline"
          >
            {CONTACT_EMAIL}
          </a>
          与我们联系，我们会在收到后尽快处理并回复。
        </p>
      </section>

      <div className="flex items-center gap-4 border-t border-gray-100 pt-5">
        <Link href="/login" className="text-blue-500 hover:underline">
          ← 返回登录
        </Link>
        <Link href="/terms" className="text-gray-500 hover:underline">
          用户协议
        </Link>
        <Link href="/privacy" className="text-gray-500 hover:underline">
          隐私政策
        </Link>
      </div>
    </div>
  );
}
