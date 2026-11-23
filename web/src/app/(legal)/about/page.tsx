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

interface ServiceItem {
  name: string;
  description: string;
  live: boolean;
}

const SERVICES: ServiceItem[] = [
  { name: "陪驾", description: "实时呼叫或预约司机，上门陪练", live: true },
  { name: "应急补胎", description: "道路现场补胎、换胎", live: false },
  { name: "应急搭电", description: "电瓶亏电快速搭电", live: false },
  { name: "应急充电", description: "新能源车移动应急充电", live: false },
  { name: "即时水电维修", description: "水管、电路、门锁等家庭急修", live: false },
  { name: "即时宠物服务", description: "上门喂养、遛狗、宠物洗护", live: false },
  { name: "即时家政服务", description: "日常保洁、深度清洁、家电清洗", live: false },
];

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
          目前平台已上线陪驾服务场景：客户可实时呼叫或预约司机，司机可在线接单，双方通过平台完成订单履约、计时计费、在线支付与互评，全流程留痕，保障交易透明可追溯。平台正按同一套服务框架，陆续接入道路应急服务与即时生活服务。
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-base font-semibold text-gray-900">服务范围</h2>
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-100 bg-gray-50/60 text-xs">
          {SERVICES.map((service) => (
            <li key={service.name} className="flex items-center gap-3 px-4 py-3">
              <span className="w-28 shrink-0 text-gray-700">{service.name}</span>
              <span className="min-w-0 flex-1 text-gray-500">{service.description}</span>
              <span
                className={
                  service.live
                    ? "shrink-0 rounded-full bg-green-50 px-2 py-0.5 text-[11px] text-green-600"
                    : "shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-400"
                }
              >
                {service.live ? "已上线" : "即将上线"}
              </span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-gray-400">
          标注“即将上线”的服务正在接入中，上线后可在服务列表中直接使用。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">我们提供的服务</h2>
        <p>· 需求发布与订单管理：实时单、预约单两种模式，支持取消规则与信用约束。</p>
        <p>· 智能匹配与承接：系统推荐与司机抢单结合，提升响应效率。</p>
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
