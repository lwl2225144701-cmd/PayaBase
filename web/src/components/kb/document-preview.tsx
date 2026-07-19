"use client";

import { useEffect, useRef, useState } from "react";
import { SearchIcon, XIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MarkdownRenderer } from "@/components/ui/markdown";
import type { Chunk } from "@/types";

interface DocumentPreviewProps {
  content: string | undefined;
  selectedChunk: Chunk | undefined;
  keyword: string;
  onKeywordChange: (keyword: string) => void;
  onSelectBlock?: (text: string) => void;
  isLoading?: boolean;
  error?: Error | null;
}

// 注意：去掉 DIV，避免 closestBlock 抓到 MarkdownRenderer 的外层包装 div
const BLOCK_TAGS = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "BLOCKQUOTE", "TD", "PRE"]);

function closestBlock(node: Node): HTMLElement | null {
  let el: HTMLElement | null = node.nodeType === Node.ELEMENT_NODE ? (node as HTMLElement) : node.parentElement;
  while (el && el !== document.body) {
    if (BLOCK_TAGS.has(el.tagName)) return el;
    el = el.parentElement;
  }
  return null;
}

function clearHighlights(container: HTMLElement) {
  const marks = container.querySelectorAll('[data-chunk-highlight="true"]');
  marks.forEach((mark) => {
    mark.classList.remove(
      "rounded-md",
      "border",
      "border-blue-400/60",
      "bg-blue-50/60",
      "dark:border-blue-500/50",
      "dark:bg-blue-900/20"
    );
    mark.removeAttribute("data-chunk-highlight");
  });
}

function highlightChunkInElement(container: HTMLElement, text: string): HTMLElement | null {
  if (!text) return null;
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    const content = node.textContent || "";
    const index = content.indexOf(text);
    if (index !== -1) {
      const block = closestBlock(node);
      if (block) {
        block.classList.add(
          "rounded-md",
          "border",
          "border-blue-400/60",
          "bg-blue-50/60",
          "dark:border-blue-500/50",
          "dark:bg-blue-900/20"
        );
        block.dataset.chunkHighlight = "true";
        return block;
      }
    }
  }
  return null;
}

function highlightTextInElement(container: HTMLElement, text: string): void {
  if (!text) return;
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    const content = node.textContent || "";
    const index = content.indexOf(text);
    if (index !== -1) {
      const range = document.createRange();
      range.setStart(node, index);
      range.setEnd(node, index + text.length);
      const mark = document.createElement("mark");
      mark.className = "rounded-sm bg-yellow-100 px-0.5 py-0.5 text-yellow-900 dark:bg-yellow-900/40 dark:text-yellow-100";
      mark.dataset.highlight = "true";
      range.surroundContents(mark);
      return;
    }
  }
}

function clearTextHighlights(container: HTMLElement) {
  const marks = container.querySelectorAll('[data-highlight="true"]');
  marks.forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parent.normalize();
  });
}

export function DocumentPreview({
  content,
  selectedChunk,
  keyword,
  onKeywordChange,
  onSelectBlock,
  isLoading,
  error,
}: DocumentPreviewProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [renderKey, setRenderKey] = useState(0);

  useEffect(() => {
    setRenderKey((k) => k + 1);
  }, [content, selectedChunk, keyword]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || !content) return;

    clearHighlights(container);
    clearTextHighlights(container);

    if (selectedChunk?.content) {
      const targetText = selectedChunk.content.slice(0, 200).trim();
      const block = highlightChunkInElement(container, targetText);
      if (block) {
        block.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }

    if (keyword.trim()) {
      highlightTextInElement(container, keyword.trim());
    }
  }, [renderKey, content, selectedChunk, keyword]);

  const renderBody = () => {
    if (isLoading) {
      return (
        <div className="space-y-3 p-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="h-3 animate-pulse rounded bg-muted" style={{ width: `${60 + (i % 5) * 10}%` }} />
          ))}
        </div>
      );
    }

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center p-8 text-center">
          <p className="text-sm text-red-600">原文加载失败：{error.message}</p>
        </div>
      );
    }

    if (!content) {
      return (
        <div className="flex flex-col items-center justify-center p-8 text-center text-sm text-muted-foreground">
          暂无原文内容
        </div>
      );
    }

    return (
      <div
        className="p-4 text-sm leading-7"
        ref={scrollRef}
        onClick={(e) => {
          if (!onSelectBlock) return;
          const block = closestBlock(e.target as Node);
          if (!block) return;
          const text = (block.textContent || "").trim();
          if (text.length >= 2) onSelectBlock(text);
        }}
        style={onSelectBlock ? { cursor: "pointer" } : undefined}
      >
        <MarkdownRenderer content={content} />
      </div>
    );
  };

  return (
    <Card className="flex h-full flex-col overflow-hidden border-border/60 bg-background/80 shadow-sm">
      <CardHeader className="shrink-0 border-b px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm font-semibold">原文预览</CardTitle>
          <div className="relative w-[180px]">
            <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={keyword}
              onChange={(e) => onKeywordChange(e.target.value)}
              placeholder="搜索原文内容"
              className="h-8 w-full rounded-md border border-input bg-background/70 pl-8 pr-7 text-xs outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/40 focus:ring-1 focus:ring-primary/20"
            />
            {keyword && (
              <button
                type="button"
                onClick={() => onKeywordChange("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <XIcon className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 min-h-0 p-0">
        <ScrollArea className="h-full">{renderBody()}</ScrollArea>
      </CardContent>
    </Card>
  );
}
