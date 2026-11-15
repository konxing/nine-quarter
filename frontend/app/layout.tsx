import type { Metadata } from "next";
import NavBar from "@/components/NavBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nine Quarter · AI 股票筛选与模拟投资",
  description: "AI 股票筛选与模拟投资系统（个人研究用途，非实盘）",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <NavBar />
        <main className="container">{children}</main>
        <div className="footer-note">
          个人研究用途 · 模拟投资非实盘 · 数据来自本地后端，仅供研究参考
        </div>
      </body>
    </html>
  );
}