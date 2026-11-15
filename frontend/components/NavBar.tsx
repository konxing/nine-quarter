"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "每日选股" },
  { href: "/portfolio", label: "模拟投资" },
  { href: "/review", label: "每日复盘" },
  { href: "/history", label: "历史记录" },
  { href: "/settings", label: "设置" },
];

export default function NavBar() {
  const pathname = usePathname();
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">
          <span className="brand-name">Nine Quarter</span>
          <span className="brand-sub">AI 股票筛选与模拟投资 · 个人研究 · 非实盘</span>
        </div>
        <nav className="nav">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={pathname === l.href ? "nav-link active" : "nav-link"}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}