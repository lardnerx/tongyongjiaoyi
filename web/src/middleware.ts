import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const authToken = request.cookies.get("auth-token")?.value;
  const activeRole = request.cookies.get("active-role")?.value;

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

  // 角色守卫：学员不能访问教练页面，教练不能访问学员页面
  if (pathname.startsWith("/escort/coach") && activeRole !== "supplier") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  if (pathname.startsWith("/escort/student") && activeRole !== "demander") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
