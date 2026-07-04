"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";

interface DrivePreview {
  source_url: string;
  file_id: string;
  file_name: string;
  file_type: string;
  file_size: number;
  content_type?: string;
}

interface DriveLinkModalProps {
  open: boolean;
  kbId: string;
  onClose: () => void;
}

async function pollIndexing(kbId: string, docId: string): Promise<void> {
  const maxRounds = 120;
  for (let i = 0; i < maxRounds; i++) {
    const status = await api.getIndexingStatus(kbId, docId);
    if (status.status === "ready") return;
    if (status.status === "failed" || status.status === "error") {
      throw new Error(status.error_message || "索引失败");
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("索引超时，请稍后在知识库页面查看状态");
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)}MB`;
}

export default function DriveLinkModal({ open, kbId, onClose }: DriveLinkModalProps) {
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<DrivePreview | null>(null);
  const [loading, setLoading] = useState(false);

  const canImport = useMemo(() => !!preview && !!kbId && !loading, [preview, kbId, loading]);

  if (!open) return null;

  const handlePreview = async () => {
    if (!url.trim()) {
      alert("请输入 Google Drive 文档链接");
      return;
    }
    setLoading(true);
    try {
      const data = await api.previewGoogleDrive(url.trim());
      setPreview(data);
    } catch (e: any) {
      alert(`链接解析失败: ${e.message || "未知错误"}`);
      setPreview(null);
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    if (!preview || !kbId) return;
    setLoading(true);
    try {
      const created = await api.uploadSourceToKb({
        kb_id: kbId,
        source_type: "google_drive",
        source_data: { url: preview.source_url },
        title: preview.file_name,
      });
      await pollIndexing(kbId, created.id);
      alert("Google Drive 文档导入并索引完成");
      onClose();
    } catch (e: any) {
      alert(`导入失败: ${e.message || "未知错误"}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/45 flex items-center justify-center p-4">
      <div className="w-full max-w-xl rounded-lg bg-background border shadow-lg p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold">导入 Google Drive 文档</h3>
          <button type="button" onClick={onClose} className="text-sm text-muted-foreground hover:text-foreground">
            关闭
          </button>
        </div>

        <div className="space-y-2">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="粘贴 Google Drive 链接"
            className="w-full rounded-md border px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={handlePreview}
            disabled={loading}
            className="px-3 py-2 rounded-md border text-sm hover:bg-muted disabled:opacity-50"
          >
            解析链接
          </button>
        </div>

        <div className="rounded-md border p-3 text-sm">
          {!preview ? (
            <span className="text-muted-foreground">解析后显示文档信息</span>
          ) : (
            <div className="space-y-1">
              <p><span className="text-muted-foreground">文件名：</span>{preview.file_name}</p>
              <p><span className="text-muted-foreground">类型：</span>{preview.file_type}</p>
              <p><span className="text-muted-foreground">大小：</span>{formatSize(preview.file_size)}</p>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-2 rounded-md border text-sm">
            取消
          </button>
          <button
            type="button"
            onClick={handleImport}
            disabled={!canImport}
            className="px-3 py-2 rounded-md bg-primary text-primary-foreground text-sm disabled:opacity-50"
          >
            导入并索引
          </button>
        </div>
      </div>
    </div>
  );
}
