"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { BookOpen, Bot, GraduationCap, Lock, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [code, setCode] = useState("");

  const handleLogin = async () => {
    if (!code.trim()) {
      alert("请输入用户名");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/sso?code=${code}`, {
        method: "POST",
      });
      const data = await res.json();
      if (data.code === 0 && data.data.access_token) {
        api.setToken(data.data.access_token);
        router.push("/chat");
      } else {
        alert("登录失败: " + (data.msg || "未知错误"));
      }
    } catch (e) {
      alert("登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen overflow-hidden bg-[linear-gradient(135deg,rgba(88,107,255,0.40),rgba(234,242,255,1)_52%,rgba(248,250,252,1)_100%)]">
      {/* Decorative background (planet + light trails) */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -left-40 -top-24 h-[520px] w-[520px] rounded-full bg-[radial-gradient(circle_at_30%_30%,rgba(99,102,241,0.55),rgba(147,51,234,0.20)_55%,transparent_72%)] blur-[2px]" />
        <div className="absolute left-16 top-[56%] h-[420px] w-[420px] -translate-y-1/2 rounded-full bg-[radial-gradient(circle_at_35%_35%,rgba(99,102,241,0.35),rgba(34,197,94,0.08)_40%,rgba(59,130,246,0.10)_55%,transparent_72%)] shadow-[0_40px_120px_rgba(99,102,241,0.18)]" />
        <div className="absolute left-[-12%] top-[63%] h-[340px] w-[640px] -translate-y-1/2 rotate-[-10deg] rounded-full bg-[radial-gradient(closest-side,rgba(255,255,255,0.65),rgba(255,255,255,0.10),transparent)] blur-[10px]" />
        <div className="absolute left-[-8%] top-[70%] h-[260px] w-[620px] -translate-y-1/2 rotate-[-12deg] rounded-full bg-[radial-gradient(closest-side,rgba(99,102,241,0.22),rgba(147,51,234,0.10),transparent)] blur-[14px]" />
        <div className="absolute left-[18%] top-[48%] h-2 w-2 rounded-full bg-white/60 shadow-[0_0_18px_rgba(255,255,255,0.8)]" />
        <div className="absolute left-[22%] top-[52%] h-1.5 w-1.5 rounded-full bg-white/50 shadow-[0_0_14px_rgba(255,255,255,0.7)]" />
        <div className="absolute left-[28%] top-[46%] h-1 w-1 rounded-full bg-white/40 shadow-[0_0_10px_rgba(255,255,255,0.65)]" />
      </div>

      <div className="relative mx-auto grid min-h-screen max-w-[1240px] grid-cols-1 items-center gap-10 px-6 py-10 md:grid-cols-2">
        {/* Left content */}
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/70 shadow-sm ring-1 ring-white/50">
              <Bot className="h-5 w-5 text-primary" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold">PayaBase</div>
              <div className="mt-0.5 text-xs text-muted-foreground">AI 知识库问答助手</div>
            </div>
          </div>

          <h1 className="mt-8 text-4xl font-semibold leading-tight tracking-tight text-foreground">
            让知识更易检索
            <br />
            让学习更有价值
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-muted-foreground">
            基于大模型的个人 AI 知识库问答与管理平台
          </p>

          <div className="mt-10 space-y-5">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-white/65 shadow-sm ring-1 ring-white/40">
                <GraduationCap className="h-4 w-4 text-primary" />
              </div>
              <div>
                <div className="text-sm font-medium">智能问答</div>
                <div className="mt-0.5 text-xs text-muted-foreground">7x24 小时培训知识答疑</div>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-white/65 shadow-sm ring-1 ring-white/40">
                <BookOpen className="h-4 w-4 text-primary" />
              </div>
              <div>
                <div className="text-sm font-medium">知识沉淀</div>
                <div className="mt-0.5 text-xs text-muted-foreground">企业知识库统一管理与索引</div>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-white/65 shadow-sm ring-1 ring-white/40">
                <Lock className="h-4 w-4 text-primary" />
              </div>
              <div>
                <div className="text-sm font-medium">权限隔离</div>
                <div className="mt-0.5 text-xs text-muted-foreground">部门知识库可控共享</div>
              </div>
            </div>
          </div>
        </div>

        {/* Right login card */}
        <div className="flex justify-center md:justify-end">
          <Card className="w-full max-w-md border border-white/40 bg-white/75 backdrop-blur supports-[backdrop-filter]:bg-white/60 shadow-[0_24px_70px_rgba(15,23,42,0.12)]">
            <CardHeader className="text-center pb-3">
              <CardTitle className="text-2xl">欢迎回来</CardTitle>
              <CardDescription>登录你的 PayaBase 账号</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="请输入用户名"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                  className="h-11 bg-white/70 pl-9 shadow-sm"
                />
              </div>

              {/* NOTE: 仅样式对齐，不新增密码/记住我等真实登录逻辑 */}
              <div className="relative opacity-75">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="请输入密码"
                  value=""
                  readOnly
                  className="h-11 bg-white/50 pl-9 shadow-sm"
                />
              </div>

              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <label className="inline-flex items-center gap-2 select-none opacity-75">
                  <input type="checkbox" className="h-3.5 w-3.5 rounded border-border" disabled />
                  记住我
                </label>
                <button type="button" className="underline underline-offset-4 opacity-75" disabled>
                  忘记密码？
                </button>
              </div>

              <Button
                className="w-full h-11 rounded-md bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] text-white hover:opacity-95 shadow-sm"
                size="lg"
                onClick={handleLogin}
                disabled={loading}
              >
                {loading ? "登录中..." : "登录"}
              </Button>

              <div className="pt-1 text-center text-xs text-muted-foreground">
                还没有账号？
                <span className="ml-1 text-primary">联系管理员开通</span>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="md:col-span-2 pt-10 text-center text-xs text-muted-foreground/80">
          © 2024 PayaBase. All rights reserved.
        </div>
      </div>
    </div>
  );
}
