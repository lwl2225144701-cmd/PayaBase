"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import { useState } from "react";
import type { Chunk } from "@/types";

interface ChunkMetadataProps {
  chunk: Chunk;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" && value.trim() === "") return "—";
  return String(value);
}

function MetadataItem({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };

  return (
    <div className="flex items-center justify-between gap-2 py-1.5 text-xs">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="truncate text-foreground" title={value}>{value}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          title="复制"
        >
          {copied ? <CheckIcon className="h-3 w-3 text-emerald-600" /> : <CopyIcon className="h-3 w-3" />}
        </button>
      </div>
    </div>
  );
}

export function ChunkMetadata({ chunk }: ChunkMetadataProps) {
  const items = [
    { label: "document_id", value: formatValue(chunk.document_id) },
    { label: "chunk_id", value: formatValue(chunk.chunk_id) },
    { label: "section_title", value: formatValue(chunk.section_title) },
    { label: "page_number", value: formatValue(chunk.page_number) },
    { label: "start_offset", value: formatValue(chunk.start_offset) },
    { label: "end_offset", value: formatValue(chunk.end_offset) },
    { label: "token_count", value: formatValue(chunk.token_count) },
    { label: "character_count", value: formatValue(chunk.character_count) },
    { label: "vector_status", value: formatValue(chunk.vector_status) },
    { label: "embedding_model", value: formatValue(chunk.embedding_model) },
    { label: "created_at", value: formatValue(chunk.created_at) },
  ];

  return (
    <div className="border-t bg-muted/20 px-4 py-3">
      <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
        {items.map((item) => (
          <MetadataItem key={item.label} label={item.label} value={item.value} />
        ))}
      </div>
    </div>
  );
}
