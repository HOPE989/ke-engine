import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KE Engine 文档上传",
  description: "用于端到端测试文档上传接口的简单页面"
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
