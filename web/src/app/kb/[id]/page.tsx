'use client';

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  ArrowLeftIcon,
  ArrowUpDownIcon,
  Building2Icon,
  CheckCircle2Icon,
  ChevronLeftIcon,
  ChevronRightIcon,
  FileIcon,
  FileTextIcon,
  FlaskConicalIcon,
  InfoIcon,
  Loader2,
  LockIcon,
  MoreHorizontalIcon,
  RefreshCwIcon,
  SearchIcon,
  SettingsIcon,
  TrashIcon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import { useDocuments, useUploadDocuments, useDeleteDocument, useReindexDocument, useIndexingStatus, useKnowledgeBase } from "@/hooks/use-api";

type StatusFilter = "all" | "ready" | "indexing" | "pending" | "error";
type SortKey = "created_desc" | "created_asc" | "name_asc" | "name_desc";

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "ready", label: "已完成" },
  { value: "indexing", label: "处理中" },
  { value: "error", label: "失败" },
];

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "created_desc", label: "上传时间 (新→旧)" },
  { value: "created_asc", label: "上传时间 (旧→新)" },
  { value: "name_asc", label: "名称 (A→Z)" },
  { value: "name_desc", label: "名称 (Z→A)" },
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
      <div className="flex items-center gap-2">
        <Badge
          variant="outline"
          className="rounded-md border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-normal text-blue-700 dark:border-blue-800/50 dark:bg-blue-950/40 dark:text-blue-400"
        >
          <Loader2 className="mr-1 h-3 w-3 animate-spin" /> 索引中 {progress}%
        </Badge>
        <Progress value={progress} className="h-1 w-16" />
      </div>
    );
  }

  if (status === "pending") {
    return (
      <div className="flex items-center gap-2">
        <Badge
          variant="outline"
          className="rounded-md px-2 py-0.5 text-xs font-normal text-muted-foreground"
        >
          等待中
        </Badge>
        <Progress value={0} className="h-1 w-16" />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col gap-0.5">
        <Badge
          variant="outline"
          className="rounded-md border-red-200 bg-red-50 px-2 py-0.5 text-xs font-normal text-red-700 dark:border-red-800/50 dark:bg-red-950/40 dark:text-red-400"
        >
          失败
        </Badge>
        {errorMessage && (
          <span className="line-clamp-1 max-w-[180px] text-[11px] text-red-500" title={errorMessage}>
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

function TableRowSkeleton() {
  return (
    <tr className="border-b border-border/60 last:border-b-0">
      <td className="px-4 py-3">
        <div className="h-4 w-4 animate-pulse rounded bg-muted" />
      </td>
      <td className="px-4 py-3">
        <div className="h-3.5 w-6 animate-pulse rounded bg-muted" />
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 animate-pulse rounded-md bg-muted" />
          <div className="h-4 w-40 animate-pulse rounded bg-muted" />
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-12 animate-pulse rounded bg-muted" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-16 animate-pulse rounded bg-muted" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-8 animate-pulse rounded bg-muted" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-28 animate-pulse rounded bg-muted" />
      </td>
      <td className="px-4 py-3">
        <div className="h-5 w-20 animate-pulse rounded bg-muted" />
      </td>
      <td className="px-4 py-3">
        <div className="h-7 w-7 animate-pulse rounded bg-muted" />
      </td>
    </tr>
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
  const [sortKey, setSortKey] = useState<SortKey>("created_desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const normalizedKeyword = searchKeyword.trim().toLowerCase();

  const statusCounts = useMemo(() => {
    const list = (docs as any[]) || [];
    return {
      all: list.length,
      ready: list.filter((d) => d.status === "ready").length,
      indexing: list.filter((d) => d.status === "indexing" || d.status === "pending").length,
      error: list.filter((d) => d.status === "error").length,
    };
  }, [docs]);

  const filtered = useMemo<any[]>(() => {
    if (!docs) return [];
    const base = (docs as any[]).filter((doc) => {
      if (statusFilter !== "all" && doc.status !== statusFilter) return false;
      if (!normalizedKeyword) return true;
      return [doc.title, doc.file_type]
        .filter(Boolean)
        .some((text: any) => String(text).toLowerCase().includes(normalizedKeyword));
    });
    const sorted = [...base];
    sorted.sort((a, b) => {
      switch (sortKey) {
        case "created_asc":
          return String(a.created_at || "").localeCompare(String(b.created_at || ""));
        case "name_asc":
          return String(a.title || "").localeCompare(String(b.title || ""));
        case "name_desc":
          return String(b.title || "").localeCompare(String(a.title || ""));
        case "created_desc":
        default:
          return String(b.created_at || "").localeCompare(String(a.created_at || ""));
      }
    });
    return sorted;
  }, [docs, statusFilter, normalizedKeyword, sortKey]);

  const totalItems = filtered.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const startIndex = (page - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, totalItems);
  const pagedDocs = useMemo<any[]>(
    () => filtered.slice(startIndex, startIndex + pageSize),
    [filtered, startIndex, pageSize]
  );

  // 搜索 / 筛选 / 排序 / 页大小 变化时, 重置到第 1 页
  useEffect(() => {
    setPage(1);
  }, [normalizedKeyword, statusFilter, sortKey, pageSize]);

  // 越界保护: 数据被筛掉后 page 超出 totalPages 时, 拉回最后一页
  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

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

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* ======== Left Sidebar ======== */}
      <aside className="hidden w-[260px] shrink-0 flex-col border-r bg-muted/20 md:flex">
        <div className="border-b px-4 py-3">
          <Link href="/kb">
            <Button variant="ghost" size="sm" className="h-8 w-full justify-start px-2 text-sm text-muted-foreground hover:text-foreground">
              <ArrowLeftIcon className="mr-2 h-4 w-4" />
              知识库列表
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
                {!canManage && (
                  <Badge variant="outline" className="rounded-md px-1.5 py-0 text-[10px] font-normal text-muted-foreground">
                    <LockIcon className="mr-0.5 h-2.5 w-2.5" /> 只读
                  </Badge>
                )}
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          <ul className="flex flex-col gap-0.5">
            <li>
              <button
                type="button"
                className="flex h-9 w-full items-center justify-between rounded-md bg-primary/10 px-3 text-sm font-medium text-primary"
              >
                <span className="flex items-center gap-2.5">
                  <FileTextIcon className="h-4 w-4" />
                  文档
                </span>
                <ChevronRightIcon className="h-3.5 w-3.5 opacity-60" />
              </button>
            </li>
            <li>
              <button
                type="button"
                disabled
                className="flex h-9 w-full items-center justify-between rounded-md px-3 text-sm text-muted-foreground/60"
                title="即将推出"
              >
                <span className="flex items-center gap-2.5">
                  <RefreshCwIcon className="h-4 w-4" />
                  流水线
                </span>
                <span className="text-[10px] uppercase tracking-wide opacity-70">soon</span>
              </button>
            </li>
            <li>
              <button
                type="button"
                disabled
                className="flex h-9 w-full items-center justify-between rounded-md px-3 text-sm text-muted-foreground/60"
                title="即将推出"
              >
                <span className="flex items-center gap-2.5">
                  <FlaskConicalIcon className="h-4 w-4" />
                  召回测试
                </span>
                <span className="text-[10px] uppercase tracking-wide opacity-70">soon</span>
              </button>
            </li>
            <li>
              <button
                type="button"
                disabled
                className="flex h-9 w-full items-center justify-between rounded-md px-3 text-sm text-muted-foreground/60"
                title="即将推出"
              >
                <span className="flex items-center gap-2.5">
                  <SettingsIcon className="h-4 w-4" />
                  设置
                </span>
                <span className="text-[10px] uppercase tracking-wide opacity-70">soon</span>
              </button>
            </li>
          </ul>
        </nav>

        <div className="border-t px-4 py-3 text-xs text-muted-foreground">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md bg-background/60 px-2.5 py-2">
              <div className="text-[10px] uppercase tracking-wide opacity-70">文档数</div>
              <div className="mt-0.5 text-sm font-medium text-foreground">
                {kb?.doc_count ?? (docs as any[])?.length ?? 0}
              </div>
            </div>
            <div className="rounded-md bg-background/60 px-2.5 py-2">
              <div className="text-[10px] uppercase tracking-wide opacity-70">关联应用</div>
              <div className="mt-0.5 text-sm font-medium text-foreground">0</div>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled
            className="mt-3 h-8 w-full text-xs"
            title="即将推出"
          >
            <InfoIcon className="mr-1.5 h-3.5 w-3.5" />
            访问 API
          </Button>
        </div>
      </aside>

      {/* ======== Right Main ======== */}
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
        {/* Header */}
        <div className="relative z-30 shrink-0 border-b bg-background/70 px-6 pb-4 pt-5 backdrop-blur-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight">文档</h1>
              <p className="mt-1.5 text-sm text-muted-foreground">
                知识库的所有文件都会在这里显示，可用于 AI 问答检索。
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled
                className="h-9 text-sm"
                title="即将推出"
              >
                <InfoIcon className="mr-1.5 h-4 w-4" />
                元数据
              </Button>
              <Button
                size="sm"
                onClick={canManage ? handlePickFiles : undefined}
                disabled={!canManage || uploadDocs.isPending}
                className="h-9 rounded-lg bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] px-4 text-sm text-white shadow-sm hover:opacity-90 disabled:opacity-50"
                title={canManage ? "选择并上传文件" : "无权限上传"}
              >
                {uploadDocs.isPending ? (
                  <>
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    上传中…
                  </>
                ) : (
                  <>
                    <UploadIcon className="mr-1.5 h-4 w-4" />
                    添加文件
                  </>
                )}
              </Button>
            </div>
          </div>

          {/* Selected files preview */}
          {canManage && files && files.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-primary/30 bg-primary/5 px-3 py-2 text-xs">
              <FileTextIcon className="h-3.5 w-3.5 text-primary" />
              <span className="text-primary">已选 {files.length} 个文件</span>
              <button
                type="button"
                onClick={handleCancelFiles}
                className="ml-1 text-muted-foreground hover:text-foreground"
                title="清除选择"
              >
                <XIcon className="h-3.5 w-3.5" />
              </button>
              <Button
                onClick={handleUpload}
                disabled={uploadDocs.isPending}
                className="ml-auto h-7 rounded-md bg-primary px-3 text-xs text-primary-foreground hover:opacity-90"
              >
                {uploadDocs.isPending ? "上传中…" : "立即上传"}
              </Button>
            </div>
          )}

          {/* Toolbar */}
          <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              {STATUS_OPTIONS.map((opt) => {
                const count = statusCounts[opt.value as keyof typeof statusCounts] ?? 0;
                const active = statusFilter === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setStatusFilter(opt.value)}
                    className={`h-8 rounded-md px-3 text-sm font-medium transition-colors ${
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
            <div className="flex items-center gap-2">
              <div className="relative min-w-0 md:w-[240px]">
                <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  value={searchKeyword}
                  onChange={(e) => setSearchKeyword(e.target.value)}
                  placeholder="搜索"
                  className="h-8 w-full min-w-0 rounded-md border border-input bg-background/70 pl-9 pr-8 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
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
              <div className="relative">
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                  className="h-8 appearance-none rounded-md border border-input bg-background/70 pl-3 pr-8 text-sm shadow-sm outline-none transition-colors focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
                  title="排序"
                >
                  {SORT_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <ArrowUpDownIcon className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              </div>
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="relative z-0 min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {/* Hidden file input (mounted once for the right area) */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.doc,.md,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.gif,.webp,.bmp"
            multiple
            onChange={handleFileChange}
            className="hidden"
          />

          {/* Loading skeleton table */}
          {loading && (
            <div className="overflow-hidden rounded-lg border bg-background">
              <div className="overflow-x-auto">
                <table className="min-w-[960px] w-full text-sm">
                  <thead>
                  <tr className="border-b border-border/80 bg-muted/30 text-left text-xs font-medium text-muted-foreground">
                    <th className="w-10 px-4 py-2.5">
                      <div className="h-3.5 w-3.5 rounded bg-muted" />
                    </th>
                    <th className="w-12 px-4 py-2.5">#</th>
                    <th className="px-4 py-2.5">名称</th>
                    <th className="px-4 py-2.5">分段</th>
                    <th className="px-4 py-2.5">大小</th>
                    <th className="px-4 py-2.5">召回次数</th>
                    <th className="px-4 py-2.5">上传时间</th>
                    <th className="px-4 py-2.5">状态</th>
                    <th className="w-16 px-4 py-2.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {Array.from({ length: 8 }).map((_, i) => (
                    <TableRowSkeleton key={i} />
                  ))}
                </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Empty: no docs & can manage */}
          {!loading && hasNoDocs && canManage && (
            <div className="flex flex-col items-center justify-center py-24 text-center">
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
                添加文件
              </Button>
            </div>
          )}

          {/* Empty: no docs & cannot manage */}
          {!loading && hasNoDocs && !canManage && (
            <div className="flex flex-col items-center justify-center py-24 text-center text-sm text-muted-foreground">
              暂无可查看文档
            </div>
          )}

          {/* Empty: search has results but filtered to nothing */}
          {!loading && showEmptySearch && (
            <div className="flex flex-col items-center justify-center py-24 text-center">
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
          {!loading && showEmptyFilter && (
            <div className="flex flex-col items-center justify-center py-24 text-center">
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

          {/* Doc table */}
          {!loading && !hasNoDocs && !showEmptySearch && !showEmptyFilter && filtered.length > 0 && (
            <div className="overflow-hidden rounded-lg border bg-background">
              <div className="overflow-x-auto">
                <table className="min-w-[960px] w-full text-sm">
                  <thead>
                  <tr className="border-b border-border/80 bg-muted/30 text-left text-xs font-medium text-muted-foreground">
                    <th className="w-10 px-4 py-2.5">
                      <input
                        type="checkbox"
                        disabled
                        className="h-3.5 w-3.5 cursor-not-allowed rounded border-input"
                        title="批量操作 (即将推出)"
                      />
                    </th>
                    <th className="w-12 px-4 py-2.5">#</th>
                    <th className="px-4 py-2.5">名称</th>
                    <th className="px-4 py-2.5">分段</th>
                    <th className="px-4 py-2.5">大小</th>
                    <th className="px-4 py-2.5">召回次数</th>
                    <th className="px-4 py-2.5">上传时间</th>
                    <th className="px-4 py-2.5">状态</th>
                    <th className="w-24 px-4 py-2.5 text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedDocs.map((doc: any, idx: number) => (
                    <tr
                      key={doc.id}
                      className="group border-b border-border/60 transition-colors last:border-b-0 hover:bg-muted/30"
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          disabled
                          className="h-3.5 w-3.5 cursor-not-allowed rounded border-input"
                          title="批量操作 (即将推出)"
                        />
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {(page - 1) * pageSize + idx + 1}
                      </td>
                      <td className="max-w-[280px] px-4 py-3">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border ${fileTypeTheme(doc.file_type)}`}>
                            <FileIcon className="h-3.5 w-3.5" />
                          </div>
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium leading-snug" title={doc.title}>
                              {doc.title}
                            </div>
                            <div className="mt-0.5 text-[11px] uppercase tracking-wide text-muted-foreground/80">
                              {(doc.file_type || "file").split("/").pop()?.toUpperCase() || "FILE"}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="rounded-md bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground">通用</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                        {formatBytes(doc.file_size)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                        {doc.hit_count !== undefined && doc.hit_count !== null ? doc.hit_count : "—"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                        {formatDate(doc.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <DocStatus kbId={kbId} doc={doc} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          {(doc.status === "pending" || doc.status === "error") && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground/60 transition-colors hover:bg-primary/10 hover:text-primary"
                              onClick={() => handleReindex(doc.id)}
                              disabled={reindexDoc.isPending}
                              title="重新索引"
                            >
                              <RefreshCwIcon className="h-3.5 w-3.5" />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground/60 transition-colors hover:bg-destructive/10 hover:text-destructive"
                            onClick={() => handleDelete(doc.id)}
                            title="删除文档"
                          >
                            <TrashIcon className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled
                            className="h-7 w-7 text-muted-foreground/30"
                            title="更多 (即将推出)"
                          >
                            <MoreHorizontalIcon className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-3 text-sm">
                <div className="text-xs text-muted-foreground">
                  共 {totalItems} 个文档
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                  >
                    <ChevronLeftIcon className="mr-1 h-3.5 w-3.5" />
                    上一页
                  </Button>
                  <span className="min-w-[60px] text-center text-xs text-muted-foreground">
                    {page} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                  >
                    下一页
                    <ChevronRightIcon className="ml-1 h-3.5 w-3.5" />
                  </Button>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span>每页</span>
                  {[10, 25, 50].map((size) => (
                    <button
                      key={size}
                      type="button"
                      onClick={() => setPageSize(size)}
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
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
