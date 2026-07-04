'use client';

import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { UploadIcon, FileIcon, TrashIcon, ArrowLeftIcon, RefreshCwIcon } from "lucide-react";
import { useDocuments, useUploadDocuments, useDeleteDocument, useReindexDocument, useIndexingStatus, useKnowledgeBase } from "@/hooks/use-api";

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

  const status = statusData?.status || doc.status;
  const progress = statusData?.progress || 0;
  const chunkCount = statusData?.chunk_count || doc.chunk_count || 0;
  const errorMessage = statusData?.error_message;

  if (isLoading && !statusData) {
    return <Badge variant="secondary">加载中...</Badge>;
  }
  
  if (status === "ready") {
    return (
      <div className="flex items-center gap-2">
        <Badge variant="default">已完成</Badge>
        <span className="text-xs text-muted-foreground">{chunkCount} chunks</span>
      </div>
    );
  }
  
  if (status === "indexing") {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex gap-2 items-center">
          <Badge variant="secondary">索引中 {progress}%</Badge>
          <span className="text-xs text-muted-foreground">({chunkCount} chunks)</span>
        </div>
        <Progress value={progress} className="h-1 w-24" />
      </div>
    );
  }
  
  if (status === "pending") {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex gap-2 items-center">
          <Badge variant="outline">等待中 0%</Badge>
        </div>
        <Progress value={0} className="h-1 w-24" />
      </div>
    );
  }
  
  if (status === "error") {
    return (
      <div className="flex flex-col gap-1">
        <Badge variant="destructive">失败</Badge>
        {errorMessage && <span className="text-xs text-red-500">{errorMessage}</span>}
      </div>
    );
  }
  
  return <Badge variant="outline">{status}</Badge>;
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
    } catch (e: any) {
      alert("上传失败: " + (e.message || "未知错误"));
    }
  };

  const handleDelete = async (docId: string) => {
    if (!canManage) {
      alert("无权限删除该文档");
      return;
    }
    if (!confirm("确定删除?")) return;
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
      alert("索引任务已启动");
    } catch (e: any) {
      alert("重新索引失败: " + (e.message || "未知错误"));
    }
  };

  if (isLoading || kbLoading) return <div className="p-6">加载中...</div>;

  return (
    <div className="h-full overflow-auto p-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-6">
        <div className="flex items-center gap-4">
          <Link href="/kb">
            <Button variant="ghost" size="sm">
              <ArrowLeftIcon className="h-4 w-4 mr-2" />
              返回
            </Button>
          </Link>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">文档管理</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {kb?.name} · {kb?.department_name || "公共知识库"}
            </p>
          </div>
        </div>
        
        {canManage && (
          <div className="flex items-center gap-2">
            <input
              type="file"
              accept=".pdf,.docx,.doc,.md,.txt,.xlsx,.xls,.png,.jpg,.jpeg,.gif,.webp,.bmp"
              multiple
              onChange={(e) => setFiles(e.target.files)}
              className="hidden"
              id="file-upload"
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => document.getElementById('file-upload')?.click()}
              className="h-10 bg-background/70 shadow-sm"
            >
              <UploadIcon className="h-4 w-4 mr-2" />
              选择文件
            </Button>
            {files && files.length > 0 && (
              <Button
                onClick={handleUpload}
                disabled={uploadDocs.isPending}
                className="h-10 bg-[linear-gradient(90deg,rgba(37,99,235,1),rgba(147,51,234,1))] text-white hover:opacity-95"
              >
                {uploadDocs.isPending ? "上传中..." : `上传 ${files.length} 个文件`}
              </Button>
            )}
          </div>
        )}
      </div>

      <div className="grid gap-4">
        {docs?.map((doc: any) => (
          <Card key={doc.id} className="border-border/70 bg-background/70 shadow-sm hover:shadow-md transition-shadow">
            <CardContent className="flex justify-between items-center p-4">
              <div className="flex items-center gap-3">
                <FileIcon className="h-5 w-5" />
                <div>
                  <p className="font-medium">{doc.title}</p>
                  <div className="flex gap-2 mt-1 items-center">
                    <DocStatus kbId={kbId} doc={doc} />
                    <span className="text-sm text-muted-foreground">
                      {(doc.file_size / 1024).toFixed(1)} KB
                    </span>
                  </div>
                </div>
              </div>
              
              {canManage && (
                <>
                  {(doc.status === "pending" || doc.status === "error") && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleReindex(doc.id)}
                      disabled={reindexDoc.isPending}
                    >
                      <RefreshCwIcon className="h-4 w-4 mr-1" />
                      重新索引
                    </Button>
                  )}
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => handleDelete(doc.id)}
                  >
                    <TrashIcon className="h-4 w-4" />
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        ))}
        
        {(!docs || docs.length === 0) && (
          <div className="text-center py-12 text-muted-foreground">
            暂无文档，请上传文档
          </div>
        )}
      </div>
    </div>
  );
}
