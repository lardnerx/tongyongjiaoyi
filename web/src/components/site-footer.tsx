import Link from "next/link";

const COMPANY_NAME =
  process.env.NEXT_PUBLIC_COMPANY_NAME ?? "深圳市华创科信息技术有限公司";
const ICP_NUMBER = process.env.NEXT_PUBLIC_ICP_NUMBER ?? "粤ICP备2026155792号";

/** 站点合规页脚：协议入口、版权归属、ICP 备案号。 */
export function SiteFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className="mt-6 space-y-1.5 text-center text-xs text-gray-400">
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
        <Link href="/terms" className="hover:text-gray-600 hover:underline">
          用户协议
        </Link>
        <span className="text-gray-300">|</span>
        <Link href="/privacy" className="hover:text-gray-600 hover:underline">
          隐私政策
        </Link>
      </div>
      <p>
        © {year} {COMPANY_NAME} 版权所有
      </p>
      <p>
        <a
          href="https://beian.miit.gov.cn"
          target="_blank"
          rel="noreferrer"
          className="hover:text-gray-600 hover:underline"
        >
          {ICP_NUMBER}
        </a>
      </p>
    </footer>
  );
}
