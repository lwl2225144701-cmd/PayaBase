"use client";

import { useEffect, useRef, useMemo, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Building2Icon,
  ChevronDownIcon,
  FileTextIcon,
  Grid3X3Icon,
  LayoutListIcon,
  Loader2,
  LockIcon,
  PlusIcon,
  SearchIcon,
  TrashIcon,
  XIcon,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { useKnowledgeBases, useDeleteKnowledgeBase, useCreateKnowledgeBase, useDepartments } from "@/hooks/use-api";
import { useCurrentUser } from "@/hooks/use-current-user";
import type { KnowledgeBase } from "@/types";

const iconThemes = [
  "bg-blue-50 text-blue-600 border-blue-100 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800/50",
  "bg-indigo-50 text-indigo-600 border-indigo-100 dark:bg-indigo-950/50 dark:text-indigo-400 dark:border-indigo-800/50",
  "bg-rose-50 text-rose-600 border-rose-100 dark:bg-rose-950/50 dark:text-rose-400 dark:border-rose-800/50",
  "bg-violet-50 text-violet-600 border-violet-100 dark:bg-violet-950/50 dark:text-violet-400 dark:border-violet-800/50",
  "bg-emerald-50 text-emerald-600 border-emerald-100 dark:bg-emerald-950/50 dark:text-emerald-400 dark:border-emerald-800/50",
];

function KBCardSkeleton() {
  return (
    <div className="h-[230px] animate-pulse rounded-lg border border-border/60 bg-background/70 p-5">
      <div className="flex items-start justify-between">
        <div className="h-9 w-9 rounded-lg bg-muted" />
        <div className="h-5 w-14 rounded-md bg-muted" />
      </div>
      <div className="mt-5 h-5 w-3/4 rounded bg-muted" />
      <div className="mt-2 space-y-1.5">
        <div className="h-3.5 w-full rounded bg-muted/70" />
        <div className="h-3.5 w-2/3 rounded bg-muted/70" />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="h-8 rounded bg-muted/60" />
        <div className="h-8 rounded bg-muted/60" />
      </div>
    </div>
  );
}

export default function KBListPage() {
  const { data: kbs, isLoading } = useKnowledgeBases();
  const deleteKB = useDeleteKnowledgeBase();
  const createKB = useCreateKnowledgeBase();
  const { isSuperAdmin, canManageKnowledgeBases, isLoading: userLoading } = useCurrentUser();
  const { data: departments } = useDepartments(isSuperAdmin);
  const [showForm, setShowForm] = useState(false);
  const [departmentFilter, setDepartmentFilter] = useState("all");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [departmentDropdownOpen, setDepartmentDropdownOpen] = useState(false);
  const [formDepartmentDropdownOpen, setFormDepartmentDropdownOpen] = useState(false);
  const [newKB, setNewKB] = useState({ name: "", description: "", department_id: "" });
  const departmentDropdownRef = useRef<HTMLDivElement>(null);
  const formDepartmentDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!departmentDropdownOpen && !formDepartmentDropdownOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!departmentDropdownRef.current?.contains(event.target as Node)) {
        setDepartmentDropdownOpen(false);
      }
      if (!formDepartmentDropdownRef.current?.contains(event.target as Node)) {
        setFormDepartmentDropdownOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [departmentDropdownOpen, formDepartmentDropdownOpen]);

  // ---- 数据 & 过滤 (hooks 必须在 early return 之前调用,避免 hooks 顺序不一致) ----
  const normalizedKeyword = searchKeyword.trim().toLowerCase();

  const baseFilteredKbs = useMemo(() => {
    if (!kbs) return [];
    if (departmentFilter === "all") return kbs;
    return kbs.filter((kb: KnowledgeBase) =>
      departmentFilter === "public"
        ? !kb.department_id
        : kb.department_id === departmentFilter
    );
  }, [kbs, departmentFilter]);

  const visibleKbs = useMemo(() => {
    if (!normalizedKeyword) return baseFilteredKbs;
    return baseFilteredKbs.filter((kb: KnowledgeBase) =>
      [kb.name, kb.description, kb.department_name]
        .filter(Boolean)
        .some((text) => String(text).toLowerCase().includes(normalizedKeyword))
    );
  }, [baseFilteredKbs, normalizedKeyword]);

  if (userLoading) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const handleDelete = async (id: string) => {
    const kb = kbs?.find((item: KnowledgeBase) => item.id === id);
    if (!kb?.can_manage) {
      alert("无权限删除该知识库");
      return;
    }
    if (!confirm("确定删除?")) return;
    try {
      await deleteKB.mutateAsync(id);
      alert("删除成功");
    } catch (e: any) {
      alert("删除失败: " + (e.message || "未知错误"));
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = {
        name: newKB.name,
        description: newKB.description,
        ...(isSuperAdmin && newKB.department_id ? { department_id: newKB.department_id } : {}),
      };
      await createKB.mutateAsync(payload);
      setShowForm(false);
      setNewKB({ name: "", description: "", department_id: "" });
      alert("创建成功");
    } catch (e: any) {
      alert("创建失败: " + (e.message || "未知错误"));
    }
  };

  // ---- 渲染 ----
  const publicCount = kbs?.filter((kb: KnowledgeBase) => !kb.department_id).length || 0;
  const privateCount = Math.max((kbs?.length || 0) - publicCount, 0);

  const departmentOptions = [
    { value: "all", label: "全部部门" },
    { value: "public", label: "公共知识库" },
    ...(departments || []).map((dept: any) => ({ value: dept.id, label: dept.name })),
  ];
  const formDepartmentOptions = [
    { value: "", label: "公共知识库" },
    ...(departments || []).map((dept: any) => ({ value: dept.id, label: dept.name })),
  ];
  const selectedDepartmentLabel =
    departmentOptions.find((item) => item.value === departmentFilter)?.label || "全部部门";
  const selectedFormDepartmentLabel =
    formDepartmentOptions.find((item) => item.value === newKB.department_id)?.label || "公共知识库";

  // ---- 渲染 ----
  const hasNoKbs = !isLoading && (!kbs || kbs.length === 0);
  const showEmptySearch = !isLoading && normalizedKeyword && baseFilteredKbs.length > 0 && visibleKbs.length === 0;
  const showEmptyFilter =
    !isLoading &&
    !normalizedKeyword &&
    !hasNoKbs &&
    visibleKbs.length === 0;
  const loading = isLoading || userLoading;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(800px_circle_at_0%_0%,rgba(99,102,241,0.06),transparent_55%)]">
      {/* ======== Header ======== */}
      <div className="relative z-30 shrink-0 border-b bg-background/50 px-6 pb-4 pt-5 backdrop-blur-sm">
        <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">知识库</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              管理你的文档、资料与 AI 问答知识来源
            </p>
          </div>
          {canManageKnowledgeBases ? (
            <Button
              onClick={() => setShowForm(!showForm)}
              className="h-10 rounded-lg bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] px-4 text-sm text-white shadow-sm hover:opacity-90"
            >
              <PlusIcon className="mr-2 h-4 w-4" />
              新建知识库
            </Button>
          ) : (
            <Button disabled className="h-10 rounded-lg px-4 text-sm">
              <LockIcon className="mr-2 h-4 w-4" />
              仅管理员可新建
            </Button>
          )}
        </div>

        {/* ======== Toolbar ======== */}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setDepartmentFilter("all")}
              className={`h-9 rounded-lg px-4 text-sm font-medium transition-colors ${
                departmentFilter === "all"
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              全部 <span className="ml-1.5 text-xs opacity-60">{kbs?.length || 0}</span>
            </button>
            <button
              type="button"
              onClick={() => setDepartmentFilter("public")}
              className={`h-9 rounded-lg px-4 text-sm font-medium transition-colors ${
                departmentFilter === "public"
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              公共 <span className="ml-1.5 text-xs opacity-60">{publicCount}</span>
            </button>
            <span className="h-9 rounded-lg px-4 pt-2 text-sm font-medium text-muted-foreground/50">
              私有 <span className="ml-1.5 text-xs opacity-60">{privateCount}</span>
            </span>

            {isSuperAdmin && (
              <div ref={departmentDropdownRef} className="relative">
                <button
                  type="button"
                  onClick={() => setDepartmentDropdownOpen((open) => !open)}
                  className="flex h-9 w-[140px] items-center justify-between gap-1.5 rounded-lg border border-input bg-background/70 px-3 text-sm font-medium shadow-sm transition-colors hover:border-primary/30"
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    <Building2Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{selectedDepartmentLabel}</span>
                  </span>
                  <ChevronDownIcon className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform ${departmentDropdownOpen ? "rotate-180" : ""}`} />
                </button>

                {departmentDropdownOpen && (
                  <div className="absolute left-0 top-[calc(100%+6px)] z-50 w-[180px] overflow-hidden rounded-lg border bg-background shadow-lg">
                    {departmentOptions.map((option) => {
                      const selected = option.value === departmentFilter;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => {
                            setDepartmentFilter(option.value);
                            setDepartmentDropdownOpen(false);
                          }}
                          className={`flex h-9 w-full items-center justify-between px-3 text-left text-sm transition-colors ${
                            selected
                              ? "bg-primary/10 text-primary"
                              : "text-foreground hover:bg-muted"
                          }`}
                        >
                          <span className="truncate">{option.label}</span>
                          {selected && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <div className="relative flex-1 md:w-[280px] md:flex-none">
              <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                value={searchKeyword}
                onChange={(e) => setSearchKeyword(e.target.value)}
                placeholder="搜索知识库…"
                className="h-9 w-full rounded-lg border border-input bg-background/70 pl-9 pr-8 text-sm shadow-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
              />
              {searchKeyword && (
                <button
                  type="button"
                  onClick={() => setSearchKeyword("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <XIcon className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <Button variant="outline" size="icon" className="h-9 w-9 bg-background/70 shadow-sm opacity-50" disabled title="网格视图">
              <Grid3X3Icon className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="icon" className="h-9 w-9 bg-background/70 shadow-sm opacity-50" disabled title="列表视图">
              <LayoutListIcon className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* ======== Create Form ======== */}
      {showForm && (
        <Card className="mx-6 mt-4 shrink-0 border-border/60 bg-background/80 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">新建知识库</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">名称</label>
                <Input
                  placeholder="输入知识库名称"
                  value={newKB.name}
                  onChange={(e) => setNewKB({ ...newKB, name: e.target.value })}
                  required
                  className="h-10 bg-background/70 shadow-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">描述</label>
                <Input
                  placeholder="简要描述知识库内容"
                  value={newKB.description}
                  onChange={(e) => setNewKB({ ...newKB, description: e.target.value })}
                  className="h-10 bg-background/70 shadow-sm"
                />
              </div>
              {isSuperAdmin && (
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">归属部门</label>
                  <div ref={formDepartmentDropdownRef} className="relative">
                    <button
                      type="button"
                      onClick={() => setFormDepartmentDropdownOpen((open) => !open)}
                      className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background/70 px-3 text-sm shadow-sm transition-colors hover:border-primary/30"
                    >
                      <span className="truncate">{selectedFormDepartmentLabel}</span>
                      <ChevronDownIcon className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${formDepartmentDropdownOpen ? "rotate-180" : ""}`} />
                    </button>

                    {formDepartmentDropdownOpen && (
                      <div className="absolute left-0 top-[calc(100%+6px)] z-50 max-h-56 w-full overflow-y-auto rounded-lg border bg-background shadow-lg">
                        {formDepartmentOptions.map((option) => {
                          const selected = option.value === newKB.department_id;
                          return (
                            <button
                              key={option.value || "public"}
                              type="button"
                              onClick={() => {
                                setNewKB({ ...newKB, department_id: option.value });
                                setFormDepartmentDropdownOpen(false);
                              }}
                              className={`flex h-9 w-full items-center justify-between px-3 text-left text-sm transition-colors ${
                                selected ? "bg-primary/10 text-primary" : "text-foreground hover:bg-muted"
                              }`}
                            >
                              <span className="truncate">{option.label}</span>
                              {selected && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              )}
              <div className="flex items-center gap-2">
                <Button
                  type="submit"
                  disabled={createKB.isPending}
                  className="h-10 bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] text-white hover:opacity-90"
                >
                  {createKB.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      创建中…
                    </>
                  ) : (
                    "创建"
                  )}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-10"
                  onClick={() => {
                    setShowForm(false);
                    setFormDepartmentDropdownOpen(false);
                    setNewKB({ name: "", description: "", department_id: "" });
                  }}
                >
                  取消
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* ======== Body ======== */}
      <div className="relative z-0 min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {/* Loading */}
        {loading && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <KBCardSkeleton key={i} />
            ))}
          </div>
        )}

        {/* Empty: no KBs at all & can manage */}
        {!loading && hasNoKbs && canManageKnowledgeBases && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <FileTextIcon className="h-8 w-8" />
            </div>
            <h2 className="mt-5 text-lg font-medium">还没有知识库</h2>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">
              创建你的第一个知识库，上传文档后即可进行 AI 检索与问答
            </p>
            <Button
              onClick={() => setShowForm(true)}
              className="mt-5 h-10 rounded-lg bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] px-5 text-sm text-white hover:opacity-90"
            >
              <PlusIcon className="mr-2 h-4 w-4" />
              创建知识库
            </Button>
          </div>
        )}

        {/* Empty: no KBs & cannot manage */}
        {!loading && hasNoKbs && !canManageKnowledgeBases && (
          <div className="flex flex-col items-center justify-center py-20 text-center text-sm text-muted-foreground">
            暂无可查看知识库
          </div>
        )}

        {/* Empty: search has results but filtered to nothing */}
        {!loading && showEmptySearch && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-sm text-muted-foreground">没有找到匹配的知识库</p>
            <button
              type="button"
              onClick={() => setSearchKeyword("")}
              className="mt-3 text-sm text-primary hover:underline"
            >
              清空搜索词
            </button>
          </div>
        )}

        {/* Empty: filter (department / public) returns nothing */}
        {!loading && showEmptyFilter && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-sm text-muted-foreground">当前筛选下暂无知识库</p>
            {canManageKnowledgeBases && (
              <p className="mt-2 max-w-sm text-xs text-muted-foreground/80">
                可以切换筛选条件,或创建新的知识库。
              </p>
            )}
          </div>
        )}

        {/* Card grid */}
        {!loading && visibleKbs && visibleKbs.length > 0 && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {visibleKbs.map((kb: KnowledgeBase, index: number) => (
              <Card
                key={kb.id}
                className="group flex min-h-[224px] flex-col overflow-hidden border-border/60 bg-background/80 shadow-sm transition-shadow hover:shadow-md"
              >
                <CardHeader className="flex-1 pb-0 pt-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${iconThemes[index % iconThemes.length]}`}>
                      <FileTextIcon className="h-4 w-4" />
                    </div>
                    <Badge
                      variant={kb.department_id ? "secondary" : "outline"}
                      className="max-w-[100px] truncate rounded-md px-2 py-0.5 text-xs font-normal"
                    >
                      {kb.department_name || "公共"}
                    </Badge>
                  </div>
                  <div className="pt-5">
                    <CardTitle className="line-clamp-1 text-base leading-snug">{kb.name}</CardTitle>
                    <CardDescription className="mt-2 line-clamp-2 min-h-[36px] text-xs leading-5">
                      {kb.description || "暂无描述"}
                    </CardDescription>
                  </div>
                </CardHeader>

                <CardContent className="pt-5">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="min-w-0">
                      <div className="whitespace-nowrap text-lg font-semibold tracking-tight">{kb.doc_count || 0}</div>
                      <div className="mt-0.5 text-xs text-muted-foreground">文档</div>
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {kb.can_manage ? (
                          <span className="text-emerald-600 dark:text-emerald-400">可管理</span>
                        ) : (
                          <span className="text-muted-foreground">只读</span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">权限</div>
                    </div>
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t pt-4">
                    <Link
                      href={`/kb/${kb.id}`}
                      className="text-sm font-medium text-primary transition-colors hover:text-primary/80 hover:underline"
                    >
                      进入管理
                    </Link>
                    {kb.can_manage ? (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground/60 transition-colors hover:bg-destructive/10 hover:text-destructive"
                        onClick={() => handleDelete(kb.id)}
                        title="删除知识库"
                      >
                        <TrashIcon className="h-4 w-4" />
                      </Button>
                    ) : (
                      <Button variant="ghost" size="icon" className="h-8 w-8" disabled title="无管理权限">
                        <LockIcon className="h-4 w-4 text-muted-foreground/40" />
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}

            {canManageKnowledgeBases && (
              <button
                type="button"
                onClick={() => setShowForm(true)}
                className="flex min-h-[224px] flex-col items-center justify-center rounded-lg border border-dashed border-primary/15 bg-background/40 p-6 text-center shadow-sm transition-all hover:border-primary/30 hover:bg-background/60"
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
                  <PlusIcon className="h-5 w-5" />
                </div>
                <div className="mt-4 text-sm font-medium">创建知识库</div>
                <div className="mt-1.5 text-xs text-muted-foreground">导入文档，构建专属知识库</div>
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
