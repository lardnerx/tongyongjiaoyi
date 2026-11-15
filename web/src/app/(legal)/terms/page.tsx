import Link from "next/link";

export const metadata = {
  title: "用户协议",
};

export default function TermsPage() {
  return (
    <div className="space-y-6 text-sm leading-7 text-gray-600">
      <header className="space-y-2 border-b border-gray-100 pb-5">
        <h1 className="text-xl font-semibold text-gray-900">用户协议</h1>
        <p className="text-xs text-gray-400">更新日期：2026年11月15日</p>
      </header>

      <p>
        欢迎使用即时百分百在线服务平台（以下简称“本平台”）。本平台由深圳市华创科信息技术有限公司（以下简称“我们”）运营。请您在注册、登录或使用本平台服务前，认真阅读并充分理解本协议全部内容。您完成注册、登录或实际使用本平台服务，即视为您已阅读并同意本协议。
      </p>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">一、服务内容</h2>
        <p>
          本平台为用户提供需求发布、服务资源匹配、订单管理、在线支付、评价与信用记录等在线服务。平台作为信息与技术服务的提供方，协助需求方与服务提供方达成交易，具体服务内容以平台页面展示为准。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">二、账号注册与使用</h2>
        <p>
          1. 您应使用真实、有效的手机号注册账号，并保证所填写信息的真实性与准确性。
        </p>
        <p>
          2. 账号仅限本人使用，您应妥善保管账号及密码。因您主动泄露、出借账号或因您自身保管不当造成的损失，由您自行承担。
        </p>
        <p>
          3. 如发现账号被未经授权使用，请立即通过本协议末尾的联系方式通知我们。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">三、服务预约与履行</h2>
        <p>
          1. 需求方应如实填写服务时间、地点及需求信息；服务提供方应保证其具备提供相应服务的资质与能力。
        </p>
        <p>
          2. 双方应按照订单约定的时间、地点履行服务，并通过平台完成签到、签退等履约确认。
        </p>
        <p>
          3. 平台可依据业务规则对服务过程进行记录与监督，以保障双方合法权益。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">四、支付、退款与发票</h2>
        <p>
          1. 本平台订单款项通过第三方支付机构（如微信支付）完成收付，您应遵守相应支付机构的服务规则。
        </p>
        <p>
          2. 订单取消、退款的条件与比例以平台公示的取消规则及订单页面展示为准。
        </p>
        <p>
          3. 如需开具发票，请通过平台提供的客服渠道提出申请。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">五、取消与违约责任</h2>
        <p>
          任一方未按约定履行订单，应按照平台规则承担相应责任，包括但不限于取消订单、扣除信用分、赔偿对方损失等。具体规则以平台公示内容为准。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">六、评价与信用</h2>
        <p>
          服务完成后，双方可相互评价。您应保证评价内容真实、客观，不得包含侮辱、诽谤、虚假信息或其他违法违规内容。平台有权对异常评价进行处理。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">七、用户行为规范</h2>
        <p>
          您不得利用本平台从事任何违反法律法规、公序良俗或损害他人合法权益的行为，包括但不限于发布虚假信息、恶意刷单、干扰平台正常运行、侵犯他人知识产权或个人信息权益等。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">八、知识产权</h2>
        <p>
          本平台的软件、页面设计、文字、图形等内容的知识产权归我们或相关权利人所有。未经书面许可，任何人不得复制、传播或用于商业用途。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">九、责任限制</h2>
        <p>
          因不可抗力、网络故障、第三方服务异常等非我们可控的原因导致服务中断或数据延迟的，我们将尽力协助处理，但在法律允许的范围内不承担由此产生的间接损失。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">十、协议变更与终止</h2>
        <p>
          我们可根据业务发展或法律法规要求修订本协议，并通过平台公告等方式提示。修订后的协议自公示之日起生效。如您不同意修订内容，应停止使用本平台服务。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">十一、法律适用与争议解决</h2>
        <p>
          本协议的订立、履行与解释均适用中华人民共和国法律。因本协议产生的争议，双方应友好协商解决；协商不成的，任何一方可向我们所在地有管辖权的人民法院提起诉讼。
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-gray-900">十二、联系我们</h2>
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
