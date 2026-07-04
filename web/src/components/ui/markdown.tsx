'use client';

import { ReactNode, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import { Copy } from 'lucide-react';
import 'highlight.js/styles/github.css';

interface MarkdownProps {
  content: string;
  className?: string;
}

function getTextContent(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(getTextContent).join('');
  if (node && typeof node === 'object' && 'props' in node) {
    return getTextContent((node as { props?: { children?: unknown } }).props?.children);
  }
  return '';
}

function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string>('');
  const chartId = useMemo(
    () => `mermaid-${Math.random().toString(36).slice(2)}`,
    []
  );

  useEffect(() => {
    let cancelled = false;

    async function renderChart() {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: 'default',
        });
        const result = await mermaid.render(chartId, code);
        if (!cancelled) {
          setSvg(result.svg);
          setError('');
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Mermaid 渲染失败');
          setSvg('');
        }
      }
    }

    renderChart();
    return () => {
      cancelled = true;
    };
  }, [chartId, code]);

  if (svg) {
    return (
      <div
        className="my-3 overflow-x-auto rounded-md border bg-background p-3"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    );
  }

  if (error) {
    return (
      <div className="my-3 rounded-md border border-destructive/30 bg-destructive/5 p-3">
        <div className="mb-2 text-xs text-destructive">Mermaid 渲染失败，已显示源码</div>
        <pre className="overflow-x-auto text-xs">{code}</pre>
      </div>
    );
  }

  return (
    <div className="my-3 rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
      正在渲染流程图...
    </div>
  );
}

function CodeBlock({ className, children }: { className?: string; children: ReactNode }) {
  const code = getTextContent(children).replace(/\n$/, '');
  const language = /language-(\w+)/.exec(className || '')?.[1] || '';

  if (language === 'mermaid') {
    return <MermaidBlock code={code} />;
  }

  return (
    <div className="group relative mb-3 overflow-hidden rounded-md border bg-muted/60">
      <button
        type="button"
        className="absolute right-2 top-2 hidden h-7 w-7 items-center justify-center rounded border bg-background/80 text-muted-foreground shadow-sm group-hover:flex"
        onClick={() => navigator.clipboard?.writeText(code)}
        title="复制代码"
      >
        <Copy className="h-3.5 w-3.5" />
      </button>
      <pre className="overflow-x-auto p-3 pr-12 text-sm">
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

export function MarkdownRenderer({ content, className }: MarkdownProps) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-xl font-bold mb-2">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-lg font-bold mb-2">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-base font-bold mb-1">{children}</h3>
          ),
          p: ({ children }) => <p className="mb-2 leading-7">{children}</p>,
          ul: ({ children }) => (
            <ul className="list-disc ml-4 mb-2">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal ml-4 mb-2">{children}</ol>
          ),
          li: ({ children }) => <li className="mb-1 leading-7">{children}</li>,
          code: ({ className, children, ...props }) => {
            const language = /language-(\w+)/.exec(className || '')?.[1];
            if (language) {
              return <code className={className} {...props}>{children}</code>;
            }
            return (
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-sm" {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => {
            const child = Array.isArray(children) ? children[0] : children;
            if (child && typeof child === 'object' && 'props' in child) {
              const props = (child as { props?: { className?: string; children?: ReactNode } }).props || {};
              return <CodeBlock className={props.className}>{props.children}</CodeBlock>;
            }
            return (
              <pre className="mb-3 overflow-x-auto rounded-md border bg-muted/60 p-3 text-sm">
                {children}
              </pre>
            );
          },
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded-md border">
              <table className="w-full border-collapse text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted/70">{children}</thead>,
          th: ({ children }) => (
            <th className="border-b px-3 py-2 text-left font-semibold">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border-b px-3 py-2 align-top text-muted-foreground">{children}</td>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              className="text-primary underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-border pl-4 italic text-muted-foreground">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-4 border-border" />,
          strong: ({ children }) => (
            <strong className="font-bold">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          input: ({ type, checked }) => type === 'checkbox' ? (
            <input type="checkbox" checked={checked} className="accent-primary mr-1.5" readOnly />
          ) : null,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
