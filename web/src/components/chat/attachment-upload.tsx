"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Paperclip, X, FileText, Cloud, Building2 } from "lucide-react";
import FeishuAuthModal from "./feishu-auth-modal";
import DriveLinkModal from "./drive-link-modal";

const ALLOWED_TYPES = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/msword",
  "text/plain",
  "text/markdown",
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/bmp",
]);

const ALLOWED_EXTENSIONS = new Set([
  "pdf", "docx", "doc", "txt", "md", "png", "jpg", "jpeg", "gif", "webp", "bmp",
]);

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

export interface AttachmentState {
  id: string;
  file: File;
  status: "ready" | "error";
  error?: string;
  previewUrl?: string; // for images
}

function isImageFile(file: File): boolean {
  return file.type.startsWith("image/");
}

function getFileExtension(name: string): string {
  return name.split(".").pop()?.toLowerCase() || "";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

function validateFile(file: File): string | null {
  const ext = getFileExtension(file.name);
  if (!ALLOWED_EXTENSIONS.has(ext) && !ALLOWED_TYPES.has(file.type)) {
    return `不支持的文件格式: .${ext}`;
  }
  if (file.size > MAX_FILE_SIZE) {
    return `文件过大: ${formatSize(file.size)}，最大 10MB`;
  }
  return null;
}

let idCounter = 0;
function genId(): string {
  return `att_${Date.now()}_${++idCounter}`;
}

interface AttachmentUploadProps {
  attachments: AttachmentState[];
  onChange: (attachments: AttachmentState[]) => void;
  kbId?: string;
  disabled?: boolean;
}

export default function AttachmentUpload({
  attachments,
  onChange,
  kbId,
  disabled,
}: AttachmentUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [showFeishuModal, setShowFeishuModal] = useState(false);
  const [showDriveModal, setShowDriveModal] = useState(false);

  // Paste listener
  useEffect(() => {
    const handler = (e: ClipboardEvent) => {
      if (disabled) return;
      const files = e.clipboardData?.files;
      if (files && files.length > 0) {
        e.preventDefault();
        addFiles(Array.from(files));
      }
    };
    document.addEventListener("paste", handler);
    return () => document.removeEventListener("paste", handler);
  }, [disabled, attachments]);

  const addFiles = useCallback(
    (newFiles: File[]) => {
      const added: AttachmentState[] = [];
      for (const file of newFiles) {
        // Skip duplicates
        if (attachments.some((a) => a.file.name === file.name && a.file.size === file.size)) {
          continue;
        }
        const error = validateFile(file);
        const state: AttachmentState = {
          id: genId(),
          file,
          status: error ? "error" : "ready",
          error: error || undefined,
          previewUrl: isImageFile(file) && !error ? URL.createObjectURL(file) : undefined,
        };
        added.push(state);
      }
      if (added.length > 0) {
        onChange([...attachments, ...added]);
      }
    },
    [attachments, onChange]
  );

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files) {
      addFiles(Array.from(files));
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const removeAttachment = (id: string) => {
    const target = attachments.find((a) => a.id === id);
    if (target?.previewUrl) {
      URL.revokeObjectURL(target.previewUrl);
    }
    onChange(attachments.filter((a) => a.id !== id));
  };

  // Drag handlers
  const handleDragStart = (index: number) => {
    setDragIndex(index);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (targetIndex: number) => {
    if (dragIndex === null || dragIndex === targetIndex) {
      setDragIndex(null);
      return;
    }
    const updated = [...attachments];
    const [moved] = updated.splice(dragIndex, 1);
    updated.splice(targetIndex, 0, moved);
    onChange(updated);
    setDragIndex(null);
  };

  if (attachments.length === 0) {
    return (
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          className="inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed border-muted-foreground/30 bg-background/70 px-3 text-xs text-muted-foreground shadow-sm hover:border-muted-foreground/60 hover:text-foreground transition-colors disabled:opacity-50"
          title="上传附件 (支持粘贴 Ctrl+V)"
        >
          <Paperclip className="w-4 h-4" />
          <span>附件</span>
        </button>
        <button
          type="button"
          onClick={() => {
            if (!kbId) {
              alert("请先进入已绑定知识库的会话");
              return;
            }
            setShowFeishuModal(true);
          }}
          disabled={disabled}
          className="inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed border-muted-foreground/30 bg-background/70 px-3 text-xs text-muted-foreground shadow-sm hover:border-muted-foreground/60 hover:text-foreground transition-colors disabled:opacity-50"
          title="导入飞书文档"
        >
          <Building2 className="w-4 h-4" />
          <span>飞书文档</span>
        </button>
        <button
          type="button"
          onClick={() => {
            if (!kbId) {
              alert("请先进入已绑定知识库的会话");
              return;
            }
            setShowDriveModal(true);
          }}
          disabled={disabled}
          className="inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed border-muted-foreground/30 bg-background/70 px-3 text-xs text-muted-foreground shadow-sm hover:border-muted-foreground/60 hover:text-foreground transition-colors disabled:opacity-50"
          title="导入 Google Drive 文档"
        >
          <Cloud className="w-4 h-4" />
          <span>Drive文档</span>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          multiple
          accept=".pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.gif,.webp,.bmp"
          onChange={handleFileSelect}
        />
        <FeishuAuthModal
          open={showFeishuModal}
          kbId={kbId || ""}
          onClose={() => setShowFeishuModal(false)}
        />
        <DriveLinkModal
          open={showDriveModal}
          kbId={kbId || ""}
          onClose={() => setShowDriveModal(false)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Preview cards */}
      <div className="flex flex-wrap gap-2">
        {attachments.map((att, index) => (
          <div
            key={att.id}
            draggable={att.status !== "error"}
            onDragStart={() => handleDragStart(index)}
            onDragOver={handleDragOver}
            onDrop={() => handleDrop(index)}
            className={`relative group flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-sm max-w-[200px] transition-colors ${
              att.status === "error"
                ? "border-red-300 bg-red-50 text-red-700"
                : "border-border bg-muted/50 hover:bg-muted cursor-grab active:cursor-grabbing"
            } ${dragIndex === index ? "opacity-50" : ""}`}
          >
            {/* Thumbnail or icon */}
            {att.previewUrl ? (
              <img
                src={att.previewUrl}
                alt={att.file.name}
                className="w-10 h-10 rounded object-cover flex-shrink-0"
              />
            ) : (
              <div className="w-10 h-10 rounded bg-muted flex items-center justify-center flex-shrink-0">
                <FileText className="w-5 h-5 text-muted-foreground" />
              </div>
            )}

            {/* File info */}
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium">{att.file.name}</div>
              {att.status === "error" ? (
                <div className="text-[10px] text-red-500 mt-0.5">{att.error}</div>
              ) : (
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {formatSize(att.file.size)}
                </div>
              )}
            </div>

            {/* Delete button */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeAttachment(att.id);
              }}
              className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-background border border-border flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-destructive hover:text-destructive-foreground hover:border-destructive"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}

        {/* Add more button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          className="flex items-center justify-center w-10 h-10 rounded-lg border border-dashed border-muted-foreground/30 text-muted-foreground hover:border-muted-foreground/60 hover:text-foreground transition-colors disabled:opacity-50"
          title="添加更多文件"
        >
          <Paperclip className="w-4 h-4" />
        </button>
      </div>

      <div className="flex items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          multiple
          accept=".pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.gif,.webp,.bmp"
          onChange={handleFileSelect}
        />
        <button
          type="button"
          onClick={() => {
            if (!kbId) {
              alert("请先进入已绑定知识库的会话");
              return;
            }
            setShowFeishuModal(true);
          }}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground hover:text-foreground border border-dashed border-muted-foreground/30 rounded-lg hover:border-muted-foreground/60 transition-colors disabled:opacity-50"
        >
          <Building2 className="w-3.5 h-3.5" />
          <span>飞书文档</span>
        </button>
        <button
          type="button"
          onClick={() => {
            if (!kbId) {
              alert("请先进入已绑定知识库的会话");
              return;
            }
            setShowDriveModal(true);
          }}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground hover:text-foreground border border-dashed border-muted-foreground/30 rounded-lg hover:border-muted-foreground/60 transition-colors disabled:opacity-50"
        >
          <Cloud className="w-3.5 h-3.5" />
          <span>Drive文档</span>
        </button>
      </div>
      <FeishuAuthModal
        open={showFeishuModal}
        kbId={kbId || ""}
        onClose={() => setShowFeishuModal(false)}
      />
      <DriveLinkModal
        open={showDriveModal}
        kbId={kbId || ""}
        onClose={() => setShowDriveModal(false)}
      />
    </div>
  );
}
