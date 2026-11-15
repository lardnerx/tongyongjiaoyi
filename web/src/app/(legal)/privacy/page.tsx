import Link from "next/link";

export const metadata = {
  title: "隐私政策",
};

export default function PrivacyPage() {
  return (
    <div className="space-y-6 text-sm leading-7 text-gray-600">
      <header className="space-y-2 border-b border-gray-100 pb-5">
        <h1 className="text-xl font-semibold text-gray-900">隐私政策</h1>
        <p className="text-xs text-gray-400">更新日期：2026年11月15日</p>
      </header>

      <p>
        深圳市华创科信息技术有限公司（以下简称“我们”）深知个人信息对您的重要性，并会尽力保护您的个人信息安全。本政策说明我们在您使用即时百分百在线服务平台（以下简称“本平台”）时，如何收集、使用、存储、共享和保护您的个人信息，以及您享有的相关权利。
      </p>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">一、我们收集的信息</h2>
        <p>
          1. <span className="font-medium text-gray-800">账号信息</span>：手机号、昵称、密码（加密存储）、头像，用于创建和管理账号。
        </p>
        <p>
          2. <span className="font-medium text-gray-800">订单与服务信息</span>：预约时间、服务地点、订单金额、支付状态、履约记录，用于完成服务撮合与交易。
        </p>
        <p>
          3. <span className="font-medium text-gray-800">位置信息</span>：在您主动使用定位或就近匹配功能时，我们会获取您的位置信息，用于展示附近服务资源。您可在设备或浏览器中关闭定位授权。
        </p>
        <p>
          4. <span className="font-medium text-gray-800">设备与日志信息</span>：浏览器类型、访问时间、操作日志，用于保障系统安全与故障排查。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">二、信息的使用目的</h2>
        <p>
          我们仅在实现以下目的的必要范围内使用您的个人信息：提供账号注册与登录、完成服务匹配与订单履约、处理支付与退款、提供客户服务与争议处理、保障平台安全、依法履行法定义务。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">三、Cookie 与同类技术</h2>
        <p>
          为维持登录状态、记住您的偏好并保障安全，我们会在您的浏览器中存储必要的 Cookie 或本地存储信息。您可通过浏览器设置清除或拒绝 Cookie，但这可能影响部分功能的正常使用。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">四、信息的共享</h2>
        <p>
          1. 为完成订单，我们会向订单相对方提供履约所必需的信息，例如服务时间、地点及联系方式。
        </p>
        <p>
          2. 为完成支付，我们会向支付机构提供必要的订单与交易信息。
        </p>
        <p>
          3. 我们不会出售您的个人信息。除法律法规要求或经您单独同意外，我们不会向无关第三方提供您的个人信息。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">五、信息的存储与保护</h2>
        <p>
          您的个人信息存储于中华人民共和国境内的服务器。我们采用加密传输、访问控制、密码加密存储等措施保护您的信息，并仅在实现本政策所述目的所必需的期限内保留，超出期限后将删除或匿名化处理。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">六、您的权利</h2>
        <p>
          您有权访问、更正、补充、删除您的个人信息，有权撤回已作出的授权同意，并可申请注销账号。您可通过平台“个人中心”相关功能或本政策末尾的联系方式行使上述权利。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">七、未成年人保护</h2>
        <p>
          本平台服务面向具有完全民事行为能力的成年人。若您为未成年人，请在监护人陪同和同意下使用本平台服务。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">八、第三方服务</h2>
        <p>
          本平台可能集成地图、支付、短信通知等第三方服务。该等第三方服务由相应服务商独立提供，其信息处理行为适用其自身的隐私政策。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">九、政策更新</h2>
        <p>
          我们可能根据业务调整或法律法规变化更新本政策，并通过平台公告等方式提示。重大变更时，我们会以更显著的方式通知您。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">十、联系我们</h2>
        <p>运营主体：深圳市华创科信息技术有限公司</p>
        <p>客服邮箱：service@jishi100.online</p>
        <p>ICP 备案号：粤ICP备2026155792号</p>
      </section>

      <div className="border-t border-gray-100 pt-5">
        <Link href="/login" className="text-blue-500 hover:underline">
          ← 返回登录
        </Link>
      </div>
    </div>
  );
}
