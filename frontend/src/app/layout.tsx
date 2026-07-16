import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KE Engine 测试控制台",
  description: "用于端到端测试文档与 Chat 接口的前端控制台"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
