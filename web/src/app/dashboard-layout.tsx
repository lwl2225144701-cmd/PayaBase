"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { MessageSquare, Database, BarChart3, LogOut } from "lucide-react";
import { api } from "@/lib/api";

interface DashboardLayoutProps {
  children: ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  const pathname = usePathname();

  const handleLogout = () => {
    api.clearToken();
    window.location.href = "/login";
  };

  const navItems = [
    { href: "/chat", icon: MessageSquare, label: "聊天" },
    { href: "/kb", icon: Database, label: "知识库" },
    { href: "/stats", icon: BarChart3, label: "统计" },
  ];

  return (
    <div className="h-screen overflow-hidden bg-[radial-gradient(1200px_circle_at_0%_0%,rgba(99,102,241,0.14),transparent_55%),radial-gradient(900px_circle_at_100%_0%,rgba(147,51,234,0.12),transparent_55%),linear-gradient(to_bottom,rgba(248,250,252,1),rgba(245,247,255,1))]">
      <div className="mx-auto flex h-full min-h-0 max-w-[1440px] gap-4 px-4 py-4 md:px-6 md:py-6">
        <aside className="w-64 shrink-0 rounded-lg border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 shadow-sm flex h-full min-h-0 flex-col overflow-hidden">
          <div className="px-4 py-4 border-b bg-background/60">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-md bg-[linear-gradient(135deg,rgba(37,99,235,1),rgba(147,51,234,1))]" />
              <div className="leading-tight">
                <div className="text-[15px] font-semibold">培训助手</div>
                <div className="text-xs text-muted-foreground">企业培训与知识问答</div>
              </div>
            </div>
          </div>

          <nav className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
            {navItems.map((item) => {
              const active =
                pathname === item.href ||
                (item.href !== "/" && pathname?.startsWith(item.href + "/"));
              return (
                <Link key={item.href} href={item.href} className="block">
                  <Button
                    variant="ghost"
                    className={[
                      "w-full justify-start h-10 px-3",
                      active
                        ? "bg-primary/10 text-foreground hover:bg-primary/10"
                        : "text-muted-foreground hover:text-foreground",
                    ].join(" ")}
                  >
                    <item.icon className={["mr-2 h-4 w-4", active ? "text-primary" : ""].join(" ")} />
                    {item.label}
                  </Button>
                </Link>
              );
            })}
          </nav>

          <div className="p-2 border-t bg-background/40">
            <Button variant="ghost" className="w-full justify-start h-10 px-3 text-muted-foreground hover:text-foreground" onClick={handleLogout}>
              <LogOut className="mr-2 h-4 w-4" />
              退出
            </Button>
          </div>
        </aside>

        <main className="min-w-0 flex-1 overflow-hidden rounded-lg border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 shadow-sm flex flex-col min-h-0">
          <div className="flex-1 min-h-0 h-full">{children}</div>
        </main>
      </div>
    </div>
  );
}
