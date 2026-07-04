"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";

interface FeishuDocItem {
  id: string;
  name: string;
  url?: string;
}

interface FeishuAuthModalProps {
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

export default function FeishuAuthModal({ open, kbId, onClose }: FeishuAuthModalProps) {
  const [loading, setLoading] = useState(false);
  const [accessToken, setAccessToken] = useState("");
  const [docs, setDocs] = useState<FeishuDocItem[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<FeishuDocItem | null>(null);
  const popupRef = useRef<Window | null>(null);
  const intervalRef = useRef<number | null>(null);

  const canImport = useMemo(() => !!selectedDoc && !!accessToken && !!kbId && !loading, [selectedDoc, accessToken, kbId, loading]);

  useEffect(() => {
    if (!open) return;
    return () => {
      if (intervalRef.current) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      if (popupRef.current && !popupRef.current.closed) {
        popupRef.current.close();
      }
    };
  }, [open]);

  if (!open) return null;

  const loadDocs = async (token: string) => {
    setLoading(true);
    try {
      const list = await api.getFeishuFiles(token, 50);
      const mapped: FeishuDocItem[] = (list || []).map((item: any) => ({
        id: item.id,
        name: item.name,
        url: item.url || "",
      }));
      setDocs(mapped);
      if (mapped.length === 0) {
        alert("未获取到飞书文档列表，可手动粘贴文档链接到下方输入框");
      }
    } catch (e: any) {
      alert(`获取飞书文档列表失败: ${e.message || "未知错误"}`);
    } finally {
      setLoading(false);
    }
  };

  const startAuth = async () => {
    setLoading(true);
    try {
      const redirectUri = window.location.origin;
      const data = await api.getFeishuLoginUrl(redirectUri);
      const popup = window.open(data.auth_url, "feishu-auth", "width=720,height=760");
      if (!popup) {
        throw new Error("浏览器拦截了弹窗，请允许弹窗后重试");
      }
      popupRef.current = popup;

      intervalRef.current = window.setInterval(async () => {
        if (!popupRef.current || popupRef.current.closed) {
          if (intervalRef.current) window.clearInterval(intervalRef.current);
          intervalRef.current = null;
          return;
        }
        try {
          const href = popupRef.current.location.href;
          const url = new URL(href);
          const token = url.searchParams.get("access_token");
          if (!token) return;
          setAccessToken(token);
          popupRef.current.close();
          if (intervalRef.current) window.clearInterval(intervalRef.current);
          intervalRef.current = null;
          await loadDocs(token);
        } catch {
          // Still on Feishu domain, ignore cross-origin errors.
        }
      }, 1000);
    } catch (e: any) {
      alert(`飞书授权失败: ${e.message || "未知错误"}`);
      setLoading(false);
      return;
    }
    setLoading(false);
  };

  const importDoc = async () => {
    if (!selectedDoc || !kbId || !accessToken) return;
    setLoading(true);
    try {
      const created = await api.uploadSourceToKb({
        kb_id: kbId,
        source_type: "feishu",
        source_data: {
          file_key: selectedDoc.id,
          access_token: accessToken,
        },
        title: selectedDoc.name,
      });
      await pollIndexing(kbId, created.id);
      alert("飞书文档导入并索引完成");
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
          <h3 className="text-base font-semibold">导入飞书文档</h3>
          <button type="button" onClick={onClose} className="text-sm text-muted-foreground hover:text-foreground">
            关闭
          </button>
        </div>

        <div className="space-y-2">
          <button
            type="button"
            onClick={startAuth}
            disabled={loading}
            className="px-3 py-2 rounded-md border text-sm hover:bg-muted disabled:opacity-50"
          >
            {accessToken ? "重新授权飞书" : "授权飞书"}
          </button>
          {accessToken && (
            <p className="text-xs text-muted-foreground">授权成功，已获取用户访问令牌</p>
          )}
        </div>

        <div className="space-y-2 max-h-56 overflow-auto border rounded-md p-2">
          {docs.length === 0 ? (
            <p className="text-sm text-muted-foreground">授权后会加载文档列表</p>
          ) : (
            docs.map((doc) => (
              <label key={doc.id} className="flex items-center gap-2 text-sm p-1.5 rounded hover:bg-muted cursor-pointer">
                <input
                  type="radio"
                  name="feishu-doc"
                  checked={selectedDoc?.id === doc.id}
                  onChange={() => setSelectedDoc(doc)}
                />
                <span className="truncate">{doc.name}</span>
              </label>
            ))
          )}
        </div>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-2 rounded-md border text-sm">
            取消
          </button>
          <button
            type="button"
            onClick={importDoc}
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
