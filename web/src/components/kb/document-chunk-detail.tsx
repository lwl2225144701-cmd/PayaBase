"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeftIcon,
  Building2Icon,
  ChevronRightIcon,
  FileTextIcon,
  FlaskConicalIcon,
  HomeIcon,
  Loader2,
  RefreshCwIcon,
  SettingsIcon,
  SplitIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useKnowledgeBase, useDocumentChunks, useDocumentContent, useDocumentDetail } from "@/hooks/use-api";
import { DocumentSummaryCard } from "./document-summary-card";
import { DocumentPreview } from "./document-preview";
import { ChunkList } from "./chunk-list";
import type { Chunk } from "@/types";

const TABS = [
  { key: "documents", label: "文档", icon: FileTextIcon },
  { key: "pipeline", label: "流水线", icon: RefreshCwIcon },
  { key: "retrieval_test", label: "召回测试", icon: FlaskConicalIcon },
  { key: "settings", label: "设置", icon: SettingsIcon },
];

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
  const router = useRouter();
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

  // 搜索变化后重置到第一页，但 useEffect 会选中第一条
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
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* Left Sidebar — 复用文档列表页的左侧导航栏风格 */}
      <aside className="hidden w-[260px] shrink-0 flex-col border-r bg-muted/20 md:flex">
        <div className="border-b px-4 py-3">
          <Link href={backHref}>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-full justify-start px-2 text-sm text-muted-foreground hover:text-foreground"
            >
              <ArrowLeftIcon className="mr-2 h-4 w-4" />
              返回文档列表
            </Button>
          </Link>
        </div>

        <div className="border-b px-4 py-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border bg-blue-50 text-blue-600 border-blue-100 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800/50">
              <FileTextIcon className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-sm font-semibold leading-snug" title={kb?.name}>
                {kb?.name || "知识库"}
              </h2>
              {kb?.description && (
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground" title={kb.description}>
                  {kb.description}
                </p>
              )}
              <div className="mt-2 flex items-center gap-1.5">
                <Badge
                  variant={kb?.department_id ? "secondary" : "outline"}
                  className="rounded-md px-1.5 py-0 text-[10px] font-normal"
                >
                  <Building2Icon className="mr-0.5 h-2.5 w-2.5" />
                  {kb?.department_name || "公共"}
                </Badge>
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          <ul className="flex flex-col gap-0.5">
            {TABS.map((tab) => {
              const active = tab.key === "documents";
              return (
                <li key={tab.key}>
                  <button
                    type="button"
                    onClick={() => {
                      if (tab.key === "documents") {
                        router.push(backHref);
                      } else {
                        router.push(`/kb/${kbId}?tab=${tab.key}`);
                      }
                    }}
                    className={`flex h-9 w-full items-center justify-between rounded-md px-3 text-sm font-medium ${
                      active
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                  >
                    <span className="flex items-center gap-2.5">
                      <tab.icon className="h-4 w-4" />
                      {tab.label}
                    </span>
                    <ChevronRightIcon className="h-3.5 w-3.5 opacity-60" />
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
        {/* Breadcrumb + Title + Actions */}
        <div className="shrink-0 border-b px-6 py-4">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Link href="/kb" className="hover:text-foreground">
              <HomeIcon className="h-3.5 w-3.5" />
            </Link>
            <ChevronRightIcon className="h-3 w-3" />
            <Link href={`/kb/${kbId}`} className="hover:text-foreground hover:underline">
              {kb?.name || "知识库"}
            </Link>
            <ChevronRightIcon className="h-3 w-3" />
            <span className="truncate max-w-[200px]" title={document?.title}>
              {document?.title || "文档切片详情"}
            </span>
          </div>
          <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight">文档切片详情</h1>
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
      </main>
    </div>
  );
}
