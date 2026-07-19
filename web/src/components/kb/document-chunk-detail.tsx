"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeftIcon,
  ChevronRightIcon,
  Loader2,
  RefreshCwIcon,
  SplitIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useKnowledgeBase, useDocumentChunks, useDocumentContent, useDocumentDetail } from "@/hooks/use-api";
import { DocumentSummaryCard } from "./document-summary-card";
import { DocumentPreview } from "./document-preview";
import { ChunkList } from "./chunk-list";
import type { Chunk } from "@/types";

interface DocumentChunkDetailProps {
  kbId: string;
  documentId: string;
  listParams?: {
    page?: string;
    q?: string;
    status?: string;
    sort?: string;
  };
}

export function DocumentChunkDetail({ kbId, documentId, listParams }: DocumentChunkDetailProps) {
  const { data: kb, isLoading: kbLoading } = useKnowledgeBase(kbId);
  const { data: document, isLoading: docLoading } = useDocumentDetail(kbId, documentId);
  const { data: content, isLoading: contentLoading, error: contentError } = useDocumentContent(kbId, documentId);

  const [keyword, setKeyword] = useState("");
  const [previewKeyword, setPreviewKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selectedChunk, setSelectedChunk] = useState<Chunk | undefined>();

  const normalizedKeyword = keyword.trim().toLowerCase();

  const { data: chunksPage, isLoading: chunksLoading, error: chunksError } = useDocumentChunks(
    kbId,
    documentId,
    {
      page,
      pageSize,
      keyword: normalizedKeyword,
      status: statusFilter,
    }
  );

  const chunks = useMemo(() => chunksPage?.items ?? [], [chunksPage?.items]);
  const total = chunksPage?.total || 0;

  // 初始化默认选中第一条切片
  useEffect(() => {
    if (!selectedChunk && chunks.length > 0) {
      setSelectedChunk(chunks[0]);
    }
  }, [chunks, selectedChunk]);

  // 分页/筛选/搜索变化后，清除选中或选中当前页第一条
  // 仅依赖分页相关状态，刻意不将 chunks 纳入依赖（避免切片数据刷新时反复重选）
  useEffect(() => {
    if (chunks.length > 0) {
      setSelectedChunk(chunks[0]);
    } else {
      setSelectedChunk(undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, statusFilter, pageSize]);

  // 搜索变化后重置到第一页
  useEffect(() => {
    setPage(1);
  }, [keyword, statusFilter]);

  const backHref = useMemo(() => {
    const query = new URLSearchParams();
    if (listParams?.page) query.set("page", listParams.page);
    if (listParams?.q) query.set("q", listParams.q);
    if (listParams?.status) query.set("status", listParams.status);
    if (listParams?.sort) query.set("sort", listParams.sort);
    const qs = query.toString();
    return `/kb/${kbId}${qs ? `?${qs}` : ""}`;
  }, [kbId, listParams]);

  const loading = kbLoading || docLoading || contentLoading || chunksLoading;

  const handleRechunk = () => {
    if (confirm("重新切分会重新处理当前文档，是否继续？")) {
      alert("重新切分功能待接入");
    }
  };

  const handleReindex = () => {
    if (confirm("重新向量化会重新生成文档向量，是否继续？")) {
      alert("重新向量化功能待接入");
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      {/* Header: Title + Actions */}
      <div className="shrink-0 border-b px-6 py-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Link href={`/kb/${kbId}`} className="hover:text-foreground hover:underline">
                {kb?.name || "知识库"}
              </Link>
              <ChevronRightIcon className="h-3 w-3" />
              <Link href={backHref} className="hover:text-foreground hover:underline">
                文档
              </Link>
              <ChevronRightIcon className="h-3 w-3" />
              <span className="truncate max-w-[200px]" title={document?.title}>
                {document?.title || "文档切片详情"}
              </span>
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">文档切片详情</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              查看原文内容、切片结果及元数据，用于分析和优化文档分段效果。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Link href={backHref}>
              <Button variant="outline" size="sm" className="h-9 text-sm">
                <ArrowLeftIcon className="mr-1.5 h-4 w-4" />
                返回文档列表
              </Button>
            </Link>
            <Button
              variant="outline"
              size="sm"
              className="h-9 text-sm"
              onClick={handleRechunk}
            >
              <SplitIcon className="mr-1.5 h-4 w-4" />
              重新切分
            </Button>
            <Button
              size="sm"
              className="h-9 rounded-lg bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] px-4 text-sm text-white shadow-sm hover:opacity-90"
              onClick={handleReindex}
            >
              <RefreshCwIcon className="mr-1.5 h-4 w-4" />
              重新向量化
            </Button>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
        {loading && !document && !chunks.length ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
          </div>
        ) : (
          <>
            <DocumentSummaryCard document={document} isLoading={docLoading} />
            <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[1.6fr_1fr]">
              <DocumentPreview
                content={content}
                selectedChunk={selectedChunk}
                keyword={previewKeyword}
                onKeywordChange={setPreviewKeyword}
                isLoading={contentLoading}
                error={contentError}
              />
              <ChunkList
                chunks={chunks}
                total={total}
                page={page}
                pageSize={pageSize}
                keyword={keyword}
                statusFilter={statusFilter}
                selectedChunkId={selectedChunk?.chunk_id}
                onKeywordChange={setKeyword}
                onStatusFilterChange={setStatusFilter}
                onPageChange={setPage}
                onPageSizeChange={setPageSize}
                onSelectChunk={setSelectedChunk}
                kbId={kbId}
                isLoading={chunksLoading}
                error={chunksError}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
