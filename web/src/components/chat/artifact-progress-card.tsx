"use client";

import { useState } from "react";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { usePptStatus, usePdfStatus } from "@/hooks/use-api";
import { api } from "@/lib/api";

interface ArtifactProgressCardProps {
  type: "ppt" | "pdf";
  taskId: string;
}

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  generating: "正在生成...",
  uploading: "正在上传...",
  ready: "已生成",
  failed: "生成失败",
};

const TYPE_LABEL: Record<string, string> = {
  ppt: "PPT 生成",
  pdf: "PDF 生成",
};

export function ArtifactProgressCard({ type, taskId }: ArtifactProgressCardProps) {
  // Always call both hooks to satisfy rules-of-hooks
  const pptQuery = usePptStatus(type === "ppt" ? taskId : null);
  const pdfQuery = usePdfStatus(type === "pdf" ? taskId : null);

  const data = type === "ppt" ? pptQuery.data : pdfQuery.data;
  const [downloading, setDownloading] = useState(false);

  const status = data?.status || "pending";
  const progress = data?.progress || 0;
  const label = TYPE_LABEL[type] || type.toUpperCase();
  const statusText =
    status === "generating"
      ? `正在生成 ${label}...`
      : STATUS_TEXT[status] || "处理中...";
  const isReady = status === "ready";
  const isFailed = status === "failed";

  const handleDownload = async () => {
    setDownloading(true);
    try {
      if (type === "ppt") {
        await api.downloadPpt(taskId, `${data?.title || "PPT"}.pptx`);
      } else {
        await api.downloadPdf(taskId, `${data?.title || "PDF"}.pdf`);
      }
    } catch {
      alert("下载失败，请重试");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="border rounded-lg p-3 mt-2 bg-background">
      <div className="flex items-center gap-2 mb-2">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="w-4 h-4"
        >
          <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <span className="text-sm font-medium">{label}</span>
        {!isReady && !isFailed && (
          <span className="text-xs text-muted-foreground ml-auto">{progress}%</span>
        )}
      </div>

      {!isFailed && <Progress value={progress} className="mb-2" />}

      <div className="flex items-center justify-between">
        <span
          className={`text-xs ${
            isFailed
              ? "text-destructive"
              : isReady
                ? "text-green-600"
                : "text-muted-foreground"
          }`}
        >
          {isFailed ? data?.error_message || statusText : statusText}
        </span>
        {isReady && (
          <Button size="sm" variant="default" onClick={handleDownload} disabled={downloading}>
            {downloading ? "下载中..." : `下载 ${label}`}
          </Button>
        )}
      </div>
    </div>
  );
}
