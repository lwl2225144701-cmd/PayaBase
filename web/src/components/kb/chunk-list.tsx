"use client";

import { useEffect } from "react";
import { SearchIcon, XIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChunkCard } from "./chunk-card";
import type { Chunk } from "@/types";

const STATUS_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "indexed", label: "已向量化" },
  { value: "error", label: "异常" },
];

interface ChunkListProps {
  chunks: Chunk[];
  total: number;
  page: number;
  pageSize: number;
  keyword: string;
  statusFilter: string;
  selectedChunkId: string | undefined;
  onKeywordChange: (keyword: string) => void;
  onStatusFilterChange: (status: string) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  onSelectChunk: (chunk: Chunk) => void;
  kbId: string;
  isLoading?: boolean;
  error?: Error | null;
  listRef?: React.RefObject<HTMLDivElement>;
}

export function ChunkList({
  chunks,
  total,
  page,
  pageSize,
  keyword,
  statusFilter,
  selectedChunkId,
  onKeywordChange,
  onStatusFilterChange,
  onPageChange,
  onPageSizeChange,
  onSelectChunk,
  kbId,
  isLoading,
  error,
  listRef,
}: ChunkListProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startIndex = (page - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, total);

  // 选中切片变化时，把对应卡片滚到视口里
  useEffect(() => {
    if (!selectedChunkId) return;
    const el = document.querySelector<HTMLElement>(`[data-chunk-id="${CSS.escape(selectedChunkId)}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selectedChunkId, page]);

  const renderBody = () => {
    if (isLoading) {
      return (
        <div className="space-y-3 p-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      );
    }

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center p-8 text-center">
          <p className="text-sm text-red-600">切片加载失败：{error.message}</p>
        </div>
      );
    }

    if (chunks.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center p-8 text-center text-sm text-muted-foreground">
          {keyword || statusFilter !== "all" ? "没有找到匹配的切片" : "暂无切片"}
        </div>
      );
    }

    return (
      <div className="space-y-3 p-4">
        {chunks.map((chunk, idx) => (
          <ChunkCard
            key={chunk.chunk_id}
            chunk={chunk}
            index={startIndex + idx}
            isSelected={chunk.chunk_id === selectedChunkId}
            onSelect={onSelectChunk}
            kbId={kbId}
          />
        ))}
      </div>
    );
  };

  return (
    <Card className="flex h-full flex-col overflow-hidden border-border/60 bg-background/80 shadow-sm">
      <CardHeader className="shrink-0 border-b px-4 py-3">
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="text-sm font-semibold">切片列表</CardTitle>
            <span className="text-xs text-muted-foreground">共 {total} 个</span>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-1">
              {STATUS_OPTIONS.map((opt) => {
                const active = statusFilter === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => onStatusFilterChange(opt.value)}
                    className={`h-7 rounded-md px-2.5 text-xs font-medium transition-colors ${
                      active
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
            <div className="relative w-full sm:w-[200px]">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                value={keyword}
                onChange={(e) => onKeywordChange(e.target.value)}
                placeholder="搜索 chunk 内容 / chunk_id"
                className="h-8 w-full rounded-md border border-input bg-background/70 pl-8 pr-7 text-xs outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
              />
              {keyword && (
                <button
                  type="button"
                  onClick={() => onKeywordChange("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <XIcon className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 min-h-0 p-0">
        <ScrollArea className="h-full">
          <div ref={listRef}>{renderBody()}</div>
        </ScrollArea>
      </CardContent>
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-3 text-xs">
        <div className="text-muted-foreground">
          {total > 0 ? `${startIndex + 1} - ${endIndex} / ${total}` : "—"}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
          >
            <ChevronLeftIcon className="mr-1 h-3.5 w-3.5" /> 上一页
          </Button>
          <span className="min-w-[48px] text-center text-muted-foreground">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
          >
            下一页 <ChevronRightIcon className="ml-1 h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <span>每页</span>
          {[10, 20, 50].map((size) => (
            <button
              key={size}
              type="button"
              onClick={() => onPageSizeChange(size)}
              className={`h-7 rounded-md px-2 text-xs transition-colors ${
                pageSize === size
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              {size}
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}
