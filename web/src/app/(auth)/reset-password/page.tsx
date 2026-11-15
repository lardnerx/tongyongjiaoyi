import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { SiteFooter } from "@/components/site-footer";

export default function ResetPasswordPage() {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-gray-50 p-4">
      <Card className="relative w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-2xl">重置密码</CardTitle>
          <CardDescription>该功能暂未开放</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <p className="text-sm leading-relaxed text-gray-600">
            为保障账号安全，密码重置需要短信验证，目前尚未开通。如需找回密码，请发送邮件至
            <a
              href="mailto:service@jishi100.online"
              className="mx-1 text-gray-900 underline underline-offset-2"
            >
              service@jishi100.online
            </a>
            并附上注册手机号，我们核验身份后会协助处理。
          </p>
          <Button asChild className="w-full">
            <Link href="/login">返回登录</Link>
          </Button>
          <div className="text-center text-sm text-gray-500">
            还没有账号？{" "}
            <Link href="/register" className="text-blue-500 hover:underline">
              立即注册
            </Link>
          </div>
        </CardContent>
      </Card>
      <div className="w-full max-w-md">
        <SiteFooter />
      </div>
    </div>
  );
}
