"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, CalendarIcon, Clock, DownloadIcon, Users, MessageCircle, Sparkles, Search } from "lucide-react";
import {
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
} from "recharts";
import { useStats, useTopQueries, useQueryTrend, useAgentMetrics, useAgentTrend, useSearchMetrics, useSearchTrend } from "@/hooks/use-api";

function latencyColor(ms: number): string {
  if (ms < 1000) return "text-green-600";
  if (ms < 3000) return "text-yellow-600";
  return "text-red-600";
}

function StatCard({
  title,
  value,
  icon,
  className,
  tone = "blue",
}: {
  title: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
  tone?: "blue" | "green" | "purple" | "orange";
}) {
  const toneClass = {
    blue: "bg-blue-50 text-blue-600 border-blue-100",
    green: "bg-emerald-50 text-emerald-600 border-emerald-100",
    purple: "bg-violet-50 text-violet-600 border-violet-100",
    orange: "bg-orange-50 text-orange-600 border-orange-100",
  }[tone];

  return (
    <Card className="border-border/70 bg-background/85 shadow-sm">
      <CardHeader className="pb-1.5">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-xs font-medium text-muted-foreground">{title}</CardTitle>
          {icon ? (
            <div className={`h-8 w-8 rounded-full border flex items-center justify-center shadow-sm ${toneClass}`}>
              {icon}
            </div>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className={`text-2xl font-semibold tracking-tight ${className ?? ""}`}>{value}</div>
        <div className="mt-1 text-xs text-muted-foreground">较昨日 0%</div>
      </CardContent>
    </Card>
  );
}

export default function StatsPage() {
  const [agentWindowDays, setAgentWindowDays] = useState<7 | 30>(7);
  const [searchWindowDays, setSearchWindowDays] = useState<7 | 30>(7);
  const { data: stats, isLoading } = useStats();
  const { data: topQueries } = useTopQueries();
  const { data: trend } = useQueryTrend();
  const { data: agentMetrics } = useAgentMetrics(agentWindowDays);
  const { data: agentTrend } = useAgentTrend(agentWindowDays);
  const { data: searchMetrics } = useSearchMetrics();
  const { data: searchTrend } = useSearchTrend(searchWindowDays);

  if (isLoading) return <div className="p-6">加载中...</div>;

  const avgMs = Math.round(stats?.avg_latency_ms || 0);
  const topData = (topQueries || [])
    .filter((q) => typeof q.query === "string" && q.query.trim().length > 0)
    .slice(0, 10);
  console.log("[StatsPage] topQueries raw:", topQueries, "filtered:", topData);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(900px_circle_at_0%_0%,rgba(99,102,241,0.10),transparent_52%)]">
      <div className="shrink-0 border-b bg-background/35 px-6 pb-5 pt-5 backdrop-blur">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">数据统计</h1>
            <div className="mt-1 text-sm text-muted-foreground">全局运行概览与关键指标</div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex h-9 items-center gap-2 rounded-md border bg-background/80 px-3 text-xs text-muted-foreground shadow-sm"
              disabled
            >
              <CalendarIcon className="h-4 w-4" />
              2024-05-12 ~ 2024-05-18
            </button>
            <button
              type="button"
              className="inline-flex h-9 items-center gap-2 rounded-md border bg-background/80 px-3 text-xs text-muted-foreground shadow-sm"
              disabled
            >
              <DownloadIcon className="h-4 w-4" />
              导出
            </button>
          </div>
        </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard title="总查询量" value={stats?.total_queries ?? 0} icon={<MessageCircle className="h-4 w-4" />} tone="blue" />
        <StatCard title="今日查询量" value={stats?.today_queries ?? 0} icon={<Activity className="h-4 w-4" />} tone="green" />
        <StatCard
          title="平均响应时间"
          value={`${avgMs}ms`}
          className={latencyColor(avgMs)}
          icon={<Clock className="h-4 w-4" />}
          tone="purple"
        />
        <StatCard title="今日活跃用户" value={stats?.active_users ?? 0} icon={<Users className="h-4 w-4" />} tone="orange" />
      </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Trend chart */}
        <Card className="border-border/70 bg-background/70 shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">近 7 天查询趋势</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={trend || []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="count"
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  dot={{ r: 4 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Popular queries */}
        <Card className="border-border/70 bg-background/70 shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">热门问题 Top 10</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {topData.map((item, i) => {
                const maxCount = topData[0]?.count || 1;
                const pct = Math.round((item.count / maxCount) * 100);
                return (
                  <div key={i} className="flex items-center gap-2">
                    <span
                      className="shrink-0 text-sm text-muted-foreground text-right"
                      style={{ width: 180 }}
                      title={item.query}
                    >
                      {item.query.length > 20 ? item.query.slice(0, 20) + "..." : item.query}
                    </span>
                    <div className="flex-1 h-5 bg-muted rounded overflow-hidden">
                      <div
                        className="h-full bg-primary rounded"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="shrink-0 text-sm font-medium w-10 text-right">
                      {item.count}
                    </span>
                  </div>
                );
              })}
              {topData.length === 0 && (
                <div className="text-sm text-muted-foreground py-8 text-center">
                  暂无数据
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Card className="border-border/70 bg-background/70 shadow-sm">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-base">搜索服务指标</CardTitle>
              <div className="inline-flex rounded-md border border-border overflow-hidden">
                <button
                  type="button"
                  className={`px-3 py-1.5 text-xs ${searchWindowDays === 7 ? "bg-primary text-primary-foreground" : "bg-background text-foreground"}`}
                  onClick={() => setSearchWindowDays(7)}
                >
                  近7天
                </button>
                <button
                  type="button"
                  className={`px-3 py-1.5 text-xs ${searchWindowDays === 30 ? "bg-primary text-primary-foreground" : "bg-background text-foreground"}`}
                  onClick={() => setSearchWindowDays(30)}
                >
                  近30天
                </button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <StatCard title="总请求数" value={searchMetrics?.requests_total ?? 0} icon={<Search className="h-4 w-4" />} />
              <StatCard title="缓存命中" value={searchMetrics?.cache_hits ?? 0} icon={<Sparkles className="h-4 w-4" />} />
              <StatCard title="并发合并命中" value={searchMetrics?.coalesced_hits ?? 0} icon={<Activity className="h-4 w-4" />} />
              <StatCard title="缓存条目" value={searchMetrics?.cache_entries ?? 0} icon={<Sparkles className="h-4 w-4" />} />
              <StatCard title="成功返回" value={searchMetrics?.status_ok ?? 0} icon={<Sparkles className="h-4 w-4" />} />
              <StatCard title="空结果" value={searchMetrics?.status_empty ?? 0} icon={<Activity className="h-4 w-4" />} />
              <StatCard title="上游失败" value={searchMetrics?.status_upstream_failed ?? 0} icon={<Activity className="h-4 w-4" />} />
              <StatCard title="超时数" value={searchMetrics?.timeouts ?? 0} icon={<Clock className="h-4 w-4" />} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div className="rounded-md border border-border/70 bg-background/60 p-3 shadow-sm">
                <div className="font-medium mb-2">服务状态</div>
                <div className="space-y-1 text-muted-foreground">
                  <div>非法参数请求：{searchMetrics?.status_bad_request ?? 0}</div>
                  <div>回退引擎命中：{searchMetrics?.fallback_hits ?? 0}</div>
                  <div>上游异常数：{searchMetrics?.upstream_errors ?? 0}</div>
                  <div>熔断跳过数：{searchMetrics?.circuit_open_skips ?? 0}</div>
                </div>
              </div>
              <div className="rounded-md border border-border/70 bg-background/60 p-3 shadow-sm">
                <div className="font-medium mb-2">当前熔断引擎</div>
                {searchMetrics?.circuit_open_engines?.length ? (
                  <div className="flex flex-wrap gap-2">
                    {searchMetrics.circuit_open_engines.map((engine: string) => (
                      <span key={engine} className="rounded bg-muted px-2 py-1 text-xs">
                        {engine}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="text-muted-foreground">暂无</div>
                )}
              </div>
            </div>

            <div className="mt-6">
              <div className="text-sm font-medium mb-2">搜索服务趋势（{searchWindowDays}天）</div>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={searchTrend || []}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="requests_total" name="总请求" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="cache_hits" name="缓存命中" stroke="#16a34a" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="coalesced_hits" name="并发合并" stroke="#d97706" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="status_upstream_failed" name="上游失败" stroke="#dc2626" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Card className="border-border/70 bg-background/70 shadow-sm">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-base">Agent 运行指标</CardTitle>
              <div className="inline-flex rounded-md border border-border overflow-hidden">
                <button
                  type="button"
                  className={`px-3 py-1.5 text-xs ${agentWindowDays === 7 ? "bg-primary text-primary-foreground" : "bg-background text-foreground"}`}
                  onClick={() => setAgentWindowDays(7)}
                >
                  近7天
                </button>
                <button
                  type="button"
                  className={`px-3 py-1.5 text-xs ${agentWindowDays === 30 ? "bg-primary text-primary-foreground" : "bg-background text-foreground"}`}
                  onClick={() => setAgentWindowDays(30)}
                >
                  近30天
                </button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <StatCard title="总运行数" value={agentMetrics?.total_runs ?? 0} icon={<Activity className="h-4 w-4" />} />
              <StatCard title="完成率" value={`${Math.round((agentMetrics?.completion_rate ?? 0) * 100)}%`} icon={<Sparkles className="h-4 w-4" />} />
              <StatCard title="失败率" value={`${Math.round((agentMetrics?.failure_rate ?? 0) * 100)}%`} icon={<Activity className="h-4 w-4" />} />
              <StatCard title="平均步数" value={Number(agentMetrics?.avg_steps_per_run ?? 0).toFixed(2)} icon={<Clock className="h-4 w-4" />} />
              <StatCard title="触发重试Run" value={agentMetrics?.retry_triggered_runs ?? 0} icon={<Activity className="h-4 w-4" />} />
              <StatCard title="重试成功Run" value={agentMetrics?.retry_success_runs ?? 0} icon={<Sparkles className="h-4 w-4" />} />
              <StatCard title="重试成功率" value={`${Math.round((agentMetrics?.retry_success_rate ?? 0) * 100)}%`} icon={<Sparkles className="h-4 w-4" />} />
              <StatCard title="失败Run数" value={agentMetrics?.failed_runs ?? 0} icon={<Activity className="h-4 w-4" />} />
            </div>

            <div>
              <div className="text-sm font-medium mb-2">错误类型分布</div>
              <div className="space-y-2">
                {Object.entries(agentMetrics?.error_type_distribution || {}).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2">
                    <span className="shrink-0 text-sm text-muted-foreground text-right w-40">{k}</span>
                    <div className="flex-1 h-4 bg-muted rounded overflow-hidden">
                      <div
                        className="h-full bg-primary rounded"
                        style={{
                          width: `${Math.max(
                            5,
                            Math.round(
                              (Number(v) /
                                Math.max(
                                  1,
                                  ...Object.values(agentMetrics?.error_type_distribution || {}).map((x) => Number(x))
                                )) *
                                100
                            )
                          )}%`,
                        }}
                      />
                    </div>
                    <span className="shrink-0 text-sm font-medium w-10 text-right">{Number(v)}</span>
                  </div>
                ))}
                {Object.keys(agentMetrics?.error_type_distribution || {}).length === 0 && (
                  <div className="text-sm text-muted-foreground">暂无错误数据</div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Card className="border-border/70 bg-background/70 shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">Agent 质量趋势（{agentWindowDays}天）</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={agentTrend || []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="total_runs" name="总Run" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="completed_runs" name="完成Run" stroke="#16a34a" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="failed_runs" name="失败Run" stroke="#dc2626" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="retry_runs" name="重试Run" stroke="#d97706" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
      </div>
    </div>
  );
}
