'use client';

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  ArrowLeftIcon,
  Building2Icon,
  CheckCircle2Icon,
  FileIcon,
  FileTextIcon,
  Loader2,
  LockIcon,
  RefreshCwIcon,
  SearchIcon,
  TrashIcon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import { useDocuments, useUploadDocuments, useDeleteDocument, useReindexDocument, useIndexingStatus, useKnowledgeBase } from "@/hooks/use-api";

type StatusFilter = "all" | "ready" | "indexing" | "pending" | "error";

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "ready", label: "已完成" },
  { value: "indexing", label: "处理中" },
  { value: "error", label: "失败" },
];

const iconThemes = [
  "bg-blue-50 text-blue-600 border-blue-100 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800/50",
  "bg-indigo-50 text-indigo-600 border-indigo-100 dark:bg-indigo-950/50 dark:text-indigo-400 dark:border-indigo-800/50",
  "bg-rose-50 text-rose-600 border-rose-100 dark:bg-rose-950/50 dark:text-rose-400 dark:border-rose-800/50",
  "bg-violet-50 text-violet-600 border-violet-100 dark:bg-violet-950/50 dark:text-violet-400 dark:border-violet-800/50",
  "bg-emerald-50 text-emerald-600 border-emerald-100 dark:bg-emerald-950/50 dark:text-emerald-400 dark:border-emerald-800/50",
];

function fileTypeTheme(fileType: string): string {
  const t = (fileType || "").toLowerCase();
  if (t.includes("pdf")) return iconThemes[0];
  if (t.includes("doc")) return iconThemes[1];
  if (t.includes("sheet") || t.includes("xls") || t.includes("csv")) return iconThemes[2];
  if (t.includes("image") || t.includes("png") || t.includes("jpg") || t.includes("jpeg") || t.includes("webp") || t.includes("gif") || t.includes("bmp")) return iconThemes[3];
  if (t.includes("markdown") || t.includes("md")) return iconThemes[4];
  return iconThemes[0];
}

function formatBytes(n: number): string {
  if (!n && n !== 0) return "—";
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

function DocStatus({ kbId, doc }: { kbId: string; doc: any }) {
  const queryClient = useQueryClient();
  const isIndexing = doc.status === "indexing" || doc.status === "pending";

  const { data: statusData, isLoading, error } = useIndexingStatus(
    kbId,
    doc.id,
    isIndexing,
    () => {
      queryClient.invalidateQueries({ queryKey: ["documents", kbId] });
    }
  );

  const status: string = statusData?.status || doc.status;
  const progress: number = statusData?.progress || 0;
  const chunkCount: number = statusData?.chunk_count || doc.chunk_count || 0;
  const errorMessage: string | undefined = statusData?.error_message;

  if (isLoading && !statusData) {
    return (
      <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-xs font-normal">
        <Loader2 className="mr-1 h-3 w-3 animate-spin" /> 加载中
      </Badge>
    );
  }

  if (status === "ready") {
    return (
      <div className="flex items-center gap-2">
        <Badge
          variant="outline"
          className="rounded-md border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-normal text-emerald-700 dark:border-emerald-800/50 dark:bg-emerald-950/40 dark:text-emerald-400"
        >
          <CheckCircle2Icon className="mr-1 h-3 w-3" /> 已完成
        </Badge>
        {chunkCount > 0 && (
          <span className="text-xs text-muted-foreground">{chunkCount} chunks</span>
        )}
      </div>
    );
  }

  if (status === "indexing") {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="rounded-md border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-normal text-blue-700 dark:border-blue-800/50 dark:bg-blue-950/40 dark:text-blue-400"
          >
            <Loader2 className="mr-1 h-3 w-3 animate-spin" /> 索引中 {progress}%
          </Badge>
          {chunkCount > 0 && (
            <span className="text-xs text-muted-foreground">{chunkCount} chunks</span>
          )}
        </div>
        <Progress value={progress} className="h-1 w-28" />
      </div>
    );
  }

  if (status === "pending") {
    return (
      <div className="flex flex-col gap-1">
        <Badge
          variant="outline"
          className="rounded-md px-2 py-0.5 text-xs font-normal text-muted-foreground"
        >
          等待中
        </Badge>
        <Progress value={0} className="h-1 w-28" />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col gap-1">
        <Badge
          variant="outline"
          className="rounded-md border-red-200 bg-red-50 px-2 py-0.5 text-xs font-normal text-red-700 dark:border-red-800/50 dark:bg-red-950/40 dark:text-red-400"
        >
          失败
        </Badge>
        {errorMessage && (
          <span className="line-clamp-1 max-w-[220px] text-xs text-red-500" title={errorMessage}>
            {errorMessage}
          </span>
        )}
      </div>
    );
  }

  return (
    <Badge variant="outline" className="rounded-md px-2 py-0.5 text-xs font-normal">
      {status}
    </Badge>
  );
}

