import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "UMCP Web",
  description: "通用交易平台前端",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
