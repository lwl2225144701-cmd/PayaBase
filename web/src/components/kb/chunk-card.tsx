"use client";

import { useState } from "react";
import { ChevronDownIcon, ChevronUpIcon, FlaskConicalIcon, InfoIcon, PencilIcon } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ChunkMetadata } from "./chunk-metadata";
import type { Chunk } from "@/types";

interface ChunkCardProps {
  chunk: Chunk;
  index: number;
  isSelected: boolean;
  onSelect: (chunk: Chunk) => void;
  kbId: string;
}

function statusBadge(status: string) {
  if (status === "indexed") {
    return (
      <Badge
        variant="outline"
        className="rounded-md border-emerald-200 bg-emerald-50 px-1.5 py-0 text-[10px] font-normal text-emerald-700 dark:border-emerald-800/50 dark:bg-emerald-950/40 dark:text-emerald-400"
      >
        已向量化
      </Badge>
    );
  }
  if (status === "error") {
    return (
      <Badge
        variant="outline"
        className="rounded-md border-red-200 bg-red-50 px-1.5 py-0 text-[10px] font-normal text-red-700 dark:border-red-800/50 dark:bg-red-950/40 dark:text-red-400"
      >
        异常
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="rounded-md px-1.5 py-0 text-[10px] font-normal text-muted-foreground">
      待处理
    </Badge>
  );
}

export function ChunkCard({ chunk, index, isSelected, onSelect, kbId }: ChunkCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [showMetadata, setShowMetadata] = useState(false);
  const previewLength = 180;
  const needsExpand = chunk.content.length > previewLength;
  const displayContent = expanded ? chunk.content : chunk.content.slice(0, previewLength) + (needsExpand ? "…" : "");

  return (
    <div
      className={`rounded-lg border bg-background p-4 transition-colors ${
        isSelected
          ? "border-primary/40 bg-primary/[0.03] ring-1 ring-primary/20"
          : "border-border/60 hover:border-primary/30 hover:bg-muted/20"
      }`}
      onClick={() => onSelect(chunk)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect(chunk);
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-semibold text-primary">
            {String(index + 1).padStart(3, "0")}
          </span>
          <span className="truncate text-xs text-muted-foreground" title={chunk.chunk_id}>
            {chunk.chunk_id}
          </span>
        </div>
        {statusBadge(chunk.vector_status)}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>字符：{chunk.character_count ?? "—"}</span>
        <span>Token：{chunk.token_count ?? "—"}</span>
        <span>页码：{chunk.page_number ?? "—"}</span>
        {chunk.section_title && (
          <span className="truncate max-w-[160px]" title={chunk.section_title}>
            {chunk.section_title}
          </span>
        )}
      </div>

      <div className="mt-3 text-sm leading-6 text-foreground">
        {displayContent}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          {needsExpand && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
              onClick={(e) => {
                e.stopPropagation();
                setExpanded((v) => !v);
              }}
            >
              {expanded ? (
                <>
                  <ChevronUpIcon className="mr-1 h-3.5 w-3.5" /> 收起
                </>
              ) : (
                <>
                  <ChevronDownIcon className="mr-1 h-3.5 w-3.5" /> 展开
                </>
              )}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation();
              setShowMetadata((v) => !v);
            }}
          >
            <InfoIcon className="mr-1 h-3.5 w-3.5" /> 查看元数据
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Link
            href={`/kb/${kbId}?tab=retrieval_test&document_id=${encodeURIComponent(chunk.document_id)}&chunk_id=${encodeURIComponent(chunk.chunk_id)}`}
            onClick={(e) => e.stopPropagation()}
          >
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground">
              <FlaskConicalIcon className="mr-1 h-3.5 w-3.5" /> 召回测试
            </Button>
          </Link>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation();
              alert("编辑切片暂未开放");
            }}
          >
            <PencilIcon className="mr-1 h-3.5 w-3.5" /> 编辑
          </Button>
        </div>
      </div>

      {showMetadata && <ChunkMetadata chunk={chunk} />}
    </div>
  );
}
