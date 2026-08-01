import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 从 cookie 读取 auth-token（Zustand persist 默认存 localStorage，
  // 但 middleware 运行在 Edge Runtime 无法访问 localStorage，
  // 所以通过 cookie 传递认证状态——需在 auth-store 中同步写入 cookie）
  const authToken = request.cookies.get("auth-token")?.value;

  // 公开路径（无需登录）
  const publicPaths = ["/login", "/register", "/forgot-password"];
  const isPublicPath = publicPaths.some((p) => pathname.startsWith(p));

  // 未登录访问受保护路径 → 跳登录
  if (!authToken && !isPublicPath) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // 已登录访问登录页 → 跳 Dashboard
  if (authToken && isPublicPath) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
