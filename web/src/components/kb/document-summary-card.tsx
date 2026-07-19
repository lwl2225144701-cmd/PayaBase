"use client";

import { FileIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DocumentDetail } from "@/types";

function fileTypeTheme(fileType: string): string {
  const t = (fileType || "").toLowerCase();
  if (t.includes("pdf")) return "bg-blue-50 text-blue-600 border-blue-100 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800/50";
  if (t.includes("doc")) return "bg-indigo-50 text-indigo-600 border-indigo-100 dark:bg-indigo-950/50 dark:text-indigo-400 dark:border-indigo-800/50";
  if (t.includes("sheet") || t.includes("xls") || t.includes("csv")) return "bg-rose-50 text-rose-600 border-rose-100 dark:bg-rose-950/50 dark:text-rose-400 dark:border-rose-800/50";
  if (t.includes("image")) return "bg-violet-50 text-violet-600 border-violet-100 dark:bg-violet-950/50 dark:text-violet-400 dark:border-violet-800/50";
  if (t.includes("markdown") || t.includes("md") || t.includes("txt")) return "bg-emerald-50 text-emerald-600 border-emerald-100 dark:bg-emerald-950/50 dark:text-emerald-400 dark:border-emerald-800/50";
  return "bg-blue-50 text-blue-600 border-blue-100 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800/50";
}

function formatBytes(n: number | undefined | null): string {
  if (n === undefined || n === null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function formatDate(s?: string): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

interface DocumentSummaryCardProps {
  document: DocumentDetail | undefined;
  isLoading?: boolean;
}

function InfoItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-foreground">{value}</span>
    </div>
  );
}

export function DocumentSummaryCard({ document, isLoading }: DocumentSummaryCardProps) {
  if (isLoading || !document) {
    return (
      <Card className="border-border/60 bg-background/80 shadow-sm">
        <CardContent className="p-5">
          <div className="flex animate-pulse items-start gap-4">
            <div className="h-12 w-12 shrink-0 rounded-lg bg-muted" />
            <div className="min-w-0 flex-1 space-y-2">
              <div className="h-4 w-1/3 rounded bg-muted" />
              <div className="h-3 w-1/2 rounded bg-muted/70" />
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const fileType = (document.file_type || "file").split("/").pop()?.toUpperCase() || "FILE";
  const statusText = document.status === "ready" ? "已完成" : document.status === "indexing" ? "索引中" : document.status === "pending" ? "等待中" : document.status === "error" ? "失败" : document.status;

  return (
    <Card className="border-border/60 bg-background/80 shadow-sm">
      <CardContent className="p-5">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <div className="flex min-w-0 items-center gap-4">
            <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border ${fileTypeTheme(document.file_type)}`}>
              <FileIcon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold leading-snug" title={document.title}>
                {document.title}
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">{document.file_type || "—"}</p>
            </div>
          </div>

          <div className="grid flex-1 grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
            <InfoItem label="大小" value={formatBytes(document.file_size)} />
            <InfoItem label="上传时间" value={formatDate(document.created_at)} />
            <InfoItem label="分段策略" value={document.strategy || "通用"} />
            <InfoItem label="切片数量" value={`${document.chunk_count ?? 0} chunks`} />
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">状态</span>
              <Badge
                variant="outline"
                className={`w-fit rounded-md px-2 py-0.5 text-xs font-normal ${
                  document.status === "ready"
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800/50 dark:bg-emerald-950/40 dark:text-emerald-400"
                    : document.status === "error"
                    ? "border-red-200 bg-red-50 text-red-700 dark:border-red-800/50 dark:bg-red-950/40 dark:text-red-400"
                    : document.status === "indexing"
                    ? "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800/50 dark:bg-blue-950/40 dark:text-blue-400"
                    : ""
                }`}
              >
                {statusText}
              </Badge>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
