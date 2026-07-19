'use client';

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
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
  CopyIcon,
  FileIcon,
  FileTextIcon,
  FlaskConicalIcon,
  HistoryIcon,
  InfoIcon,
  Loader2,
  LockIcon,
  MessageSquareIcon,
  MoreHorizontalIcon,
  RefreshCwIcon,
  SearchIcon,
  SettingsIcon,
  TrashIcon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import { useDocumentsPage, useUploadDocuments, useDeleteDocument, useReindexDocument, useIndexingStatus, useKnowledgeBase, useRetrievalTest, useUpdateKnowledgeBase, useDeleteKnowledgeBase } from "@/hooks/use-api";

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

function DocStatus({ kbId, doc, detailHref }: { kbId: string; doc: any; detailHref?: string }) {
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

  const chunkCountLink = chunkCount > 0 && detailHref ? (
    <Link href={detailHref} className="text-xs text-muted-foreground hover:text-primary hover:underline">
      {chunkCount} chunks
    </Link>
  ) : chunkCount > 0 ? (
    <span className="text-xs text-muted-foreground">{chunkCount} chunks</span>
  ) : null;

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
        {chunkCountLink}
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
  const searchParams = useSearchParams();
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
  const [activeTab, setActiveTab] = useState<"documents" | "pipeline" | "retrieval_test" | "settings">("documents");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const initializedFromQuery = useRef(false);

  // 从 URL query 初始化列表状态，保证从详情页返回时状态不丢失
  useEffect(() => {
    if (initializedFromQuery.current) return;
    initializedFromQuery.current = true;
    const q = searchParams.get("q") || "";
    const status = (searchParams.get("status") as StatusFilter) || "all";
    const sort = (searchParams.get("sort") as SortKey) || "created_desc";
    const p = Number(searchParams.get("page"));
    const ps = Number(searchParams.get("pageSize"));
    if (q) setSearchKeyword(q);
    if (status && status !== "all") setStatusFilter(status);
    if (sort && sort !== "created_desc") setSortKey(sort);
    if (p > 0) setPage(p);
    if (ps > 0) setPageSize(ps);
  }, [searchParams]);

  const normalizedKeyword = searchKeyword.trim().toLowerCase();

  // ====== 服务端分页查询 ======
  const docsPageQuery = useDocumentsPage(
    kbId,
    {
      page,
      pageSize,
      q: normalizedKeyword || undefined,
      status: statusFilter === "all" ? undefined : statusFilter,
      sort: sortKey,
    },
    // 文档可能正在索引, 启用 3s 轮询让状态自动刷新
    { refetchInterval: 3000 }
  );
  const docsPage = docsPageQuery.data;
  const docs: any[] = docsPage?.items || [];
  const totalItems = docsPage?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const startIndex = (page - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, totalItems);
  // 后端已按 page/page_size 切片, 直接用 docs
  const pagedDocs = docs;

  // statusCounts 优先用后端 counts, 没有再 fallback 到当前页统计
  const statusCounts = useMemo(() => {
    if (docsPage?.counts) {
      return docsPage.counts;
    }
    const list = docs;
    return {
      all: list.length,
      ready: list.filter((d) => d.status === "ready").length,
      indexing: list.filter((d) => d.status === "indexing" || d.status === "pending").length,
      error: list.filter((d) => d.status === "error").length,
    };
  }, [docsPage, docs]);

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

  const buildChunkDetailHref = (docId: string) => {
    const query = new URLSearchParams();
    if (page !== 1) query.set("page", String(page));
    if (searchKeyword) query.set("q", searchKeyword);
    if (statusFilter !== "all") query.set("status", statusFilter);
    if (sortKey !== "created_desc") query.set("sort", sortKey);
    if (pageSize !== 10) query.set("pageSize", String(pageSize));
    const qs = query.toString();
    return `/knowledge/${kbId}/document/${docId}/chunks${qs ? `?${qs}` : ""}`;
  };

  const loading = docsPageQuery.isLoading || kbLoading;
  const totalDocsInKb =
    docsPage?.counts?.all ?? kb?.doc_count ?? 0;

  const hasNoDocs =
    !loading && totalDocsInKb === 0;

  const hasNoFilteredDocs =
    !loading && !hasNoDocs && totalItems === 0;

  const showEmptySearch =
    hasNoFilteredDocs && normalizedKeyword.length > 0;

  const showEmptyFilter =
    hasNoFilteredDocs &&
    normalizedKeyword.length === 0 &&
    statusFilter !== "all";

  return (
    <div className="h-screen overflow-hidden bg-[radial-gradient(1200px_circle_at_0%_0%,rgba(99,102,241,0.14),transparent_55%),radial-gradient(900px_circle_at_100%_0%,rgba(147,51,234,0.12),transparent_55%),linear-gradient(to_bottom,rgba(248,250,252,1),rgba(245,247,255,1))]">
      <div className="mx-auto flex h-full min-h-0 max-w-[1440px] gap-4 px-4 py-4 md:px-6 md:py-6">
        <div className="min-w-0 flex-1 overflow-hidden rounded-lg border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 shadow-sm flex min-h-0">
          <div className="flex h-full min-w-0 flex-1 overflow-hidden">
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
                onClick={() => setActiveTab("documents")}
                className={`flex h-9 w-full items-center justify-between rounded-md px-3 text-sm font-medium ${
                  activeTab === "documents"
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
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
                onClick={() => setActiveTab("pipeline")}
                className={`flex h-9 w-full items-center justify-between rounded-md px-3 text-sm font-medium ${
                  activeTab === "pipeline"
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <span className="flex items-center gap-2.5">
                  <RefreshCwIcon className="h-4 w-4" />
                  流水线
                </span>
                <ChevronRightIcon className={`h-3.5 w-3.5 opacity-60 ${activeTab === "pipeline" ? "" : "hidden"}`} />
              </button>
            </li>
            <li>
              <button
                type="button"
                onClick={() => setActiveTab("retrieval_test")}
                className={`flex h-9 w-full items-center justify-between rounded-md px-3 text-sm font-medium ${
                  activeTab === "retrieval_test"
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <span className="flex items-center gap-2.5">
                  <FlaskConicalIcon className="h-4 w-4" />
                  召回测试
                </span>
                <ChevronRightIcon className={`h-3.5 w-3.5 opacity-60 ${activeTab === "retrieval_test" ? "" : "hidden"}`} />
              </button>
            </li>
            <li>
              <button
                type="button"
                onClick={() => setActiveTab("settings")}
                className={`flex h-9 w-full items-center justify-between rounded-md px-3 text-sm font-medium ${
                  activeTab === "settings"
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <span className="flex items-center gap-2.5">
                  <SettingsIcon className="h-4 w-4" />
                  设置
                </span>
                <ChevronRightIcon className={`h-3.5 w-3.5 opacity-60 ${activeTab === "settings" ? "" : "hidden"}`} />
              </button>
            </li>
          </ul>
        </nav>

        <div className="border-t px-4 py-3 text-xs text-muted-foreground">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md bg-background/60 px-2.5 py-2">
              <div className="text-[10px] uppercase tracking-wide opacity-70">文档数</div>
              <div className="mt-0.5 text-sm font-medium text-foreground">
                {totalDocsInKb}
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
        {activeTab === "documents" ? (
          <DocumentsTabContent
            kbId={kbId}
            canManage={canManage}
            docsPageQuery={docsPageQuery}
            docs={docs}
            totalItems={totalItems}
            totalPages={totalPages}
            pagedDocs={pagedDocs}
            statusCounts={statusCounts}
            statusFilter={statusFilter}
            setStatusFilter={setStatusFilter}
            sortKey={sortKey}
            setSortKey={setSortKey}
            page={page}
            setPage={setPage}
            pageSize={pageSize}
            setPageSize={setPageSize}
            searchKeyword={searchKeyword}
            setSearchKeyword={setSearchKeyword}
            files={files}
            handlePickFiles={handlePickFiles}
            handleFileChange={handleFileChange}
            handleCancelFiles={handleCancelFiles}
            handleUpload={handleUpload}
            handleDelete={handleDelete}
            handleReindex={handleReindex}
            uploadDocs={uploadDocs}
            reindexDoc={reindexDoc}
            loading={loading}
            hasNoDocs={hasNoDocs}
            showEmptySearch={showEmptySearch}
            showEmptyFilter={showEmptyFilter}
            fileInputRef={fileInputRef}
            buildChunkDetailHref={buildChunkDetailHref}
          />
        ) : activeTab === "pipeline" ? (
          <PipelinePanel
            kbId={kbId}
            kb={kb}
            canManage={canManage}
            onGoDocuments={() => setActiveTab("documents")}
          />
        ) : activeTab === "retrieval_test" ? (
          <RetrievalTestPanel kbId={kbId} />
        ) : (
          <SettingsPanel kbId={kbId} kb={kb} canManage={canManage} />
        )}
      </main>
          </div>
        </div>
      </div>
    </div>
  );
}

// ====== Documents Tab Content ======
type DocumentsTabProps = {
  kbId: string;
  canManage: boolean;
  docsPageQuery: any;
  docs: any[];
  totalItems: number;
  totalPages: number;
  pagedDocs: any[];
  statusCounts: any;
  statusFilter: StatusFilter;
  setStatusFilter: React.Dispatch<React.SetStateAction<StatusFilter>>;
  sortKey: SortKey;
  setSortKey: React.Dispatch<React.SetStateAction<SortKey>>;
  page: number;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  pageSize: number;
  setPageSize: React.Dispatch<React.SetStateAction<number>>;
  searchKeyword: string;
  setSearchKeyword: React.Dispatch<React.SetStateAction<string>>;
  files: FileList | null;
  handlePickFiles: () => void;
  handleFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleCancelFiles: () => void;
  handleUpload: () => void;
  handleDelete: (docId: string) => void;
  handleReindex: (docId: string) => void;
  uploadDocs: any;
  reindexDoc: any;
  loading: boolean;
  hasNoDocs: boolean;
  showEmptySearch: boolean;
  showEmptyFilter: boolean;
  fileInputRef: React.RefObject<HTMLInputElement>;
  buildChunkDetailHref: (docId: string) => string;
};

function DocumentsTabContent(props: DocumentsTabProps) {
  const {
    kbId,
    canManage,
    docsPageQuery,
    docs,
    totalItems,
    totalPages,
    pagedDocs,
    statusCounts,
    statusFilter,
    setStatusFilter,
    sortKey,
    setSortKey,
    page,
    setPage,
    pageSize,
    setPageSize,
    searchKeyword,
    setSearchKeyword,
    files,
    handlePickFiles,
    handleFileChange,
    handleCancelFiles,
    handleUpload,
    handleDelete,
    handleReindex,
    uploadDocs,
    reindexDoc,
    loading,
    hasNoDocs,
    showEmptySearch,
    showEmptyFilter,
    fileInputRef,
    buildChunkDetailHref,
  } = props;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header + Toolbar (固定, 不滚动) */}
      <div className="flex flex-col gap-3 px-6 pt-6">
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
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-primary/30 bg-primary/5 px-3 py-2 text-xs">
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

        {/* Toolbar: status filters + search + sort */}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
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

      {/* Body (可滚动) */}
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
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
              <FileTextIcon className="h-8 w-8" />
            </div>
            <h2 className="mt-5 text-lg font-medium">暂无可查看文档</h2>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">
              该知识库还没有上传任何文档，或你暂无查看权限。
            </p>
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
        {!loading && !hasNoDocs && !showEmptySearch && !showEmptyFilter && pagedDocs.length > 0 && (
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
                          <Link
                            href={buildChunkDetailHref(doc.id)}
                            className="block truncate text-sm font-medium leading-snug hover:text-primary hover:underline"
                            title={doc.title}
                          >
                            {doc.title}
                          </Link>
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
                      <DocStatus kbId={kbId} doc={doc} detailHref={buildChunkDetailHref(doc.id)} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {(doc.status === "pending" || doc.status === "error") && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground/60 transition-colors hover:bg-primary/10 hover:text-primary"
                          onClick={() => handleReindex(doc.id)}
                          disabled={!canManage || reindexDoc.isPending}
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
                          disabled={!canManage}
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
    </div>
  );
}

// ====== Pipeline Panel (MVP) ======
function PipelinePanel({
  kbId,
  kb,
  canManage,
  onGoDocuments,
}: {
  kbId: string;
  kb: any;
  canManage: boolean;
  onGoDocuments: () => void;
}) {
  // 复用文档分页接口, 分别拉取: 全部 / 失败 / 处理中(含 pending)
  const allQuery = useDocumentsPage(
    kbId,
    { page: 1, pageSize: 50, status: undefined, sort: "created_desc" },
    { refetchInterval: 3000 }
  );
  const errorQuery = useDocumentsPage(
    kbId,
    { page: 1, pageSize: 20, status: "error", sort: "created_desc" },
    { refetchInterval: 3000 }
  );
  const processingQuery = useDocumentsPage(
    kbId,
    { page: 1, pageSize: 20, status: "indexing", sort: "created_desc" },
    { refetchInterval: 3000 }
  );
  const reindexDoc = useReindexDocument();

  const allData = allQuery.data;
  const counts = allData?.counts;
  const totalDocs = counts?.all ?? allData?.total ?? 0;
  const readyCount = counts?.ready ?? 0;
  const processingCount = counts?.indexing ?? 0; // 后端 indexing 已包含 pending
  const errorCount = counts?.error ?? 0;

  // 分块总数: 后端 KB 无聚合字段, 从全部列表(前 50 条)累加 chunk_count
  const totalChunks = useMemo(() => {
    const items: any[] = allData?.items || [];
    return items.reduce((sum, d) => sum + (d.chunk_count || 0), 0);
  }, [allData]);

  const errorDocs: any[] = errorQuery.data?.items || [];
  const processingDocs: any[] = processingQuery.data?.items || [];

  const loading = allQuery.isLoading || kb == null;

  const handleReindex = (docId: string) => {
    if (!canManage) return;
    reindexDoc.mutate(
      { kbId, docId },
      {
        onError: (e: any) => {
          alert("重新索引失败: " + (e?.message || "未知错误"));
        },
      }
    );
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center px-6 py-5 text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
      </div>
    );
  }

  // 空状态: 没有任何文档, 引导去文档 tab 上传
  if (totalDocs === 0) {
    return (
      <div className="px-6 py-5">
        <div className="mb-5">
          <h1 className="text-lg font-semibold">索引流水线</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            查看文档从上传、解析、分块到向量索引的处理状态。
          </p>
        </div>
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed bg-background px-6 py-12 text-center">
          <RefreshCwIcon className="h-8 w-8 text-muted-foreground/50" />
          <p className="mt-3 text-sm text-muted-foreground">
            还没有文档进入索引流水线。
          </p>
          <Button variant="outline" size="sm" className="mt-4" onClick={onGoDocuments}>
            <FileTextIcon className="mr-1.5 h-3.5 w-3.5" />
            前往文档 tab
          </Button>
        </div>
      </div>
    );
  }

  const stats = [
    { label: "文档总数", value: totalDocs, icon: FileTextIcon },
    { label: "已完成", value: readyCount, icon: CheckCircle2Icon, tone: "text-green-600" },
    { label: "处理中", value: processingCount, icon: Loader2, tone: "text-yellow-600" },
    { label: "失败", value: errorCount, icon: XIcon, tone: "text-red-600" },
    { label: "分块总数", value: totalChunks, icon: CopyIcon },
  ];

  const stages = [
    { title: "上传", desc: "文档进入知识库，生成文档记录。" },
    { title: "文档解析", desc: "提取 PDF / Word / Markdown / Excel / 图片等文件内容。" },
    { title: "文本分块", desc: "将长文本切分为可检索片段。" },
    { title: "向量化", desc: "使用 embedding 模型生成向量。" },
    { title: "索引入库", desc: "写入向量索引，供相似度检索使用。" },
    { title: "可召回", desc: "文档可被召回测试和聊天问答使用。" },
  ];

  return (
    <div className="px-6 py-5">
      {/* 标题 */}
      <div className="mb-5">
        <h1 className="text-lg font-semibold">索引流水线</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          查看文档从上传、解析、分块到向量索引的处理状态。
        </p>
      </div>

      {/* 状态总览 */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {stats.map((s) => {
          const StatIcon = s.icon;
          return (
            <div key={s.label} className="rounded-lg border bg-background p-3">
              <div className="flex items-center gap-2 text-muted-foreground">
                <StatIcon className={`h-4 w-4 ${s.tone || ""}`} />
                <span className="text-xs">{s.label}</span>
              </div>
              <div className="mt-1.5 text-2xl font-semibold tabular-nums">{s.value}</div>
            </div>
          );
        })}
      </div>

      {/* 流水线阶段说明 */}
      <section className="mb-6 rounded-lg border bg-background p-4">
        <h2 className="mb-3 text-sm font-semibold">流水线阶段</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {stages.map((s, i) => (
            <div key={s.title} className="rounded-md border bg-muted/30 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                  {i + 1}
                </span>
                <span className="text-sm font-medium">{s.title}</span>
                <Badge variant="secondary" className="ml-auto text-[10px]">
                  系统默认
                </Badge>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{s.desc}</p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          以上为索引流水线的标准阶段说明，不代表实时任务编排，当前版本暂不支持编辑。
        </p>
      </section>

      {/* 异常文档区 */}
      <section className="mb-6 rounded-lg border bg-background p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">异常文档</h2>
          <Badge variant={errorCount > 0 ? "destructive" : "secondary"}>{errorCount}</Badge>
        </div>
        {errorDocs.length === 0 ? (
          <p className="text-sm text-muted-foreground">没有失败文档，很好。</p>
        ) : (
          <div className="divide-y">
            {errorDocs.map((doc) => (
              <div key={doc.id} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{doc.title}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    上传于 {formatDate(doc.created_at)}
                  </div>
                </div>
                <Badge variant="destructive" className="shrink-0">
                  失败
                </Badge>
                {canManage ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={reindexDoc.isPending}
                    onClick={() => handleReindex(doc.id)}
                  >
                    <RefreshCwIcon className="mr-1.5 h-3.5 w-3.5" />
                    重新索引
                  </Button>
                ) : (
                  <span className="shrink-0 text-xs text-muted-foreground">只读权限</span>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 处理中区 */}
      <section className="mb-6 rounded-lg border bg-background p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">处理中</h2>
          <Badge variant="secondary">{processingCount}</Badge>
        </div>
        {processingDocs.length === 0 ? (
          <p className="text-sm text-muted-foreground">没有正在处理的文档。</p>
        ) : (
          <div className="divide-y">
            {processingDocs.map((doc) => (
              <div key={doc.id} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{doc.title}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    上传于 {formatDate(doc.created_at)}
                    {doc.chunk_count ? ` · ${doc.chunk_count} 分块` : ""}
                  </div>
                </div>
                <Badge variant="secondary" className="shrink-0">
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  {doc.status === "pending" ? "排队中" : "索引中"}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 索引配置只读 */}
      <section className="rounded-lg border bg-background p-4">
        <h2 className="mb-3 text-sm font-semibold">索引配置</h2>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">Embedding 模型</dt>
            <dd className="mt-0.5 text-sm font-medium">{kb?.embedding_model || "系统默认"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">默认分块策略</dt>
            <dd className="mt-0.5 text-sm font-medium">通用</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">默认 Top K</dt>
            <dd className="mt-0.5 text-sm font-medium">系统默认</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Rerank</dt>
            <dd className="mt-0.5 text-sm font-medium">按系统策略</dd>
          </div>
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">当前版本暂不支持在前端修改索引策略。</p>
      </section>
    </div>
  );
}

// ====== Settings Panel (MVP) ======
function SettingsPanel({
  kbId,
  kb,
  canManage,
}: {
  kbId: string;
  kb: any;
  canManage: boolean;
}) {
  const router = useRouter();
  const updateMutation = useUpdateKnowledgeBase();
  const deleteMutation = useDeleteKnowledgeBase();

  const [name, setName] = useState(kb?.name ?? "");
  const [description, setDescription] = useState(kb?.description ?? "");

  // 后端数据刷新后, 同步本地编辑态 (保存成功后 kb 重新拉取)
  useEffect(() => {
    setName(kb?.name ?? "");
    setDescription(kb?.description ?? "");
  }, [kb?.id, kb?.name, kb?.description]);

  if (!kb) {
    return (
      <div className="flex h-full items-center justify-center px-6 py-5 text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
      </div>
    );
  }

  const isDirty =
    name !== (kb.name ?? "") || description !== (kb.description ?? "");
  const canSave =
    canManage && name.trim() !== "" && isDirty && !updateMutation.isPending;

  const handleSave = () => {
    if (!canSave) return;
    updateMutation.mutate(
      {
        id: kbId,
        data: { name: name.trim(), description: description.trim() },
      },
      {
        onError: (e: any) => {
          alert("保存失败: " + (e?.message || "未知错误"));
        },
      }
    );
  };

  const handleDelete = () => {
    if (!canManage) {
      alert("无权限删除该知识库");
      return;
    }
    if (
      !confirm(
        "确定删除该知识库？该操作会删除知识库及其文档索引，无法恢复。"
      )
    )
      return;
    deleteMutation.mutate(kbId, {
      onSuccess: () => {
        router.push("/kb");
      },
      onError: (e: any) => {
        alert("删除失败: " + (e?.message || "未知错误"));
      },
    });
  };

  const departmentLabel = kb.department_name || "公共";
  const inputBase =
    "h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";

  return (
    <div className="overflow-y-auto px-6 py-5">
      <div className="mx-auto max-w-3xl">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">设置</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            管理知识库基础信息和危险操作。
          </p>
        </div>

        {/* 基础信息 */}
        <section className="rounded-lg border bg-background p-5">
          <h2 className="text-sm font-semibold">基础信息</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            知识库的名称与描述，仅管理员可修改。
          </p>

          <div className="mt-4 space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">知识库名称</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={!canManage || updateMutation.isPending}
                placeholder="知识库名称"
                className={inputBase}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">描述</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                disabled={!canManage || updateMutation.isPending}
                rows={4}
                placeholder="知识库描述"
                className="w-full resize-none rounded-md border border-input bg-background p-3 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-muted-foreground">
                  所属部门 / 公共
                </label>
                <div className="flex h-9 items-center rounded-md border bg-muted/30 px-3 text-sm text-foreground/90">
                  <Building2Icon className="mr-1.5 h-3.5 w-3.5 text-muted-foreground" />
                  {departmentLabel}
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-muted-foreground">
                  权限
                </label>
                <div className="flex h-9 items-center rounded-md border bg-muted/30 px-3 text-sm text-foreground/90">
                  {canManage ? (
                    <>
                      <SettingsIcon className="mr-1.5 h-3.5 w-3.5 text-primary" />
                      可管理
                    </>
                  ) : (
                    <>
                      <LockIcon className="mr-1.5 h-3.5 w-3.5 text-muted-foreground" />
                      只读
                    </>
                  )}
                </div>
              </div>
            </div>

            {!canManage && (
              <p className="text-xs text-muted-foreground">只读权限，无法修改。</p>
            )}

            {canManage && (
              <div className="flex justify-end">
                <Button
                  onClick={handleSave}
                  disabled={!canSave}
                  className="h-9 rounded-lg bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] px-4 text-sm text-white shadow-sm hover:opacity-90 disabled:opacity-50"
                >
                  {updateMutation.isPending ? (
                    <>
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                      保存中…
                    </>
                  ) : (
                    "保存"
                  )}
                </Button>
              </div>
            )}
          </div>
        </section>

        {/* 索引配置 (只读) */}
        <section className="mt-5 rounded-lg border bg-background p-5">
          <h2 className="text-sm font-semibold">索引配置</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            索引配置暂不支持在前端修改。
          </p>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <div className="text-xs text-muted-foreground">Embedding 模型</div>
              <div className="mt-1 break-all text-sm text-foreground/90">
                {kb.embedding_model || "—"}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">文档数</div>
              <div className="mt-1 text-sm text-foreground/90">{kb.doc_count ?? 0}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">创建时间</div>
              <div className="mt-1 text-sm text-foreground/90">
                {formatDate(kb.created_at)}
              </div>
            </div>
          </div>
        </section>

        {/* 危险操作 */}
        <section className="mt-5 rounded-lg border border-red-200/70 bg-red-50/30 p-5 dark:border-red-800/40 dark:bg-red-950/10">
          <h2 className="text-sm font-semibold text-red-700 dark:text-red-400">
            危险操作
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            删除后知识库及其文档索引将无法恢复。
          </p>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="text-sm font-medium text-foreground/90">删除知识库</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                永久删除知识库和所有文档索引
              </div>
            </div>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={!canManage || deleteMutation.isPending}
              className="h-9 shrink-0 rounded-lg text-sm"
            >
              {deleteMutation.isPending ? (
                <>
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  删除中…
                </>
              ) : (
                <>
                  <TrashIcon className="mr-1.5 h-4 w-4" />
                  删除知识库
                </>
              )}
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}

// ====== Retrieval Test Panel (MVP) ======
type ScoreBreakdown = {
  vector_distance: number | null;
  vector_score: number | null;
  vector_rank: number | null;
  bm25_score: number | null;
  bm25_rank: number | null;
  rrf_score: number | null;
  rrf_rank: number | null;
  rerank_score: number | null;
  rerank_rank: number | null;
};

type RetrievalChunk = {
  chunk_id: string | null;
  document_id: string | null;
  document_title: string;
  content: string;
  score: number;
  /** 分数类型: rerank=重排真实相关度; rrf=仅融合排序分(非相关度) */
  score_type?: "rerank" | "rrf";
  /** 各路分数拆解, 空值统一为 null */
  score_breakdown?: ScoreBreakdown;
  rank: number;
  metadata: Record<string, any>;
};

type RetrievalTimings = {
  embedding_ms?: number;
  retrieval_ms?: number;
  vector_sql_ms?: number;
  bm25_ms?: number;
  rrf_ms?: number;
  rerank_ms?: number;
  retrieval_total_ms?: number;
  rerank_decision?: string;
  rerank_reason?: string;
  total_ms?: number;
};

type RetrievalResult = {
  query: string;
  items: RetrievalChunk[];
  timings: RetrievalTimings;
};

type RetrievalHistoryItem = {
  id: string;
  query: string;
  createdAt: string;
  topK: number;
  threshold: number;
  useRerank: boolean;
  resultCount: number;
  topScore?: number;
  avgScore?: number;
  totalMs?: number;
};

function scoreColor(score: number): string {
  if (score >= 0.7) return "bg-emerald-500";
  if (score >= 0.4) return "bg-blue-500";
  return "bg-amber-500";
}

function scoreTextColor(score: number): string {
  if (score >= 0.7) return "text-emerald-600 dark:text-emerald-400";
  if (score >= 0.4) return "text-blue-600 dark:text-blue-400";
  return "text-amber-600 dark:text-amber-400";
}

// 详情字段空值统一显示 "—"，禁止出现 undefined / null / NaN
function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v as number)) return "—";
  return String(v);
}

// 相关度展示：根据 score_type 区分含义
// - rerank: 重排相关度，可显示为百分比
// - rrf: 仅融合排序分，禁止当相关度百分比展示
function ScoreBadge({ score, scoreType }: { score: number; scoreType?: string }) {
  const s = typeof score === "number" && !Number.isNaN(score) ? score : 0;
  if (scoreType === "rerank") {
    return (
      <div className="text-right">
        <div className="text-[10px] text-muted-foreground">重排相关度</div>
        <div className={`text-sm font-semibold tabular-nums ${scoreTextColor(s)}`}>
          {s.toFixed(4)}
        </div>
        <div className="text-[10px] text-muted-foreground">{(s * 100).toFixed(2)}%</div>
      </div>
    );
  }
  return (
    <div className="text-right">
      <div className="text-[10px] text-muted-foreground">RRF 融合分</div>
      <div className="text-sm font-semibold tabular-nums text-muted-foreground">
        {s.toFixed(4)}
      </div>
      <div className="text-[10px] text-muted-foreground">仅用于排序</div>
    </div>
  );
}

function highlightText(text: string, query: string) {
  const q = query.trim();
  if (!q) return text;
  const rawTerms = q.split(/\s+/).filter(Boolean);
  const terms = rawTerms.length > 1 ? rawTerms : [q];
  const uniq = Array.from(new Set(terms.map((t) => t.toLowerCase())));
  if (uniq.length === 0) return text;
  const escaped = uniq.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = text.split(re);
  return parts.map((part, i) =>
    part && uniq.includes(part.toLowerCase()) ? (
      <mark
        key={i}
        className="rounded-sm bg-yellow-100 text-yellow-900 dark:bg-yellow-900/40 dark:text-yellow-100"
      >
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

async function copyToClipboard(text: string) {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      throw new Error("clipboard unavailable");
    }
  } catch (e) {
    console.warn("[RetrievalTest] 复制失败:", e);
  }
}

function RetrievalSummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-background p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono tabular-nums text-foreground/90">{value}</span>
    </div>
  );
}

function RetrievalTestPanel({ kbId }: { kbId: string }) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [threshold, setThreshold] = useState(0.2);
  const [useRerank, setUseRerank] = useState(true);
  const retrieval = useRetrievalTest();
  const [expandedChunkIds, setExpandedChunkIds] = useState<Record<string, boolean>>({});
  const [history, setHistory] = useState<RetrievalHistoryItem[]>([]);

  const result = retrieval.data as RetrievalResult | undefined;
  const items = result?.items || [];
  const timings = result?.timings;
  const hasTested = !!result;
  const chatHref = query.trim()
    ? `/chat?kb_id=${kbId}&q=${encodeURIComponent(query.trim())}`
    : `/chat?kb_id=${kbId}`;

  const onSubmit = () => {
    const q = query.trim();
    if (!q) return;
    retrieval.mutate(
      {
        kbId,
        body: { query: q, top_k: topK, threshold, use_rerank: useRerank },
      },
      {
        onSuccess: (data: any) => {
          const dataItems: any[] = data?.items || [];
          const scores = dataItems.map((i) => i.score || 0);
          const topScore = scores.length ? Math.max(...scores) : undefined;
          const avgScore = scores.length
            ? scores.reduce((a, b) => a + b, 0) / scores.length
            : undefined;
          setHistory((prev) =>
            [
              {
                id: `${Date.now()}`,
                query: q,
                createdAt: new Date().toISOString(),
                topK,
                threshold,
                useRerank,
                resultCount: dataItems.length,
                topScore,
                avgScore,
                totalMs: data?.timings?.total_ms,
              },
              ...prev,
            ].slice(0, 20)
          );
        },
      }
    );
  };

  const onPickHistory = (item: RetrievalHistoryItem) => {
    setQuery(item.query);
    setTopK(item.topK);
    setThreshold(item.threshold);
    setUseRerank(item.useRerank);
  };

  const rerankDecision = timings?.rerank_decision;
  const rerankBadge =
    rerankDecision === "reranked"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800/50 dark:bg-emerald-950/40 dark:text-emerald-400"
      : "border-muted-foreground/20 bg-muted/40 text-muted-foreground";

  const timingMetrics: { label: string; value?: number; suffix?: string }[] = [
    { label: "向量化", value: timings?.embedding_ms, suffix: "ms" },
    { label: "检索", value: timings?.retrieval_ms, suffix: "ms" },
    { label: "向量 SQL", value: timings?.vector_sql_ms, suffix: "ms" },
    { label: "BM25", value: timings?.bm25_ms, suffix: "ms" },
    { label: "RRF 融合", value: timings?.rrf_ms, suffix: "ms" },
    { label: "重排序", value: timings?.rerank_ms, suffix: "ms" },
    { label: "总耗时", value: timings?.total_ms, suffix: "ms" },
  ];

  const resultCount = items.length;
  const topScore = items.length ? Math.max(...items.map((i) => i.score || 0)) : 0;
  const avgScore = items.length
    ? items.reduce((s, i) => s + (i.score || 0), 0) / items.length
    : 0;
  const docCount = new Set(items.map((i) => i.document_id).filter(Boolean)).size;
  const showLowTop = items.length > 0 && topScore < 0.3;
  const showLowAvg = items.length > 0 && avgScore < 0.25;

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[360px_1fr]">
      {/* Left: control + history */}
      <aside className="border-r bg-muted/10 overflow-y-auto px-4 py-5">
          <div className="flex items-center gap-2">
            <FlaskConicalIcon className="h-4 w-4 text-primary" />
            <h1 className="text-base font-semibold">召回测试</h1>
            <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-[10px] font-normal">
              MVP
            </Badge>
          </div>
          <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
            输入问题，查看当前知识库实际召回的分块、分数和耗时。
          </p>

          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={4}
            placeholder="例如: 如何申请报销?"
            className="mt-4 w-full resize-none rounded-lg border border-input bg-background/70 p-3 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
          />

          <div className="mt-3 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                召回数量
                <select
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="h-8 rounded-md border border-input bg-background/70 pl-2 pr-7 text-sm shadow-sm outline-none focus:border-primary/40"
                >
                  {[3, 5, 10, 20].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                阈值
                <select
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  className="h-8 rounded-md border border-input bg-background/70 pl-2 pr-7 text-sm shadow-sm outline-none focus:border-primary/40"
                >
                  {[0.1, 0.2, 0.3, 0.5].map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <button
              type="button"
              onClick={() => setUseRerank((v) => !v)}
              className={`flex h-8 w-full items-center justify-between rounded-md border px-3 text-sm transition-colors ${
                useRerank
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-input text-muted-foreground"
              }`}
            >
              <span>重排序</span>
              <span
                className={`flex h-3.5 w-6 items-center rounded-full p-0.5 transition-colors ${
                  useRerank ? "bg-primary" : "bg-muted"
                }`}
              >
                <span
                  className={`block h-2.5 w-2.5 rounded-full bg-white shadow-sm transition-transform ${
                    useRerank ? "translate-x-2.5" : "translate-x-0"
                  }`}
                />
              </span>
            </button>

            <Button
              onClick={onSubmit}
              disabled={!query.trim() || retrieval.isPending}
              className="h-9 w-full rounded-lg bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] text-sm text-white shadow-sm hover:opacity-90 disabled:opacity-50"
            >
              {retrieval.isPending ? (
                <>
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  测试中…
                </>
              ) : (
                <>
                  <FlaskConicalIcon className="mr-1.5 h-4 w-4" />
                  开始测试
                </>
              )}
            </Button>
          </div>

          {/* History */}
          <div className="mt-6">
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <HistoryIcon className="h-3.5 w-3.5" />
              测试历史
              {history.length > 0 && (
                <span className="text-[10px]">({history.length})</span>
              )}
            </div>
            {history.length === 0 ? (
              <p className="mt-2 text-[11px] leading-4 text-muted-foreground/70">
                测试后将在此保留最近 20 条记录。
              </p>
            ) : (
              <div className="mt-2 space-y-1.5">
                {history.map((h) => (
                  <button
                    key={h.id}
                    type="button"
                    onClick={() => onPickHistory(h)}
                    title="点击回填参数"
                    className="group block w-full rounded-lg border border-transparent bg-background/60 px-2.5 py-2 text-left transition-colors hover:border-primary/30 hover:bg-background"
                  >
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">
                        {h.query}
                      </span>
                      <span className="shrink-0 text-[10px] text-muted-foreground">
                        {h.resultCount} 块
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                      <span>Top {h.topScore !== undefined ? (h.topScore * 100).toFixed(0) : "—"}%</span>
                      <span>·</span>
                      <span>{h.totalMs !== undefined ? `${h.totalMs}ms` : "—"}</span>
                      <span className="ml-auto">
                        {new Date(h.createdAt).toLocaleTimeString()}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
      </aside>

      {/* Right: results */}
      <section className="min-w-0 overflow-y-auto px-6 py-5">
          {retrieval.isPending && (
            <div className="flex flex-col items-center justify-center py-20 text-center text-sm text-muted-foreground">
              <Loader2 className="mb-3 h-6 w-6 animate-spin text-primary" />
              正在召回分块…
            </div>
          )}

          {retrieval.isError && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800/50 dark:bg-red-950/40 dark:text-red-400">
                测试失败：{(retrieval.error as any)?.message || "未知错误"}
              </div>
            </div>
          )}

          {!retrieval.isPending && !retrieval.isError && items.length === 0 && !hasTested && (
            <div className="flex flex-col items-center justify-center py-20 text-center text-sm text-muted-foreground">
              输入查询语句后点击「开始测试」，召回结果会显示在这里。
            </div>
          )}

          {!retrieval.isPending && !retrieval.isError && items.length === 0 && hasTested && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="text-sm font-medium text-foreground">没有召回到相关分块</div>
              <p className="mt-2 max-w-md text-xs leading-5 text-muted-foreground">
                排查建议：
              </p>
              <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                <li>• 降低相似度阈值</li>
                <li>• 增大召回数量</li>
                <li>• 确认文档已索引完成</li>
                <li>• 换一个更具体的问题</li>
              </ul>
            </div>
          )}

          {!retrieval.isPending && !retrieval.isError && items.length > 0 && (
            <>
              {/* Summary metrics */}
              <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <RetrievalSummaryCard label="召回分块" value={String(resultCount)} />
                <RetrievalSummaryCard label="命中文档" value={String(docCount)} />
                <RetrievalSummaryCard label="Top1 分数" value={`${(topScore * 100).toFixed(1)}%`} />
                <RetrievalSummaryCard label="平均分" value={`${(avgScore * 100).toFixed(1)}%`} />
              </div>

              {showLowTop && (
                <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-800/50 dark:bg-amber-950/40 dark:text-amber-400">
                  最高分较低，可能存在召回质量不足，建议降低阈值或检查文档索引质量。
                </div>
              )}
              {showLowAvg && (
                <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-800/50 dark:bg-amber-950/40 dark:text-amber-400">
                  平均分偏低，召回结果可能不稳定。
                </div>
              )}

              {/* Summary */}
              <div className="mb-4 rounded-lg border bg-background p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-sm">
                    <span className="text-muted-foreground">召回 </span>
                    <span className="font-semibold text-foreground">{items.length}</span>
                    <span className="text-muted-foreground"> 个分块</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button asChild variant="outline" size="sm" className="h-7 gap-1 text-xs">
                      <Link href={chatHref}>
                        <MessageSquareIcon className="h-3.5 w-3.5" />
                        用当前问题去聊天
                      </Link>
                    </Button>
                    <Badge variant="outline" className={`rounded-md px-2 py-0.5 text-xs font-normal ${rerankBadge}`}>
                      {rerankDecision === "reranked" ? "已重排序" : "未重排序"}
                    </Badge>
                  </div>
                </div>

                {!useRerank ? (
                  <p className="mt-2 text-xs text-muted-foreground">用户关闭重排序</p>
                ) : rerankDecision || (timings?.rerank_reason && timings.rerank_reason !== "not_evaluated") ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Rerank: {rerankDecision || "—"}
                    {timings?.rerank_reason && timings.rerank_reason !== "not_evaluated" ? ` / ${timings.rerank_reason}` : ""}
                  </p>
                ) : null}

                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
                  {timingMetrics.map((m) => (
                    <div
                      key={m.label}
                      className="rounded-md bg-muted/40 px-2.5 py-2 text-center"
                    >
                      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        {m.label}
                      </div>
                      <div className="mt-0.5 text-sm font-medium text-foreground">
                        {m.value !== undefined && m.value !== null ? `${m.value}${m.suffix || ""}` : "—"}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Chunk cards */}
              <div className="flex flex-col gap-3">
                {items.map((item) => {
                  const chunkKey = item.chunk_id || String(item.rank);
                  const isExpanded = expandedChunkIds[chunkKey];
                  const shouldCollapse = item.content.length > 500;
                  const displayContent =
                    shouldCollapse && !isExpanded
                      ? item.content.slice(0, 500) + "..."
                      : item.content;
                  return (
                  <div
                    key={chunkKey}
                    className="rounded-lg border bg-background p-4 transition-colors hover:border-primary/30"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-semibold text-primary">
                          {item.rank}
                        </span>
                        <span className="truncate text-sm font-medium text-foreground" title={item.document_title}>
                          {item.document_title || "未知文档"}
                        </span>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => copyToClipboard(item.content)}
                          title="复制内容"
                          className="flex h-7 items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        >
                          <CopyIcon className="h-3.5 w-3.5" />
                          内容
                        </button>
                        <button
                          type="button"
                          onClick={() => copyToClipboard(item.chunk_id || "")}
                          title="复制 chunk_id"
                          className="flex h-7 items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        >
                          <CopyIcon className="h-3.5 w-3.5" />
                          ID
                        </button>
                        <ScoreBadge score={item.score} scoreType={item.score_type} />
                      </div>
                    </div>

                    {/* Score bar: 仅 rerank 路径展示相关度强度; rrf 不展示百分比强度 */}
                    {item.score_type === "rerank" ? (
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className={`h-full rounded-full ${scoreColor(item.score)}`}
                          style={{ width: `${Math.max(2, Math.min(100, item.score * 100))}%` }}
                        />
                      </div>
                    ) : (
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                        <div className="h-full w-full rounded-full bg-slate-300 dark:bg-slate-600" />
                      </div>
                    )}

                    <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-foreground/90">
                      {highlightText(displayContent, query)}
                    </p>

                    {shouldCollapse && (
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedChunkIds((prev) => ({ ...prev, [chunkKey]: !prev[chunkKey] }))
                        }
                        className="mt-2 text-xs font-medium text-primary hover:underline"
                      >
                        {isExpanded ? "收起" : "展开全文"}
                      </button>
                    )}

                    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                      <span className="font-mono">chunk_id: {item.chunk_id || "—"}</span>
                      <span className="font-mono">doc_id: {item.document_id || "—"}</span>
                    </div>

                    {item.metadata && Object.keys(item.metadata).length > 0 && (
                      <details className="mt-2 group">
                        <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
                          metadata
                        </summary>
                        <pre className="mt-1 overflow-x-auto rounded-md bg-muted/50 p-2 font-mono text-[11px] leading-5 text-foreground/80">
                          {JSON.stringify(item.metadata, null, 2)}
                        </pre>
                      </details>
                    )}

                    {/* 分数拆解详情: 空值统一显示 "—" */}
                    {item.score_breakdown && (
                      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-border/60 pt-3 text-[11px] sm:grid-cols-4">
                        <DetailItem label="向量排名" value={fmtNum(item.score_breakdown.vector_rank)} />
                        <DetailItem label="BM25 分数" value={fmtNum(item.score_breakdown.bm25_score)} />
                        <DetailItem label="BM25 排名" value={fmtNum(item.score_breakdown.bm25_rank)} />
                        <DetailItem label="RRF 融合分" value={fmtNum(item.score_breakdown.rrf_score)} />
                        <DetailItem label="RRF 排名" value={fmtNum(item.score_breakdown.rrf_rank)} />
                        <DetailItem label="Rerank 分数" value={fmtNum(item.score_breakdown.rerank_score)} />
                        <DetailItem
                          label="最终排名"
                          value={fmtNum(item.rank ?? item.score_breakdown.rerank_rank)}
                        />
                        <DetailItem label="类型" value={item.score_type === "rerank" ? "重排" : "RRF"} />
                      </div>
                    )}
                  </div>
                  );
                })}
              </div>
            </>
          )}
        </section>
      </div>
  );
}
