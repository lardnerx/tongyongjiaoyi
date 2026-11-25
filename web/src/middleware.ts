import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const authToken = request.cookies.get("auth-token")?.value;
  const activeRole = request.cookies.get("active-role")?.value;

  const publicPaths = [
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/terms",
    "/privacy",
    "/about",
  ];
  const isPublicPath = publicPaths.some((p) => pathname.startsWith(p));

  // 客户端路由（RSC）导航：部分移动端浏览器写 Cookie 有延迟或直接禁用 Cookie，
  // 此时不弹回登录页，交给前端根据本地登录态渲染
  const isClientNavigation = request.headers.get("rsc") === "1";

  // 受保护路径：/dashboard、/escort、/admin 等（除 publicPaths 外的全部路径）
  // /admin 路径在此仅校验登录；admin 角色校验由前端页面运行时检查（页面加载时调用 /auth/me 检查 roles）
  // 未登录访问受保护路径 → 跳登录
  if (!authToken && !isPublicPath && !isClientNavigation) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // 已登录访问登录页 → 跳服务列表
  if (authToken && isPublicPath) {
    return NextResponse.redirect(new URL("/services", request.url));
  }

  // 角色守卫：学员不能访问教练页面，教练不能访问学员页面
  if (authToken && pathname.startsWith("/escort/coach") && activeRole !== "supplier") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  if (authToken && pathname.startsWith("/escort/student") && activeRole !== "demander") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
