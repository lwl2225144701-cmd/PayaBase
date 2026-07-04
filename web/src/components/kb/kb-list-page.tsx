"use client";

import { useEffect, useRef, useState } from "react";
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
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { useKnowledgeBases, useDeleteKnowledgeBase, useCreateKnowledgeBase, useDepartments } from "@/hooks/use-api";
import { useCurrentUser } from "@/hooks/use-current-user";
import type { KnowledgeBase } from "@/types";

export default function KBListPage() {
  const { data: kbs, isLoading } = useKnowledgeBases();
  const deleteKB = useDeleteKnowledgeBase();
  const createKB = useCreateKnowledgeBase();
  const { isSuperAdmin, canManageKnowledgeBases, isLoading: userLoading } = useCurrentUser();
  const { data: departments } = useDepartments(isSuperAdmin);
  const [showForm, setShowForm] = useState(false);
  const [departmentFilter, setDepartmentFilter] = useState("all");
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

  // 等待用户信息加载完成
  if (userLoading) {
    return <div className="p-6">加载中...</div>;
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

  if (isLoading) return <div className="p-6">加载中...</div>;

  const visibleKbs =
    departmentFilter === "all"
      ? kbs
      : kbs?.filter((kb: KnowledgeBase) =>
          departmentFilter === "public"
            ? !kb.department_id
            : kb.department_id === departmentFilter
        );
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
  const iconThemes = [
    "bg-blue-50 text-blue-600 border-blue-100",
    "bg-indigo-50 text-indigo-600 border-indigo-100",
    "bg-rose-50 text-rose-600 border-rose-100",
    "bg-violet-50 text-violet-600 border-violet-100",
    "bg-emerald-50 text-emerald-600 border-emerald-100",
  ];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(900px_circle_at_0%_0%,rgba(99,102,241,0.10),transparent_52%)]">
      <div className="relative z-30 shrink-0 border-b bg-background/35 px-6 pb-4 pt-5 backdrop-blur">
        <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">知识库</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {isSuperAdmin ? "超管视图：可管理全部部门知识库" : "部门视图：可查看本部门和公共知识库"}
            </p>
          </div>
          {canManageKnowledgeBases ? (
            <Button
              onClick={() => setShowForm(!showForm)}
              className="h-11 rounded-md bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] px-5 text-sm text-white shadow-sm hover:opacity-95"
            >
              <PlusIcon className="mr-2 h-4 w-4" />
              新建知识库
            </Button>
          ) : (
            <Button disabled className="h-11 rounded-md px-5 text-sm">
              <LockIcon className="mr-2 h-4 w-4" />
              仅管理员可新建
            </Button>
          )}
        </div>

        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setDepartmentFilter("all")}
              className={`h-10 rounded-md px-5 text-sm font-medium transition-colors ${
                departmentFilter === "all"
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              全部 <span className="ml-2 text-xs opacity-70">{kbs?.length || 0}</span>
            </button>
            <button
              type="button"
              onClick={() => setDepartmentFilter("public")}
              className={`h-10 rounded-md px-5 text-sm font-medium transition-colors ${
                departmentFilter === "public"
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              公共 <span className="ml-2 text-xs opacity-70">{publicCount}</span>
            </button>
            <span className="h-10 rounded-md px-5 pt-2.5 text-sm font-medium text-muted-foreground">
              私有 <span className="ml-2 text-xs opacity-70">{privateCount}</span>
            </span>

            {isSuperAdmin && (
              <div ref={departmentDropdownRef} className="relative">
                <button
                  type="button"
                  onClick={() => setDepartmentDropdownOpen((open) => !open)}
                  className="flex h-10 w-[150px] items-center justify-between gap-2 rounded-md border border-input bg-background/85 px-3 text-sm font-medium shadow-sm transition-colors hover:border-primary/30"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <Building2Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="truncate">{selectedDepartmentLabel}</span>
                  </span>
                  <ChevronDownIcon className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${departmentDropdownOpen ? "rotate-180" : ""}`} />
                </button>

                {departmentDropdownOpen && (
                  <div className="absolute left-0 top-[calc(100%+6px)] z-50 w-[180px] overflow-hidden rounded-md border border-border bg-background shadow-lg">
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
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                readOnly
                placeholder="搜索知识库..."
                className="h-10 w-[300px] rounded-md border border-input bg-background/75 pl-9 pr-3 text-sm shadow-sm outline-none placeholder:text-muted-foreground"
              />
            </div>
            <Button variant="outline" size="icon" className="h-10 w-10 bg-background/75 shadow-sm" disabled title="网格视图">
              <Grid3X3Icon className="h-4 w-4 text-primary" />
            </Button>
            <Button variant="outline" size="icon" className="h-10 w-10 bg-background/75 shadow-sm" disabled title="列表视图">
              <LayoutListIcon className="h-4 w-4 text-muted-foreground" />
            </Button>
          </div>
        </div>
      </div>

      {showForm && (
        <Card className="mx-6 mt-5 shrink-0 border-border/70 bg-background/80 shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">新建知识库</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-4">
              <Input
                placeholder="名称"
                value={newKB.name}
                onChange={(e) => setNewKB({ ...newKB, name: e.target.value })}
                required
                className="h-10 bg-background/70 shadow-sm"
              />
              <Input
                placeholder="描述"
                value={newKB.description}
                onChange={(e) => setNewKB({ ...newKB, description: e.target.value })}
                className="h-10 bg-background/70 shadow-sm"
              />
              {isSuperAdmin && (
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
                    <div className="absolute left-0 top-[calc(100%+6px)] z-50 max-h-56 w-full overflow-y-auto rounded-md border border-border bg-background shadow-lg">
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
              )}
              <div className="flex items-center gap-2">
                <Button
                  type="submit"
                  disabled={createKB.isPending}
                  className="h-10 bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] text-white hover:opacity-95"
                >
                  {createKB.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  创建
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

      <div className="relative z-0 min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {visibleKbs?.map((kb: KnowledgeBase, index: number) => {
          const syncRate = Math.max(92, Math.min(99, 99 - (index % 4) * 2));
          const updateText = index % 3 === 0 ? "2小时前" : index % 3 === 1 ? "1天前" : "3天前";
          return (
            <Card key={kb.id} className="group relative min-h-[236px] overflow-hidden border-border/70 bg-background/85 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md">
              <CardHeader className="pb-0 pt-5">
                <div className="flex items-start justify-between gap-3">
                  <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${iconThemes[index % iconThemes.length]}`}>
                    <FileTextIcon className="h-5 w-5" />
                  </div>
                  <Badge variant={kb.department_id ? "secondary" : "outline"} className="max-w-[96px] truncate rounded-md px-2 py-1 text-xs">
                    {kb.department_name || "公共"}
                  </Badge>
                </div>
                <div className="pt-5">
                  <CardTitle className="line-clamp-1 text-base">{kb.name}</CardTitle>
                  <CardDescription className="mt-2 line-clamp-2 min-h-[36px] text-xs leading-5">
                    {kb.description || "个人知识资料沉淀、检索与问答"}
                  </CardDescription>
                </div>
              </CardHeader>

              <CardContent className="pt-6">
                <div className="grid grid-cols-3 gap-2">
                  <div className="min-w-0">
                    <div className="whitespace-nowrap text-xl font-semibold tracking-tight">{kb.doc_count || 0}</div>
                    <div className="mt-1 text-xs leading-4 text-muted-foreground">文档数</div>
                  </div>
                  <div className="min-w-0">
                    <div className="whitespace-nowrap text-xl font-semibold tracking-tight">{syncRate}%</div>
                    <div className="mt-1 text-xs leading-4 text-muted-foreground">向量化</div>
                  </div>
                  <div className="min-w-0">
                    <div className="whitespace-nowrap text-xl font-semibold tracking-tight">{updateText}</div>
                    <div className="mt-1 text-xs leading-4 text-muted-foreground">更新</div>
                  </div>
                </div>

                <div className="mt-5 flex items-center justify-between border-t pt-4">
                  <Link href={`/kb/${kb.id}`} className="text-sm font-medium text-primary hover:underline">
                    进入管理
                  </Link>
                  {kb.can_manage ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      onClick={() => handleDelete(kb.id)}
                      title="删除知识库"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </Button>
                  ) : (
                    <Button variant="ghost" size="icon" className="h-8 w-8" disabled title="无管理权限">
                      <LockIcon className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}

        {canManageKnowledgeBases && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="flex min-h-[236px] flex-col items-center justify-center rounded-lg border border-dashed border-primary/20 bg-background/45 p-6 text-center shadow-sm transition-colors hover:border-primary/40 hover:bg-background/70"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
              <PlusIcon className="h-6 w-6" />
            </div>
            <div className="mt-4 text-base font-medium">创建知识库</div>
            <div className="mt-2 text-sm text-muted-foreground">导入文档，构建专属知识库</div>
          </button>
        )}

        {(!visibleKbs || visibleKbs.length === 0) && !canManageKnowledgeBases && (
          <div className="col-span-full rounded-lg border border-dashed bg-background/60 py-14 text-center text-sm text-muted-foreground">
            暂无可查看知识库
          </div>
        )}
        </div>
      </div>
    </div>
  );
}
