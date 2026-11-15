import type { Metadata } from "next";
import "./globals.css";
import { Inter } from "next/font/google";
import { cn } from "@/lib/utils";
import { Providers } from "@/components/providers";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: {
    default: "即时百分百 · 在线服务",
    template: "%s · 即时百分百",
  },
  description:
    "即时百分百在线服务平台，提供陪驾等服务的在线预约、智能匹配、在线支付与信用评价。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className={cn("font-sans", inter.variable)}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