function DocRowSkeleton() {
  return (
    <div className="flex min-h-[88px] animate-pulse items-center gap-4 rounded-lg border border-border/60 bg-background/70 px-5 py-3">
      <div className="h-10 w-10 shrink-0 rounded-lg bg-muted" />
      <div className="flex-1 space-y-2">
        <div className="h-4 w-1/3 rounded bg-muted" />
        <div className="h-3 w-1/4 rounded bg-muted/70" />
      </div>
      <div className="h-6 w-20 rounded bg-muted/60" />
      <div className="h-8 w-8 rounded bg-muted/60" />
    </div>
  );
}

export default function DocListPage({ params }: { params: { id: string } }) {
  const kbId = params.id;
  const { data: docs, isLoading } = useDocuments(kbId);
  const { data: kb, isLoading: kbLoading } = useKnowledgeBase(kbId);
  const uploadDocs = useUploadDocuments();
  const deleteDoc = useDeleteDocument();
  const reindexDoc = useReindexDocument();
  const canManage = !!kb?.can_manage;
  const [files, setFiles] = useState<FileList | null>(null);
  const [searchKeyword, setSearchKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const normalizedKeyword = searchKeyword.trim().toLowerCase();

  const filtered = useMemo<any[]>(() => {
    if (!docs) return [];
    return (docs as any[]).filter((doc) => {
      if (statusFilter !== "all" && doc.status !== statusFilter) return false;
      if (!normalizedKeyword) return true;
      return [doc.title, doc.file_type]
        .filter(Boolean)
        .some((text) => String(text).toLowerCase().includes(normalizedKeyword));
    });
  }, [docs, statusFilter, normalizedKeyword]);

  const statusCounts = useMemo(() => {
    const list = (docs as any[]) || [];
    return {
      all: list.length,
      ready: list.filter((d) => d.status === "ready").length,
      indexing: list.filter((d) => d.status === "indexing" || d.status === "pending").length,
      error: list.filter((d) => d.status === "error").length,
    };
  }, [docs]);

  const handleUpload = async () => {
    if (!files || files.length === 0) return;
    if (!canManage) {
      alert("无权限上传文档");
      return;
    }
    try {
      const fileArray = Array.from(files);
      await uploadDocs.mutateAsync({ kbId, files: fileArray });
      setFiles(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (e: any) {
      alert("上传失败: " + (e.message || "未知错误"));
    }
  };

  const handlePickFiles = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFiles(e.target.files);
  };

  const handleCancelFiles = () => {
    setFiles(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDelete = async (docId: string) => {
    if (!canManage) {
      alert("无权限删除该文档");
      return;
    }
    if (!confirm("确定删除该文档？该操作会同时删除其索引分块。")) return;
    try {
      await deleteDoc.mutateAsync({ kbId, docId });
    } catch (e: any) {
      alert("删除失败: " + (e.message || "未知错误"));
    }
  };

  const handleReindex = async (docId: string) => {
    if (!canManage) {
      alert("无权限重新索引该文档");
      return;
    }
    try {
      await reindexDoc.mutateAsync({ kbId, docId });
    } catch (e: any) {
      alert("重新索引失败: " + (e.message || "未知错误"));
    }
  };

  const loading = isLoading || kbLoading;
  const hasNoDocs = !loading && (!docs || docs.length === 0);
  const showEmptySearch =
    !loading &&
    !hasNoDocs &&
    normalizedKeyword.length > 0 &&
    filtered.length === 0;
  const showEmptyFilter =
    !loading &&
    !hasNoDocs &&
    normalizedKeyword.length === 0 &&
    statusFilter !== "all" &&
    filtered.length === 0;

  if (loading) {
    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(800px_circle_at_0%_0%,rgba(99,102,241,0.06),transparent_55%)]">
        <div className="relative z-30 shrink-0 border-b bg-background/50 px-6 pb-4 pt-5 backdrop-blur-sm">
          <div className="flex items-center gap-4">
            <Link href="/kb">
              <Button variant="ghost" size="sm" className="h-9">
                <ArrowLeftIcon className="mr-2 h-4 w-4" /> 返回
              </Button>
            </Link>
            <div className="space-y-2">
              <div className="h-6 w-40 animate-pulse rounded bg-muted" />
              <div className="h-3.5 w-56 animate-pulse rounded bg-muted/70" />
            </div>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="flex flex-col gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <DocRowSkeleton key={i} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(800px_circle_at_0%_0%,rgba(99,102,241,0.06),transparent_55%)]">
      {/* ======== Header ======== */}
      <div className="relative z-30 shrink-0 border-b bg-background/50 px-6 pb-4 pt-5 backdrop-blur-sm">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <Link href="/kb" className="shrink-0">
              <Button variant="ghost" size="icon" className="mt-0.5 h-9 w-9" title="返回知识库">
                <ArrowLeftIcon className="h-4 w-4" />
              </Button>
            </Link>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-2xl font-semibold tracking-tight">{kb?.name || "知识库"}</h1>
                <Badge
                  variant={kb?.department_id ? "secondary" : "outline"}
                  className="rounded-md px-2 py-0.5 text-xs font-normal"
                >
                  <Building2Icon className="mr-1 h-3 w-3" />
                  {kb?.department_name || "公共"}
                </Badge>
                <span className="rounded-md bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground">
                  {kb?.doc_count ?? 0} 个文档
                </span>
                {!canManage && (
                  <span className="rounded-md bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground">
                    <LockIcon className="mr-0.5 inline h-3 w-3" /> 只读
                  </span>
                )}
              </div>
              {kb?.description && (
                <p className="mt-1.5 line-clamp-1 text-sm text-muted-foreground">
                  {kb.description}
                </p>
              )}
            </div>
          </div>

          {canManage && (
            <div className="flex shrink-0 items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.doc,.md,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.gif,.webp,.bmp"
                multiple
                onChange={handleFileChange}
                className="hidden"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={handlePickFiles}
                className="h-10 rounded-lg bg-background/70 px-3 text-sm shadow-sm"
              >
                <UploadIcon className="mr-2 h-4 w-4" />
                选择文件
              </Button>
              {files && files.length > 0 && (
                <>
                  <div className="hidden h-10 items-center gap-2 rounded-lg border border-dashed border-primary/30 bg-primary/5 px-3 text-xs text-primary sm:flex">
                    <FileTextIcon className="h-3.5 w-3.5" />
                    <span>已选 {files.length} 个文件</span>
                    <button
                      type="button"
                      onClick={handleCancelFiles}
                      className="ml-1 text-muted-foreground hover:text-foreground"
                      title="清除选择"
                    >
                      <XIcon className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <Button
                    onClick={handleUpload}
                    disabled={uploadDocs.isPending}
                    className="h-10 rounded-lg bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] px-4 text-sm text-white shadow-sm hover:opacity-90"
                  >
                    {uploadDocs.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 上传中…
                      </>
                    ) : (
                      <>
                        <UploadIcon className="mr-2 h-4 w-4" /> 立即上传
                      </>
                    )}
                  </Button>
                </>
              )}
            </div>
          )}
        </div>

        {/* ======== Toolbar ======== */}
        <div className="mt-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            {STATUS_OPTIONS.map((opt) => {
              const count = statusCounts[opt.value as keyof typeof statusCounts] ?? 0;
              const active = statusFilter === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setStatusFilter(opt.value)}
                  className={`h-9 rounded-lg px-3.5 text-sm font-medium transition-colors ${
                    active
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  {opt.label}
                  <span className="ml-1.5 text-xs opacity-60">{count}</span>
                </button>
              );
            })}
          </div>

          <div className="relative min-w-0 md:w-[280px]">
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              placeholder="搜索文档名…"
              className="h-9 w-full min-w-0 rounded-lg border border-input bg-background/70 pl-9 pr-8 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
            />
            {searchKeyword && (
              <button
                type="button"
                onClick={() => setSearchKeyword("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                title="清空"
              >
                <XIcon className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ======== Body ======== */}
      <div className="relative z-0 min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {/* Empty: no docs at all & can manage */}
        {hasNoDocs && canManage && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <FileTextIcon className="h-8 w-8" />
            </div>
            <h2 className="mt-5 text-lg font-medium">还没有任何文档</h2>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">
              支持 PDF / Word / Markdown / Excel / 图片 等格式。上传后会自动进行分块与索引。
            </p>
            <Button
              onClick={handlePickFiles}
              className="mt-5 h-10 rounded-lg bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] px-5 text-sm text-white shadow-sm hover:opacity-90"
            >
              <UploadIcon className="mr-2 h-4 w-4" />
              选择文件上传
            </Button>
          </div>
        )}

        {/* Empty: no docs & cannot manage */}
        {hasNoDocs && !canManage && (
          <div className="flex flex-col items-center justify-center py-20 text-center text-sm text-muted-foreground">
            暂无可查看文档
          </div>
        )}

        {/* Empty: search has results but filtered to nothing */}
        {showEmptySearch && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-sm text-muted-foreground">没有找到匹配的文档</p>
            <button
              type="button"
              onClick={() => setSearchKeyword("")}
              className="mt-3 text-sm text-primary hover:underline"
            >
              清空搜索词
            </button>
          </div>
        )}

        {/* Empty: status filter returns nothing */}
        {showEmptyFilter && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-sm text-muted-foreground">该状态下暂无文档</p>
            <button
              type="button"
              onClick={() => setStatusFilter("all")}
              className="mt-3 text-sm text-primary hover:underline"
            >
              查看全部
            </button>
          </div>
        )}

        {/* Doc list */}
        {!hasNoDocs && !showEmptySearch && !showEmptyFilter && filtered.length > 0 && (
          <div className="flex flex-col gap-3">
            {filtered.map((doc: any) => (
              <Card
                key={doc.id}
                className="group flex min-h-[88px] flex-row items-stretch overflow-hidden border-border/60 bg-background/80 p-0 shadow-sm transition-shadow hover:shadow-md"
              >
                <div className="flex shrink-0 items-center pl-5 pr-4">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-lg border ${fileTypeTheme(doc.file_type)}`}>
                    <FileIcon className="h-4 w-4" />
                  </div>
                </div>
                <div className="flex min-w-0 flex-1 flex-col justify-center py-3 pr-4">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm font-semibold leading-snug" title={doc.title}>
                      {doc.title}
                    </span>
                    <span className="shrink-0 rounded-md bg-muted/50 px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      {(doc.file_type || "file").split("/").pop()?.toUpperCase() || "FILE"}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span>上传 {formatDate(doc.created_at)}</span>
                    <span>·</span>
                    <span>{formatBytes(doc.file_size)}</span>
                    {doc.indexed_at && (
                      <>
                        <span>·</span>
                        <span>索引 {formatDate(doc.indexed_at)}</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center px-5">
                  <DocStatus kbId={kbId} doc={doc} />
                </div>
                {canManage && (
                  <div className="flex shrink-0 items-center gap-1 border-l border-border/80 pl-3 pr-3">
                    {(doc.status === "pending" || doc.status === "error") && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground/60 transition-colors hover:bg-primary/10 hover:text-primary"
                        onClick={() => handleReindex(doc.id)}
                        disabled={reindexDoc.isPending}
                        title="重新索引"
                      >
                        <RefreshCwIcon className="h-4 w-4" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground/60 transition-colors hover:bg-destructive/10 hover:text-destructive"
                      onClick={() => handleDelete(doc.id)}
                      title="删除文档"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
